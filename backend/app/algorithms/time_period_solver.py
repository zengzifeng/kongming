from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import ceil

from ..utils.errors import AlgorithmError

from ._shared import SolverEconomicsMixin
from .base import (
    ConstraintHit,
    DemandSnapshotItem,
    PolicyActionDraft,
    PolicyInputSnapshot,
    PolicyResult,
)

# 浮点护栏：容量求和会有残差，用它判断“缺口是否已实质填满 / 是否还有可分配容量”。
EPS = 1e-6
# 收益护栏：收益已按「元」口径（TPM×分钟÷1e6×单价），量级远小于 TPM，故用独立的更细阈值，
# 避免用 TPM 尺度的 EPS 误判「微小但真实为正」的收益改进。
REV_EPS = 1e-9



@dataclass
class _Candidate:
    demand: DemandSnapshotItem
    unit_self_revenue: float
    best_vendor: dict | None
    purchase_discount: float
    must_move: bool
    series: list[tuple[str, float]]       # [(ts, tpm)] 该客户时段业务量
    peak_tpm: float                        # 时段内峰值 TPM
    peak_vendor_gap: float                 # 峰值处“当前走三方、可回收”的量 = peak * (1 - self_ratio)
    score: float


class TimePeriodSolver(SolverEconomicsMixin):
    """时间段调整：看整段拟合业务量曲线，做「一次」机器重分配，最大化自建集群整段收入积分。

    与 realtime 的区别：机器只调一次、全时段固定、按峰值定容、收益=调整前后收入积分之差。
    机器总量守恒（只在集群间重分配，不新增）。
    """

    name = "time_period"

    def solve(self, snapshot: PolicyInputSnapshot) -> PolicyResult:
        if not snapshot.demands:
            raise AlgorithmError("快照中无可处理需求", code="ALGORITHM_FAILED")
        if not snapshot.resources or not snapshot.vendors:
            raise AlgorithmError("快照缺少资源或三方供应数据", code="ALGORITHM_FAILED")
        clusters = [dict(c) for c in snapshot.resources.get("clusters", [])]
        if not clusters:
            raise AlgorithmError("快照缺少自建集群数据", code="ALGORITHM_FAILED")

        model_prices = snapshot.params.get("model_prices", {})
        vendors = snapshot.vendors
        timeline = self._timeline(snapshot.demands)

        # 固定档位客户（如金山云）：只计入峰值可行性，不参与水位线优化——按当前自建/三方占比承载不动。
        # 其全部 uid(customer_code) 由 build_run_snapshot 从 config 解析后注入 params.fixed_profile_codes。
        # 注：当前这些客户自建占比≈0（全走三方），故不占用自建产能、无需为其预留容量；若将来固定档位
        # 客户有非零自建，需在水位注水前按其当前自建量预留集群容量（此处暂不处理）。
        fixed_codes = set(snapshot.params.get("fixed_profile_codes", []))
        opt_demands = ([d for d in snapshot.demands if d.customer_code not in fixed_codes]
                       if fixed_codes else snapshot.demands)

        # 峰值可行性硬约束基准：逐模型客户波形总需求峰值 / 三方额度 / 需保留的最小自建容量。
        # min_self_required = max(0, 峰值 − 三方额度)：三方接不住的那部分峰值必须由自建兜底，
        # 是「机器最多能挪走到什么程度」的物理下限（削峰可把峰值外抛给三方，但外抛不掉的必须留自建）。
        # 峰值需求对**全体需求（含固定档位客户）**求和：固定档位客户的量也必须被自建+三方覆盖。
        peak_demand = self._peak_demand_by_model(snapshot.demands, timeline, clusters)

        vendor_cap = self._vendor_cap_by_model(vendors)
        min_self_required = {m: max(0.0, peak_demand.get(m, 0.0) - vendor_cap.get(m, 0.0))
                             for m in peak_demand}

        # ---- A. 客户经济学（时间不变量）+ B. 需求时序剖面 ----（固定档位客户不进候选，不设水位）
        candidates, rejected = self._build_candidates(opt_demands, vendors, model_prices, timeline)
        candidates.sort(key=lambda c: c.score, reverse=True)

        # ---- C. 一次机器重分配：按“每机器边际收入面积”配齐（机会成本加权，不只按峰值台数）----
        machines_before = {c["cluster_name"]: int(c.get("machine_count", 0) or 0) for c in clusters}
        node_moves, accepted, rejected = self._plan_reallocation(
            candidates, clusters, rejected, timeline, min_self_required)
        # C 阶段腾挪也遵守「整体自建收入净增」门槛（与 C2 一致）：把 C 产出的 moves 从「无腾挪」基线
        # 起逐条重放，只保留真正抬高全体自建收入积分的腾挪，其余回滚——避免关注集群内产能不足时，
        # 为覆盖某模型忙时峰值而拆掉更高价值模型的机器、导致整体自建收入不升反降。
        node_moves = self._keep_net_positive_moves(
            candidates, clusters, timeline, node_moves, machines_before)


        # ---- C2. 模型级供需再平衡（跨模型抢机器）：把「容量≫峰值需求」的富余模型机器，挪给
        #      「需求>容量、量堆三方」的紧缺模型。**solver 内默认关**（保持直接调用/既有测试基线不变）；
        #      生产由 policy_service 按 config MODEL_REBALANCE_ENABLED(默认True) 注入 params 打开。
        #      约束：峰值可承接 + 整体自建收入净增 + 一台机器只搬一次（反两跳中转套利）+ 专属只供不收。
        rebalance_diag: dict = {}
        if snapshot.params.get("enable_model_rebalance", False):
            moves2, rebalance_diag = self._rebalance_by_model_gap(
                candidates, clusters, timeline, peak_demand, vendor_cap)
            node_moves = node_moves + moves2
        machines_after = {c["cluster_name"]: int(c.get("machine_count", 0) or 0) for c in clusters}
        # 集群粒度聚合：同一 (源集群→目标集群, 模型) 的多次腾挪合并成一条，避免海量单机记录。
        node_moves = self._aggregate_node_moves(node_moves)
        # 模型级再平衡的 moves 同样聚合（报告/前端会读 summary.model_rebalance.moves）。
        if rebalance_diag.get("moves"):
            rebalance_diag["moves"] = self._aggregate_node_moves(rebalance_diag["moves"])


        # 成案终检：机器挪动后，逐模型「自建+三方」是否仍覆盖该模型客户波形峰值。
        feasibility = self._check_peak_feasibility(clusters, peak_demand, vendor_cap)

        # 每模型调整后的自建容量（machine_count 已被 _plan_reallocation 就地更新）
        model_self_capacity = self._model_capacity(clusters)

        # ---- D. 固定水位线：机器调整后「一次性」设定每个客户的自建TPM上限（水位线），此后不随时间变化。 ----
        # 削峰优先（无保底）：当前自建与待回收三方一视同仁，从 0 做纯边际收入注水，突刺形状的当前自建
        # 也会被削峰。kept = 实际拿到自建容量（wm>0）的客户，供汇总展示。
        considered = accepted            # 进入 D 的全体候选（保留，用于 before/after 积分口径一致）
        watermarks, kept = self._compute_watermarks(considered, clusters, timeline)

        # ---- 时序积分：before/after 都对**全体候选**积分（wm=0 的被削客户 after 自建=0、before=当前自建），
        #      这样把"当前自建被削峰挖回三方"的损失正确计入 gain，不虚高。 ----
        after = self._integrate(considered, watermarks, timeline, adjust=True)
        # before 基线（现状自建）也必须只算「关注集群实际能承接」的量：现状自建占比作用在拟合忙时
        # 峰值波形上，若不按物理产能封顶，会得到集群根本跑不出的自建量，使 after 恒低于 before、假性亏损。
        # 用挪机器前(machines_before)的产能、按 _draw（含专属集群归属）逐时点给现状自建量封顶。
        before = self._before_self_revenue(considered, clusters, timeline, machines_before)
        revenue_gain = after["self_revenue"] - before["self_revenue"]

        accepted = kept                  # 汇总/约束里的 accepted 只列真正拿到自建的客户

        # 腾挪前后利用率：用**本次方案规划的自建峰值**（水位注水后 after 的逐时自建量）而非当前监控自建量，
        # 否则大部分需求当前在三方、监控自建≈0，利用率会失真为~0。口径=模型级：该模型规划自建峰值 /
        # 该模型集群总容量（分别按腾挪前/后机器数）。
        # 腾挪前后利用率（面积口径）：该模型所有客户自建波形叠加的承接面积 / 集群承载能力面积
        # （容量 × 时段总分钟）。分子用规划/存量自建量，非当前监控自建量。
        model_self_area = self._model_self_area(after, snapshot.demands, timeline)
        total_minutes = sum(self._slot_minutes(timeline).values())
        self._enrich_move_utilization(node_moves, model_self_area, total_minutes,
                                      clusters, machines_before, machines_after)
        if rebalance_diag.get("moves"):
            self._enrich_move_utilization(rebalance_diag["moves"], model_self_area, total_minutes,
                                          clusters, machines_before, machines_after)

        # ---- E. 约束体检 ----
        constraints = self._build_constraints(
            candidates, accepted, rejected, revenue_gain, after, node_moves,
            machines_before, machines_after,
        )
        constraints.append(self._peak_feasibility_constraint(feasibility))

        watermark_changes = after["watermarks"]
        actions: list[PolicyActionDraft] = []
        for mv in node_moves:
            actions.append(PolicyActionDraft(action_type="node_move", payload=mv, expected_gain=0.0))
        for wm in watermark_changes:
            actions.append(PolicyActionDraft(action_type="watermark_adjust", payload=wm,
                                             expected_gain=wm.get("customer_revenue_gain", 0.0)))

        return PolicyResult(
            expected_revenue_gain=revenue_gain,
            expected_peak_shaving_gain=revenue_gain,
            expected_off_peak_gain=0.0,
            constraints=constraints,
            actions=actions,
            diagnostics={
                "solver": self.name,
                "timeline_points": len(timeline),
                "candidate_count": len(candidates),
                "rejected": rejected,
                "machines_before": machines_before,
                "machines_after": machines_after,
                "model_self_capacity": model_self_capacity,
                "peak_feasibility": feasibility,
                "min_self_required": min_self_required,
                "fixed_profile_codes": sorted(fixed_codes),
                # 预警：三方侧亏损（售卖折扣<=采购折扣）的客户，供人工关注是否手动全挪自建
                "must_move_customers": [
                    {"report_id": c.demand.report_id, "customer_code": c.demand.customer_code,
                     "customer_name": c.demand.customer_name}
                    for c in candidates if c.must_move
                ],
            },
            summary={
                "accepted_customers": [self._accepted_row(c) for c in accepted],
                "node_moves": node_moves,
                "watermark_changes": watermark_changes,
                "self_revenue_before": before["self_revenue"],
                "self_revenue_after": after["self_revenue"],
                "expected_revenue_gain": revenue_gain,
                "self_tpm_integral_before": before["self_tpm_integral"],
                "self_tpm_integral_after": after["self_tpm_integral"],
                "machines_total_before": sum(machines_before.values()),
                "machines_total_after": sum(machines_after.values()),
                "machines_before": machines_before,
                "machines_after": machines_after,
                # 报告依赖（summary 才入库；diagnostics 不持久化）
                "peak_feasibility": feasibility,
                "model_rebalance": rebalance_diag,
            },
        )

    def _keep_net_positive_moves(self, candidates, clusters, timeline, moves, machines_before) -> list[dict]:
        """把 C 阶段产出的 moves 从「无腾挪」基线起逐条重放，只保留使全体自建收入积分净增的腾挪。

        C 阶段（_plan_reallocation）按每机器面积/机会成本贪心覆盖峰值缺口，缺口覆盖本身不保证整体
        自建收入上升——尤其关注集群内产能不足时，为承接某模型忙时峰值而拆走更高价值模型的机器会net亏。
        这里复用 D 阶段的水位积分口径，对每条腾挪做「整体净增>REV_EPS 才保留」的门槛（与 C2 一致），
        并就地把 clusters.machine_count 收敛到保留后的状态。"""
        if not moves:
            return moves
        by_name = {c["cluster_name"]: c for c in clusters}

        def apply(mv, sign):
            src, tgt = mv.get("from_cluster"), mv.get("to_cluster")
            n = int(mv.get("machine_count", 0) or 0) * sign
            if src in by_name:
                by_name[src]["machine_count"] = int(by_name[src].get("machine_count", 0) or 0) - n
            if tgt in by_name:
                by_name[tgt]["machine_count"] = int(by_name[tgt].get("machine_count", 0) or 0) + n

        def total_self_revenue():
            wm, _ = self._compute_watermarks(candidates, clusters, timeline)
            return self._integrate(candidates, wm, timeline, adjust=True)["self_revenue"]

        # 先整体回滚到无腾挪基线（machines_before），再逐条重放。
        for name, cnt in machines_before.items():
            if name in by_name:
                by_name[name]["machine_count"] = int(cnt or 0)
        cur_rev = total_self_revenue()
        kept: list[dict] = []
        for mv in moves:
            apply(mv, +1)
            new_rev = total_self_revenue()
            if new_rev - cur_rev > REV_EPS:
                kept.append(mv)
                cur_rev = new_rev
            else:
                apply(mv, -1)  # 非净增 → 回滚这条腾挪
        return kept

    @staticmethod
    def _aggregate_node_moves(moves: list[dict]) -> list[dict]:
        """按 (源集群, 目标集群, 模型) 聚合腾挪记录：台数/产能相加，合并成一条，供出更清爽的方案。"""
        agg: dict[tuple, dict] = {}
        order: list[tuple] = []
        for mv in moves:
            key = (mv.get("from_cluster"), mv.get("to_cluster"), mv.get("model"))
            a = agg.get(key)
            if a is None:
                a = agg[key] = {
                    "from_cluster": mv.get("from_cluster"),
                    "to_cluster": mv.get("to_cluster"),
                    "model": mv.get("model"),
                    "machine_count": 0,
                    "added_tpm": 0.0,
                    "removed_tpm": 0.0,
                    "from_tpm_per_machine": mv.get("from_tpm_per_machine"),
                    "to_tpm_per_machine": mv.get("to_tpm_per_machine"),
                    "gain": 0.0,
                    "merged_count": 0,
                }
                order.append(key)
            a["machine_count"] += int(mv.get("machine_count", 0) or 0)
            a["added_tpm"] += float(mv.get("added_tpm", 0.0) or 0.0)
            a["removed_tpm"] += float(mv.get("removed_tpm", 0.0) or 0.0)
            a["gain"] += float(mv.get("gain", 0.0) or 0.0)
            a["merged_count"] += 1
        result = []
        for key in order:
            a = agg[key]
            a["reason"] = (f"{a['from_cluster']} → {a['to_cluster']} 腾挪 {a['machine_count']} 台"
                           f"（{a['model']}，合并 {a['merged_count']} 次调整）")
            result.append(a)
        result.sort(key=lambda x: x["machine_count"], reverse=True)
        return result

    def _model_self_area(self, after: dict, demands: list, timeline: list[str]) -> dict[str, float]:
        """本次方案逐模型的自建「面积」= 该模型**所有在自建上跑量的客户**自建波形按时点叠加后、
        再乘每时段时长积分而成：面积 = Σ_t ( Σ_i 自建量_i(t) ) × 时长(t)  （单位 tokens/时段）。

        含两类客户，避免漏算占着产能的存量自建：
        - 进入水位优化的候选：取 after 里逐时规划自建量（slots.self_tpm）；
        - 未进候选的需求（已全自建被拒 already_fully_self_hosted、固定档位客户等）：按其
          current_self_ratio × 波形 计其既有自建量（这部分实打实占着集群产能）。
        """
        slot_minutes = self._slot_minutes(timeline)
        by_model_ts: dict[str, dict[str, float]] = {}
        covered: set[str] = set()
        for wm in after.get("watermarks", []):
            covered.add(wm.get("report_id"))
            m = str(wm.get("model", "")).lower()
            for sl in wm.get("slots", []):
                by_model_ts.setdefault(m, {}).setdefault(sl.get("ts"), 0.0)
                by_model_ts[m][sl.get("ts")] += float(sl.get("self_tpm", 0) or 0)
        # 未进水位优化、但当前有自建占比的需求：叠加其既有自建量（占着集群产能，必须计入利用率）
        for d in demands:
            if d.report_id in covered or d.current_self_ratio <= 0:
                continue
            m = (d.model_name or "").lower()
            for ts, tpm in self._series_of(d, timeline):
                by_model_ts.setdefault(m, {}).setdefault(ts, 0.0)
                by_model_ts[m][ts] += float(tpm) * d.current_self_ratio
        # 叠加后逐时点 × 时长 求和 = 承接面积
        return {m: sum(v * slot_minutes.get(ts, 60.0) for ts, v in ts_map.items())
                for m, ts_map in by_model_ts.items()}

    @staticmethod
    def _enrich_move_utilization(moves: list[dict], model_self_area: dict[str, float],
                                 total_minutes: float, clusters: list[dict],
                                 machines_before: dict[str, int],
                                 machines_after: dict[str, int]) -> None:
        """给每条腾挪记录补源/目标集群的腾挪前后利用率（面积口径）。

        利用率 = 该模型所有客户自建波形叠加出的**实际承接面积** / 该模型集群的**承载能力面积**，
        其中承载能力面积 = 该模型全部集群总容量(机器数 × 单机承载, tokens/分) × 时段总分钟。
        分别用腾挪前(machines_before)、腾挪后(machines_after)的机器数算承载面积。承载为 0 时记 0。
        """
        model_of = {c["cluster_name"]: str(c.get("deployed_model", "")).lower() for c in clusters}
        rate_of = {c["cluster_name"]: float(c.get("tpm_per_machine", 0) or 0) for c in clusters}
        clusters_of_model: dict[str, list[str]] = {}
        for c in clusters:
            clusters_of_model.setdefault(str(c.get("deployed_model", "")).lower(), []).append(c["cluster_name"])

        def util(cluster_name: str, machines_map: dict[str, int]) -> float:
            model = model_of.get(cluster_name)
            if model is None:
                return 0.0
            cap = sum(int(machines_map.get(n, 0) or 0) * rate_of.get(n, 0.0)
                      for n in clusters_of_model.get(model, []))
            cap_area = cap * total_minutes  # 承载能力面积 = 容量 × 时段总分钟
            if cap_area <= 0:
                return 0.0
            return model_self_area.get(model, 0.0) / cap_area

        for mv in moves:
            src = mv.get("from_cluster")
            dst = mv.get("to_cluster")
            mv["source_utilization_before"] = util(src, machines_before)
            mv["source_utilization_after"] = util(src, machines_after)
            mv["target_utilization_before"] = util(dst, machines_before)
            mv["target_utilization_after"] = util(dst, machines_after)

    # ---------------- A + B ----------------

    def _timeline(self, demands: list[DemandSnapshotItem]) -> list[str]:
        """所有客户序列并集的有序时间轴；若无序列则退化为单点。"""
        stamps: set[str] = set()
        for d in demands:
            for ts, _ in (d.tpm_series or []):
                stamps.add(ts)
        return sorted(stamps) if stamps else ["_flat_"]

    # ---------------- 峰值可行性（硬约束基准） ----------------
    def _peak_demand_by_model(self, demands: list[DemandSnapshotItem], timeline: list[str],
                              clusters: list[dict] | None = None) -> dict[str, float]:
        """逐模型：所有客户波形在同一时点求和后，取全时段峰值 = 该模型客户总需求峰值。

        专属集群绑定的客户需求不计入共享峰值（他们由自己的专属集群兜底，不与共享池混算）。"""
        dedicated_pairs = self._dedicated_owner_pairs(clusters or [])
        by_model_ts: dict[str, dict[str, float]] = {}
        for d in demands:
            if (d.customer_code, (d.model_name or "").lower()) in dedicated_pairs:
                continue
            for ts, tpm in self._series_of(d, timeline):
                by_model_ts.setdefault(d.model_name, {}).setdefault(ts, 0.0)
                by_model_ts[d.model_name][ts] += float(tpm)
        return {m: (max(v.values()) if v else 0.0) for m, v in by_model_ts.items()}

    @staticmethod
    def _dedicated_owner_pairs(clusters: list[dict]) -> set[tuple[str, str]]:
        """专属集群绑定的 (客户 code, 模型小写) 集合：这些需求归专属集群，不进共享池。"""
        pairs: set[tuple[str, str]] = set()
        for c in clusters:
            if c.get("dedicated") and c.get("dedicated_owner_code"):
                pairs.add((c["dedicated_owner_code"], str(c.get("deployed_model", "")).lower()))
        return pairs


    def _vendor_cap_by_model(self, vendors: list[dict]) -> dict[str, float]:
        cap: dict[str, float] = {}
        for v in vendors:
            cap[v.get("model")] = cap.get(v.get("model"), 0.0) + float(v.get("quota_tpm", 0) or 0)
        return cap

    def _self_cap_by_model(self, clusters: list[dict]) -> dict[str, float]:
        cap: dict[str, float] = {}
        for c in clusters:
            if c.get("dedicated"):
                continue  # 专属集群产能不并入共享模型池
            cap[c["deployed_model"]] = cap.get(c["deployed_model"], 0.0) + \
                float(c.get("machine_count", 0) or 0) * float(c.get("tpm_per_machine", 0) or 0)
        return cap


    def _check_peak_feasibility(self, clusters, peak_demand, vendor_cap) -> dict:
        """成案终检：逐模型 自建(调整后)+三方 是否覆盖客户波形峰值。slack<0 即按波形跑会掉量。"""
        self_cap = self._self_cap_by_model(clusters)
        out: dict[str, dict] = {}
        for m, pk in peak_demand.items():
            total = self_cap.get(m, 0.0) + vendor_cap.get(m, 0.0)
            out[m] = {
                "peak_demand": pk,
                "self_cap": self_cap.get(m, 0.0),
                "vendor_cap": vendor_cap.get(m, 0.0),
                "total_cap": total,
                "slack": total - pk,
                "feasible": total - pk >= -EPS,
            }
        return out

    def _peak_feasibility_constraint(self, feasibility: dict) -> ConstraintHit:
        worst = min((f["slack"] for f in feasibility.values()), default=0.0)
        bad = [m for m, f in feasibility.items() if not f["feasible"]]
        return ConstraintHit(
            name="model_peak_capacity_sufficient",
            hit=not bad,
            threshold=0.0,
            actual=worst,
            description="每模型(自建调整后+三方)需覆盖该模型客户波形峰值，否则按波形跑会掉量" +
                        ("" if not bad else f"；不满足: {bad}"),
        )

    def _series_of(self, demand: DemandSnapshotItem, timeline: list[str]) -> list[tuple[str, float]]:
        if demand.tpm_series:
            m = {ts: float(tpm) for ts, tpm in demand.tpm_series}
            return [(ts, m.get(ts, 0.0)) for ts in timeline]
        return [(ts, float(demand.expected_tpm)) for ts in timeline]  # 无序列 -> 平序列

    def _build_candidates(self, demands, vendors, model_prices, timeline):
        candidates: list[_Candidate] = []
        rejected: list[dict] = []
        for demand in demands:
            series = self._series_of(demand, timeline)
            peak = max((tpm for _, tpm in series), default=0.0)
            if peak <= 0:
                rejected.append(self._reject(demand, "non_positive_tpm"))
                continue
            vendor = self._best_vendor(demand, vendors)
            if vendor is None:
                rejected.append(self._reject(demand, "vendor_capacity_or_model_unavailable"))
                continue
            unit = self._unit_self_revenue(demand, model_prices, vendors)
            purchase_discount = self._purchase_discount(vendor)
            must_move = demand.discount_rate <= purchase_discount  # 售卖<=采购：留三方亏，必须全挪自建
            peak_vendor_gap = peak * max(1 - demand.current_self_ratio, 0)
            if peak_vendor_gap <= 0:
                rejected.append(self._reject(demand, "already_fully_self_hosted"))
                continue
            # 密度优先：单位自建收入为唯一排序键；must_move 仅作诊断预警，不再置顶，质量分不参与
            score = unit
            candidates.append(_Candidate(
                demand=demand, unit_self_revenue=unit, best_vendor=vendor,
                purchase_discount=purchase_discount, must_move=must_move,
                series=series, peak_tpm=peak, peak_vendor_gap=peak_vendor_gap, score=score,
            ))
        return candidates, rejected

    # ---------------- C. 机器重分配 ----------------
    def _model_capacity(self, clusters: list[dict]) -> dict[str, float]:
        cap: dict[str, float] = {}
        for c in clusters:
            cap[c["deployed_model"]] = cap.get(c["deployed_model"], 0.0) + \
                float(c.get("machine_count", 0) or 0) * float(c.get("tpm_per_machine", 0) or 0)
        return cap

    def _servable_clusters(self, demand: DemandSnapshotItem, clusters: list[dict]) -> list[dict]:
        return self._matching_clusters(demand.model_name, clusters, demand.customer_code)

    def _slot_minutes(self, timeline: list[str]) -> dict[str, float]:
        parsed: list[tuple[str, datetime]] = []
        for ts in timeline:
            try:
                parsed.append((ts, datetime.fromisoformat(str(ts))))
            except (TypeError, ValueError):
                continue
        if not parsed:
            return {ts: 60.0 for ts in timeline}

        parsed.sort(key=lambda item: item[1])
        durations: dict[str, float] = {}
        for idx, (ts, dt) in enumerate(parsed):
            if idx + 1 < len(parsed):
                minutes = (parsed[idx + 1][1] - dt).total_seconds() / 60.0
            elif idx > 0:
                minutes = (dt - parsed[idx - 1][1]).total_seconds() / 60.0
            else:
                minutes = 60.0
            durations[ts] = minutes if minutes > 0 else 60.0
        return {ts: durations.get(ts, 60.0) for ts in timeline}

    def _tpm_revenue(self, tpm: float, unit_revenue: float, minutes: float) -> float:
        return tpm * max(minutes, 0.0) / 1_000_000.0 * unit_revenue

    def _machine_area(self, cand, rate, timeline) -> float:

        """一台 `rate` 产能的机器全时段服务该客户能产出的自建收入积分。"""
        series = self._series_of(cand.demand, timeline)
        slot_minutes = self._slot_minutes(timeline)
        return sum(
            self._tpm_revenue(min(rate, max(tpm, 0.0)), cand.unit_self_revenue, slot_minutes.get(ts, 60.0))
            for ts, tpm in series
        )


    def _plan_reallocation(self, candidates, clusters, rejected, timeline, min_self_required):
        """机器一次重分配：仅当某模型**满容量**不足以覆盖其需求时，才从别处搬空闲机器过来。
        就地更新 clusters 的 machine_count；返回 (node_moves, accepted, rejected)。

        供出上限改用**峰值可行性口径**（取代 realtime 的 23:00 瞬时冗余 current_redundant_*）：
        - min_self_required[m] = max(0, 该模型客户波形峰值 − 三方额度)：三方接不住的峰值必须留自建；
        - model_slack[m] = 该模型当前自建容量 − min_self_required[m]：**唯一可供出**的自建容量。
          搬走机器就地递减源模型 slack、递增目标模型 slack，全程 slack≥0 → 任何模型都不会被搬到
          「按波形跑接不住峰值」的地步。这样：白天满载但深夜空闲的集群不再被误判为可供出。
        """
        by_name = {c["cluster_name"]: c for c in clusters}
        rate_of = {c["cluster_name"]: float(c.get("tpm_per_machine", 0) or 0) for c in clusters}
        model_of = {c["cluster_name"]: c["deployed_model"] for c in clusters}
        # reserved[c] = 已被前序客户预留的满容量（≤ 该簇满容量）。free 由 machine_count 实时算，
        # 恒 ≥0（不会像"直接扣 full_avail"那样在"先 reserve 后供出"时被扣成负）。
        reserved = {c["cluster_name"]: 0.0 for c in clusters}

        def cap_of(name):
            return float(by_name[name].get("machine_count", 0) or 0) * rate_of.get(name, 0.0)
        # 峰值可行性供出预算：每模型自建容量中，高于 min_self_required 的部分才可供出（物理护栏）。
        self_cap_model = self._self_cap_by_model(clusters)
        model_slack = {m: max(0.0, self_cap_model.get(m, 0.0) - min_self_required.get(m, 0.0))
                       for m in self_cap_model}
        # 每集群名义可供出台数 = 机器数 − 最小保留台数（KSCC 等）；专属集群机器锁定不外借；真正上限再由 model_slack 约束。
        donatable = {c["cluster_name"]: (0 if c.get("dedicated")
                                         else max(0, int(c.get("machine_count", 0) or 0) - self._min_reserve_machines(c)))
                     for c in clusters}

        # 每集群「可服务的全部候选」（机会成本用：一台机器留在源集群能承接哪些客户的面积）
        servable_by_cluster: dict[str, list] = {}
        for cand in candidates:
            for c in self._servable_clusters(cand.demand, clusters):
                servable_by_cluster.setdefault(c["cluster_name"], []).append(cand)
        node_moves: list[dict] = []
        accepted: list[_Candidate] = []

        def servable_free(servable):
            return sum(max(0.0, cap_of(c["cluster_name"]) - reserved.get(c["cluster_name"], 0.0))
                       for c in servable)

        for cand in candidates:
            demand = cand.demand
            servable = self._servable_clusters(demand, clusters)
            if not servable:
                rejected.append(self._reject(demand, "no_servable_cluster"))
                continue
            free = servable_free(servable)          # 满容量口径（machine_count×rate − 已reserve，≥0）
            need = cand.peak_vendor_gap             # 峰值处要回收的量

            if need - free > EPS:                   # 满容量真的不够才搬
                moves = self._acquire_machines(
                    cand, need - free, servable, clusters, donatable, model_slack, model_of,
                    servable_by_cluster, timeline,
                )
                for mv in moves:
                    src, tgt = mv["from_cluster"], mv["to_cluster"]
                    by_name[src]["machine_count"] -= mv["machine_count"]   # machine_count 就地更新→cap_of 实时反映
                    by_name[tgt]["machine_count"] += mv["machine_count"]
                    donatable[src] -= mv["machine_count"]
                    # 峰值可行性预算：源模型失去自建容量→slack 减；目标模型获得→slack 增。
                    model_slack[model_of[src]] = model_slack.get(model_of[src], 0.0) - mv["removed_tpm"]
                    model_slack[model_of[tgt]] = model_slack.get(model_of[tgt], 0.0) + mv["added_tpm"]
                    node_moves.append(mv)
                free = servable_free(servable)

            # 接纳只看“可服务集群**原始满容量** > 0”（不受 reserve 扣减影响）；真实自建量由 Step D
            # 面积注水决定（D 用满容量重算）。这样避免高峰客户在 C 阶段把低峰/常态客户饿死。
            servable_cap = sum(cap_of(c["cluster_name"]) for c in servable)
            if servable_cap <= EPS:
                rejected.append(self._reject(demand, "self_cluster_capacity_insufficient"))
                continue
            # 预留：把 min(need, free) 逐簇累加进 reserved（clamp 到各簇满容量），供后续客户 free 计算。
            self._reserve(servable, reserved, cap_of, min(need, free))
            accepted.append(cand)

        return node_moves, accepted, rejected

    def _acquire_machines(self, cand, shortfall_tpm, servable, clusters, donatable, model_slack, model_of,
                          servable_by_cluster, timeline) -> list[dict]:
        """为承接 `cand` 腾挪机器：目标取可服务集群里“加一台机器边际面积最高”者，源按**机会成本**
        （留在源集群一台机器能承接的最高面积）从低到高选，且**仅当目标增益 > 源机会成本**才搬——
        杜绝“把高产能机器搬到低产能目标只承接很小一段业务”的降面积挪动。

        供出上限受**峰值可行性预算** model_slack 约束（本次调用内用局部副本递减，防同模型多集群
        在一次调用里合计超额供出）：源模型自建容量必须始终 ≥ min_self_required（三方接不住的峰值）。
        禁止“同模型 rate 套利”搬运（同模型 + target_rate > src_rate）。"""
        demand = cand.demand
        targets = [c for c in servable if float(c.get("tpm_per_machine", 0) or 0) > 0]
        if not targets:
            return []
        # 目标：一台机器服务本客户面积最高的集群（速率越高、可承接面积越大）
        target = max(targets, key=lambda c: self._machine_area(cand, float(c.get("tpm_per_machine", 0) or 0), timeline))
        target_rate = float(target.get("tpm_per_machine", 0) or 0)
        target_gain = self._machine_area(cand, target_rate, timeline)  # 目标端每机器增益

        def opportunity(src) -> float:
            # 机会成本 = 这台机器留在源集群、服务源集群自己可服务客户的最高每机器面积（排除本客户）
            src_rate = float(src.get("tpm_per_machine", 0) or 0)
            best = 0.0
            for oc in servable_by_cluster.get(src["cluster_name"], []):
                if oc is cand:
                    continue
                best = max(best, self._machine_area(oc, src_rate, timeline))
            return best

        target_model = target.get("deployed_model")
        servable_names = {c["cluster_name"] for c in servable}
        sources = [c for c in clusters
                   if c["cluster_name"] not in servable_names   # 源必须在本客户**可服务集群之外**：
                   # 可服务集群本已计入 free，在其间搬对本客户是净零 churn；真正能补容量的只有
                   # 跨模型 / 专属不可达（primary≠本客户）的空闲机器。
                   and donatable.get(c["cluster_name"], 0) > 0
                   and float(c.get("tpm_per_machine", 0) or 0) > 0
                   # 禁止“同模型 rate 套利”：同模型内把低速率集群机器搬到高速率集群、按目标速率计产能，
                   # 会凭空抬高总容量（幻影）。同模型=同吞吐，rate 差是硬件差、不可随重部署转移。
                   # 保留：跨模型搬运；同模型降速率搬运（如专属集群→共享集群，把机器搬到客户能用处）。
                   and not (c.get("deployed_model") == target_model
                            and float(c.get("tpm_per_machine", 0) or 0) < target_rate - EPS)]
        # 机会成本从低到高：最“不值得留在源”的机器先搬
        sources.sort(key=opportunity)

        local_slack = dict(model_slack)   # 本次调用内递减，防同模型多集群合计超额供出
        moves: list[dict] = []
        added = 0.0
        for src in sources:
            if added >= shortfall_tpm:
                break
            # 仅当目标每机器增益 > 源机会成本才搬（相等/更低都不搬，杜绝无谓或降面积挪动）
            if target_gain - opportunity(src) <= EPS:


                break  # sources 已按机会成本升序，后续只会更贵，直接停
            name = src["cluster_name"]
            src_rate = float(src.get("tpm_per_machine", 0) or 0)
            # 安全护栏：可搬走台数受源模型峰值可行性预算限制——源模型自建须保留 min_self_required。
            movable = min(donatable.get(name, 0), int((local_slack.get(model_of[name], 0.0) + EPS) // src_rate))
            if movable <= 0:
                continue
            need_machines = max(1, ceil((shortfall_tpm - added) / target_rate))
            machines = min(movable, need_machines)
            if machines <= 0:
                continue
            moves.append({
                "from_cluster": name, "to_cluster": target["cluster_name"],
                "model": demand.model_name, "machine_count": machines,
                "added_tpm": machines * target_rate, "removed_tpm": machines * src_rate,
                "from_tpm_per_machine": src_rate, "to_tpm_per_machine": target_rate,
                "reason": f"承接优质客户 {demand.customer_code}（每机器面积 {target_gain:.0f} > 源机会成本）",
            })
            added += machines * target_rate
            local_slack[model_of[name]] = local_slack.get(model_of[name], 0.0) - machines * src_rate
        return moves

    def _reserve(self, servable, reserved, cap_of, amount):
        """把 `amount` 逐簇累加进 reserved（clamp 到各簇满容量 cap_of，不超订）。用于 Step C 规划口径：
        把当前客户的预期用量记入预留，使后续客户的 free = Σ max(0, cap − reserved) 相应变小。"""
        remaining = amount
        for c in servable:
            if remaining <= EPS:
                break
            name = c["cluster_name"]
            room = max(0.0, cap_of(name) - reserved.get(name, 0.0))
            take = min(remaining, room)
            reserved[name] = reserved.get(name, 0.0) + take
            remaining -= take

    # ---------------- C2. 模型级供需再平衡（跨模型抢机器） ----------------
    def _rebalance_by_model_gap(self, candidates, clusters, timeline, peak_demand, vendor_cap,
                                max_moves: int = 200) -> tuple[list[dict], dict]:
        """在 _plan_reallocation 之后，跨模型做「最陡上升单台贪心」腾挪，最大化全体自建收入积分。

        每步枚举所有 (源→目标) 单台腾挪，用 _compute_watermarks + _integrate 在新配置下重算总自建收入，
        取「净增最大且为正」的一台落地；直到无正收益或到 max_moves。约束（全部复用现有 helper）：
          ① 峰值可承接：_check_peak_feasibility 全模型 slack≥0（源模型不会被搬到接不住峰值）；
          ② 每步整体自建收入净增 > 0；
          ③ 一台机器只搬一次：集群不能既供出又接收（杜绝 A→B→C 两跳中转把同模型 rate 套利洗过来）；
          ④ 专属集群（KSCC/XISHANJU）只供不收，且保留最小台数；⑤ 禁同模型低→高 rate 套利。
        就地更新 cluster machine_count；返回 (node_moves, rebalance_diag)。
        """
        by_name = {c["cluster_name"]: c for c in clusters}
        rate_of = {c["cluster_name"]: float(c.get("tpm_per_machine", 0) or 0) for c in clusters}
        model_of = {c["cluster_name"]: c["deployed_model"] for c in clusters}
        names = [c["cluster_name"] for c in clusters]

        def donatable(name):
            if by_name[name].get("dedicated"):
                return 0  # 专属集群机器锁定，不参与跨模型腾挪
            return int(by_name[name].get("machine_count", 0) or 0) - self._min_reserve_machines(by_name[name])


        def total_self_revenue():
            wm, _ = self._compute_watermarks(candidates, clusters, timeline)
            return self._integrate(candidates, wm, timeline, adjust=True)["self_revenue"], wm

        def peak_ok():
            feas = self._check_peak_feasibility(clusters, peak_demand, vendor_cap)
            return all(f["feasible"] for f in feas.values())

        donated: set[str] = set()
        received: set[str] = set()

        def legal(src, tgt):
            if src == tgt or donatable(src) < 1:
                return False
            if by_name[tgt].get("dedicated"):
                return False  # 专属集群不接收外来机器
            if model_of[src] == model_of[tgt] and rate_of[src] < rate_of[tgt] - EPS:
                return False  # 禁同模型 rate 套利

            if src in received or tgt in donated:
                return False  # 反洗产能：一台机器只搬一次
            return True

        machines_start = {n: int(by_name[n].get("machine_count", 0) or 0) for n in names}
        base_rev, wm_base = total_self_revenue()
        moves: list[dict] = []
        while len(moves) < max_moves:
            cur_rev, _ = total_self_revenue()
            best = None
            for s in names:
                if donatable(s) < 1:
                    continue
                for t in names:
                    if not legal(s, t):
                        continue
                    by_name[s]["machine_count"] -= 1
                    by_name[t]["machine_count"] += 1
                    ok = peak_ok()
                    rev = total_self_revenue()[0] if ok else float("-inf")
                    by_name[s]["machine_count"] += 1
                    by_name[t]["machine_count"] -= 1
                    if ok and rev - cur_rev > REV_EPS and (best is None or rev > best[2]):
                        best = (s, t, rev)
            if best is None or best[2] - cur_rev <= REV_EPS:

                break
            s, t, rev = best
            by_name[s]["machine_count"] -= 1
            by_name[t]["machine_count"] += 1
            donated.add(s)
            received.add(t)
            moves.append({
                "from_cluster": s, "to_cluster": t, "model": model_of[t],
                "machine_count": 1, "added_tpm": rate_of[t], "removed_tpm": rate_of[s],
                "from_tpm_per_machine": rate_of[s], "to_tpm_per_machine": rate_of[t],
                "gain": rev - cur_rev,
                "reason": (f"模型级再平衡：{model_of[s]}(富余)→{model_of[t]}(紧缺) "
                           f"净增自建收入，承接紧缺模型客户"),
            })
        final_rev, wm_final = total_self_revenue()
        diag = self._rebalance_diag(candidates, clusters, moves, machines_start,
                                    wm_base, wm_final, base_rev, final_rev)
        return moves, diag

    def _rebalance_diag(self, candidates, clusters, moves, machines_start,
                        wm_base, wm_final, base_rev, final_rev) -> dict:
        """再平衡影响归因：逐客户水位线 base→final、逐模型 Σ水位线/共享容量 前后、逐集群角色与受益客户。"""
        rid2 = {c.demand.report_id: (c.demand.customer_code, c.demand.model_name) for c in candidates}
        cust_delta: list[dict] = []
        for rid in set(wm_base) | set(wm_final):
            code, mdl = rid2.get(rid, (None, None))
            if mdl is None:
                continue
            b, a = wm_base.get(rid, 0.0), wm_final.get(rid, 0.0)
            if abs(a - b) < 1.0:
                continue
            cust_delta.append({"customer_code": code, "model": mdl,
                               "watermark_before": b, "watermark_after": a, "delta": a - b})
        by_model_delta: dict[str, list] = {}
        for x in cust_delta:
            by_model_delta.setdefault(x["model"], []).append(x)
        for m in by_model_delta:
            by_model_delta[m].sort(key=lambda z: -z["delta"])

        def swm(wm):
            out: dict[str, float] = {}
            for c in candidates:
                out[c.demand.model_name] = out.get(c.demand.model_name, 0.0) + wm.get(c.demand.report_id, 0.0)
            return out

        def shared_cap(mc):
            out: dict[str, float] = {}
            for c in clusters:
                if not self._is_dedicated(c):
                    out[c["deployed_model"]] = out.get(c["deployed_model"], 0.0) + \
                        mc[c["cluster_name"]] * float(c.get("tpm_per_machine", 0) or 0)
            return out

        now_mc = {c["cluster_name"]: int(c.get("machine_count", 0) or 0) for c in clusters}
        swm_b, swm_a = swm(wm_base), swm(wm_final)
        shared_b, shared_a = shared_cap(machines_start), shared_cap(now_mc)
        per_model = [{"model": m, "swm_before": swm_b.get(m, 0.0), "swm_after": swm_a.get(m, 0.0),
                      "shared_cap_before": shared_b.get(m, 0.0), "shared_cap_after": shared_a.get(m, 0.0)}
                     for m in sorted(set(list(swm_b) + list(swm_a)))]
        per_cluster = []
        for c in sorted(clusters, key=lambda x: (x["deployed_model"], x["cluster_name"])):
            nm, mdl = c["cluster_name"], c["deployed_model"]
            mb, ma = machines_start[nm], now_mc[nm]
            dm = ma - mb
            role = "receive" if dm > 0 else ("donate" if dm < 0 else "none")
            gl = by_model_delta.get(mdl, [])
            per_cluster.append({
                "cluster_name": nm, "model": mdl, "rate": float(c.get("tpm_per_machine", 0) or 0),
                "dedicated": self._is_dedicated(c), "machines_before": mb, "machines_after": ma,
                "delta_machines": dm, "role": role,
                "gainers": [g for g in gl if g["delta"] > 0][:4] if role == "receive" else [],
                "losers": [g for g in gl if g["delta"] < 0][:3] if role == "donate" else [],
            })
        return {
            "moves": moves,
            "self_revenue_before": base_rev,
            "self_revenue_after": final_rev,
            "extra_revenue_gain": final_rev - base_rev,
            "per_model": per_model,
            "per_cluster": per_cluster,
            "customer_watermark_delta": cust_delta,
        }

    # ---------------- D. 固定水位线 + 时序积分 ----------------
    def _compute_watermarks(self, accepted, clusters, timeline) -> tuple[dict[str, float], list[_Candidate]]:
        """机器调整后「一次性」为每个客户设定固定的自建TPM上限（水位线）。此后不随时间变化。

        目标：最大化整段自建收入 Σ_t Σ_i min(需求_i(t), wm_i) × 密度_i，
        约束：Σ 抽取 ≤ 各集群满容量（经 _draw 施加，含专属集群约束）；wm_i ∈ [0, 自身峰值]。
        保证型不过订：Σwm ≤ Σcap。

        **削峰优先（无保底硬约束）**：当前自建量与待回收三方一视同仁，一律从 0 做纯边际收入注水——
        反复挑“抬高水位线的**边际收入**最大”的客户，把它的水位抬到下一个 breakpoint。
        边际收入 = 密度 × |{t: 需求(t) > 当前水位}|（= 密度 × 高于当前水位的时点数，密度已在其中）。
        尖峰（高、窄，时点少）边际收入低 → 被削到低水位；常态（矮、宽，时点多）边际收入高 → 优先注满。
        故**突刺形状的当前自建也会被削峰**（那部分挖回三方），把有限容量投到收入最高处。
        返回 (watermarks, kept)；kept = 实际拿到自建容量（wm>0）的客户，供 _integrate/汇总使用。
        """
        watermarks: dict[str, float] = {}
        kept: list[_Candidate] = []
        by_model: dict[str, list[_Candidate]] = {}
        for c in accepted:
            by_model.setdefault(c.demand.model_name, []).append(c)

        for model, custs in by_model.items():
            series = {c.demand.report_id: self._series_of(c.demand, timeline) for c in custs}
            cluster_cap = {
                cc["cluster_name"]: float(cc.get("machine_count", 0) or 0) * float(cc.get("tpm_per_machine", 0) or 0)
                for cc in clusters
            }
            level = {c.demand.report_id: 0.0 for c in custs}   # 一律从 0 起注水（无保底）
            peak = {c.demand.report_id: c.peak_tpm for c in custs}
            unit = {c.demand.report_id: c.unit_self_revenue for c in custs}
            demand_of = {c.demand.report_id: c.demand for c in custs}
            # 每客户候选水位断点（其序列里 distinct tpm 值，升序）——两断点间边际收入恒定
            breakpoints = {
                c.demand.report_id: sorted({tpm for _, tpm in series[c.demand.report_id]})
                for c in custs
            }
            capped: set[str] = set()  # 已封顶（到峰值）或所在集群已无容量的客户

            slot_minutes = self._slot_minutes(timeline)

            def time_above(rid, lv):
                return sum(slot_minutes.get(ts, 60.0) for ts, tpm in series[rid] if tpm > lv + EPS)

            def next_breakpoint(rid, lv):

                for bp in breakpoints[rid]:
                    if bp > lv + EPS:
                        return min(bp, peak[rid])
                return peak[rid]

            while True:
                best_rid, best_marginal = None, 0.0
                for c in custs:
                    rid = c.demand.report_id
                    if rid in capped or level[rid] >= peak[rid] - EPS:
                        continue
                    marginal = unit[rid] * time_above(rid, level[rid]) / 1_000_000.0

                    if marginal > best_marginal + REV_EPS:
                        best_marginal, best_rid = marginal, rid



                if best_rid is None:
                    break
                target_level = next_breakpoint(best_rid, level[best_rid])
                want = target_level - level[best_rid]
                got = self._draw(demand_of[best_rid], clusters, cluster_cap, want)
                level[best_rid] += got
                if got < want - EPS or level[best_rid] >= peak[best_rid] - EPS:
                    capped.add(best_rid)  # 容量抽尽或已到峰值，不再参与
            for c in custs:
                watermarks[c.demand.report_id] = level[c.demand.report_id]
                if level[c.demand.report_id] > EPS:   # 拿到自建容量的才计入 accepted
                    kept.append(c)
        return watermarks, kept

    def _before_self_revenue(self, considered, clusters, timeline, machines_before) -> dict:
        """现状自建收入基线，按「挪机器前」的关注集群产能逐时点封顶。

        现状自建量 = 现状自建占比 × 拟合波形；直接积分会超过集群物理产能（尤其忙时峰值），
        使 after 恒低于 before 出现假性亏损。这里用 machines_before 的产能、按 _draw（尊重
        _matching_clusters 的模型匹配与专属集群归属）逐时点为各客户现状自建量封顶后再积分。
        高单价客户优先占用产能。"""
        slot_minutes = self._slot_minutes(timeline)
        order = sorted(considered, key=lambda c: -c.unit_self_revenue)
        series_of = {c.demand.report_id: dict(self._series_of(c.demand, timeline)) for c in considered}
        rate_of = {cc["cluster_name"]: float(cc.get("tpm_per_machine", 0) or 0) for cc in clusters}
        total_rev = 0.0
        total_int = 0.0
        for ts in timeline:
            # 每时点重置为挪机器前的满产能（现状口径）
            cap_ts = {name: int(machines_before.get(name, 0) or 0) * rate_of.get(name, 0.0)
                      for name in rate_of}
            minutes = slot_minutes.get(ts, 60.0)
            for c in order:
                tpm_t = series_of[c.demand.report_id].get(ts, 0.0)
                desired = tpm_t * c.demand.current_self_ratio
                if desired <= 0:
                    continue
                got = self._draw(c.demand, clusters, cap_ts, desired)
                total_rev += self._tpm_revenue(got, c.unit_self_revenue, minutes)
                total_int += got * minutes
        return {"self_revenue": total_rev, "self_tpm_integral": total_int}

    def _integrate(self, accepted, watermarks, timeline, adjust: bool):
        """时序积分：水位线固定，逐时点 self(t)=min(需求(t), 水位线)；三方=需求−自建。
        分发占比随时间变化仅因客户跑量变化。adjust=False 用调整前的当前占比作对照基线。"""
        self_revenue = 0.0
        self_tpm_integral = 0.0
        slot_minutes = self._slot_minutes(timeline)
        wm_out: list[dict] = []
        for c in accepted:
            rid = c.demand.report_id

            unit = c.unit_self_revenue
            level = watermarks.get(rid, 0.0)           # 固定水位线（自建TPM上限）
            series = self._series_of(c.demand, timeline)
            slots = []
            cust_gain = 0.0
            for ts, tpm_t in series:
                if adjust:
                    self_t = min(tpm_t, level)          # ← 水位线固定，只有 tpm_t 变
                else:
                    self_t = tpm_t * c.demand.current_self_ratio   # 调整前：当前占比
                vendor_t = max(tpm_t - self_t, 0.0)
                minutes = slot_minutes.get(ts, 60.0)
                self_revenue += self._tpm_revenue(self_t, unit, minutes)
                self_tpm_integral += self_t * minutes

                if adjust:
                    ratio = (self_t / tpm_t) if tpm_t > 0 else 0.0
                    slots.append({
                        "ts": ts, "tpm": tpm_t, "self_ratio": round(ratio, 4),
                        "self_tpm": self_t, "vendor_tpm": vendor_t,
                        "vendor_ratios": {(c.best_vendor or {}).get("vendor", "vendor"): round(1 - ratio, 4)},
                    })
                    before_self_t = tpm_t * c.demand.current_self_ratio
                    cust_gain += self._tpm_revenue(self_t - before_self_t, unit, minutes)

            if adjust and (level > EPS or c.demand.current_self_ratio > EPS):
                # 只对"有自建 or 曾有自建"的客户产出水位变更；wm=0 且从未自建的纯空转客户跳过。
                wm_out.append({
                    "report_id": rid, "customer_code": c.demand.customer_code,
                    "customer_name": c.demand.customer_name,
                    "model": c.demand.model_name, "current_self_ratio": c.demand.current_self_ratio,
                    "watermark_self_tpm": level,        # 固定水位线（本次调整一次性设定）
                    "unit_self_revenue": unit,          # 自建单价(元/百万token)——求解器承接排序键，供报告体现优先级
                    "fallback_vendor": (c.best_vendor or {}).get("vendor"),
                    "slots": slots, "customer_revenue_gain": cust_gain,
                })
        return {
            "self_revenue": self_revenue,
            "self_tpm_integral": self_tpm_integral,
            "watermarks": wm_out,
            "peak_overflow_ok": True,
        }

    def _draw(self, demand, clusters, cluster_cap, want_tpm) -> float:
        """从 demand 的可服务集群（受专属约束）按序抽取容量，返回实际抽到量，就地扣减 cluster_cap。"""
        got = 0.0
        remaining = want_tpm
        for c in self._matching_clusters(demand.model_name, clusters, demand.customer_code):
            if remaining <= 0:
                break
            name = c["cluster_name"]
            avail = cluster_cap.get(name, 0.0)
            if avail <= 0:
                continue
            take = min(remaining, avail)
            cluster_cap[name] = avail - take
            got += take
            remaining -= take
        return got

    # ---------------- E. 约束 ----------------
    def _build_constraints(self, candidates, accepted, rejected, revenue_gain, after,
                           node_moves, machines_before, machines_after) -> list[ConstraintHit]:
        reasons = {r["reason"] for r in rejected}
        # 峰值覆盖：每个被接客户，其可服务集群容量应 >= 其峰值自建目标（此处已按峰值定容）
        peak_ok = "self_cluster_capacity_insufficient" not in reasons
        machines_conserved = sum(machines_before.values()) == sum(machines_after.values())
        return [
            ConstraintHit(
                name="peak_capacity_sufficient", hit=peak_ok, threshold=0.0,
                actual=float(len(accepted)),
                description="机器调整后自建+三方需能覆盖峰值需求（自建按峰值定容）",
            ),
            ConstraintHit(
                name="vendor_margin_positive",
                hit=bool(candidates),
                threshold=0.0,
                actual=min((c.demand.discount_rate - c.purchase_discount for c in candidates), default=0.0),
                description="三方承接部分：售卖折扣需高于采购折扣",
            ),
            ConstraintHit(
                name="high_value_moved_to_self", hit=len(accepted) > 0,
                threshold=0.0, actual=float(len(accepted)),
                description="三方上有量的优质客户已挪到自建承接",
            ),
            ConstraintHit(
                name="machines_conserved", hit=machines_conserved, threshold=None,
                actual=float(sum(machines_after.values())),
                description="机器总量守恒（仅在集群间重分配，不新增）",
            ),
            ConstraintHit(
                name="positive_revenue_gain", hit=revenue_gain > 0, threshold=0.0,
                actual=revenue_gain,
                description="一次机器调整后整段收入积分需高于调整前",
            ),
        ]

    def _accepted_row(self, c: _Candidate) -> dict:
        return {
            "report_id": c.demand.report_id, "customer_code": c.demand.customer_code,
            "customer_name": c.demand.customer_name,
            "model": c.demand.model_name, "unit_self_revenue": c.unit_self_revenue,
            "peak_tpm": c.peak_tpm, "peak_vendor_gap": c.peak_vendor_gap,
            "must_move": c.must_move, "fallback_vendor": (c.best_vendor or {}).get("vendor"),
            "score": c.score,
        }
