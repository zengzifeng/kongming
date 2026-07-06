from __future__ import annotations

from dataclasses import dataclass
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

        # ---- A. 客户经济学（时间不变量）+ B. 需求时序剖面 ----
        candidates, rejected = self._build_candidates(snapshot.demands, vendors, model_prices, timeline)
        candidates.sort(key=lambda c: c.score, reverse=True)

        # ---- C. 一次机器重分配：按峰值把选中客户所需自建容量配齐 ----
        machines_before = {c["cluster_name"]: int(c.get("machine_count", 0) or 0) for c in clusters}
        node_moves, accepted, rejected = self._plan_reallocation(candidates, clusters, rejected)
        machines_after = {c["cluster_name"]: int(c.get("machine_count", 0) or 0) for c in clusters}

        # 每模型调整后的自建容量（machine_count 已被 _plan_reallocation 就地更新）
        model_self_capacity = self._model_capacity(clusters)

        # ---- D. 固定水位线：机器调整后「一次性」设定每个客户的自建TPM上限（水位线），此后不随时间变化。 ----
        watermarks = self._compute_watermarks(accepted, clusters, timeline)

        # ---- 时序积分：水位线固定，仅客户跑量随时间变化 -> 自建/三方分发占比随之变化 ----
        after = self._integrate(accepted, watermarks, timeline, adjust=True)
        before = self._integrate(accepted, watermarks, timeline, adjust=False)
        revenue_gain = after["self_revenue"] - before["self_revenue"]

        # ---- E. 约束体检 ----
        constraints = self._build_constraints(
            candidates, accepted, rejected, revenue_gain, after, node_moves,
            machines_before, machines_after,
        )

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
            },
        )

    # ---------------- A + B ----------------
    def _timeline(self, demands: list[DemandSnapshotItem]) -> list[str]:
        """所有客户序列并集的有序时间轴；若无序列则退化为单点。"""
        stamps: set[str] = set()
        for d in demands:
            for ts, _ in (d.tpm_series or []):
                stamps.add(ts)
        return sorted(stamps) if stamps else ["_flat_"]

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
            # 密度优先（M1）：单位自建收入为主键；must_move 置顶
            score = (1e9 if must_move else 0.0) + unit * 1e6 + max(demand.quality_score, 0) * 0.01
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

    def _cluster_committed(self, clusters: list[dict]) -> dict[str, float]:
        """每集群当前已被本集群主要客户占用的自建量（用于判断可释放余量）。
        近似：用 current_redundant_tpm 表示空闲，committed = 容量 - 冗余。"""
        committed = {}
        for c in clusters:
            cap = float(c.get("machine_count", 0) or 0) * float(c.get("tpm_per_machine", 0) or 0)
            redundant = max(float(c.get("current_redundant_tpm", 0) or 0), 0.0)
            committed[c["cluster_name"]] = max(cap - redundant, 0.0)
        return committed

    def _plan_reallocation(self, candidates, clusters, rejected):
        """按峰值给高密度客户配齐自建容量；不足则在集群间腾挪机器（总量守恒）。
        就地更新 clusters 的 machine_count；返回 (node_moves, accepted, rejected)。"""
        by_name = {c["cluster_name"]: c for c in clusters}
        committed = self._cluster_committed(clusters)
        # 每集群可供出机器数（空闲机器，受最小保留约束）
        donatable = {c["cluster_name"]: self._donatable_machines(c) for c in clusters}
        donors_used: set[str] = set()
        receivers_used: set[str] = set()
        node_moves: list[dict] = []
        accepted: list[_Candidate] = []

        for cand in candidates:
            demand = cand.demand
            servable = self._servable_clusters(demand, clusters)
            if not servable:
                rejected.append(self._reject(demand, "no_servable_cluster"))
                continue
            # 该客户在其可服务集群上的当前空闲容量
            free = sum(max(float(c.get("machine_count", 0) or 0) * float(c.get("tpm_per_machine", 0) or 0)
                           - committed.get(c["cluster_name"], 0.0), 0.0) for c in servable)
            need = cand.peak_vendor_gap  # 峰值处要回收的量

            if free < need:
                moves = self._acquire_machines(
                    demand, need - free, servable, clusters, by_name,
                    donatable, donors_used, receivers_used,
                )
                for mv in moves:
                    src, tgt = mv["from_cluster"], mv["to_cluster"]
                    by_name[src]["machine_count"] -= mv["machine_count"]
                    by_name[tgt]["machine_count"] += mv["machine_count"]
                    donatable[src] -= mv["machine_count"]
                    donors_used.add(src)
                    receivers_used.add(tgt)
                    committed[src] = committed.get(src, 0.0)  # 源已提交量不变（挪的是空闲机器）
                    free += mv["added_tpm"]
                    node_moves.append(mv)

            take = min(need, free)
            if take <= 0:
                rejected.append(self._reject(demand, "self_cluster_capacity_insufficient"))
                continue
            # 记账：把 take 计入该客户可服务集群的 committed（优先填满已有集群）
            self._commit(servable, committed, take)
            accepted.append(cand)

        return node_moves, accepted, rejected

    def _acquire_machines(self, demand, shortfall_tpm, servable, clusters, by_name,
                          donatable, donors_used, receivers_used) -> list[dict]:
        """为承接 demand 腾挪机器到其可服务集群中单机能力最高者。目标速率计产能，源速率释放。"""
        targets = [c for c in servable if c["cluster_name"] not in donors_used
                   and float(c.get("tpm_per_machine", 0) or 0) > 0]
        if not targets:
            return []
        target = max(targets, key=lambda c: float(c.get("tpm_per_machine", 0) or 0))
        target_rate = float(target.get("tpm_per_machine", 0) or 0)
        sources = [c for c in clusters
                   if c["cluster_name"] != target["cluster_name"]
                   and c["cluster_name"] not in receivers_used
                   and donatable.get(c["cluster_name"], 0) > 0
                   and float(c.get("tpm_per_machine", 0) or 0) > 0]
        sources.sort(key=lambda c: donatable.get(c["cluster_name"], 0), reverse=True)

        moves: list[dict] = []
        added = 0.0
        for src in sources:
            if added >= shortfall_tpm:
                break
            name = src["cluster_name"]
            src_rate = float(src.get("tpm_per_machine", 0) or 0)
            movable = donatable.get(name, 0)
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
                "reason": f"承接优质客户 {demand.customer_code}（峰值定容）",
            })
            added += machines * target_rate
        return moves

    def _commit(self, servable, committed, amount):
        remaining = amount
        for c in servable:
            if remaining <= 0:
                break
            name = c["cluster_name"]
            cap = float(c.get("machine_count", 0) or 0) * float(c.get("tpm_per_machine", 0) or 0)
            free = max(cap - committed.get(name, 0.0), 0.0)
            put = min(free, remaining)
            committed[name] = committed.get(name, 0.0) + put
            remaining -= put

    # ---------------- D. 固定水位线 + 时序积分 ----------------
    def _compute_watermarks(self, accepted, clusters, timeline) -> dict[str, float]:
        """机器调整后「一次性」为每个客户设定固定的自建TPM上限（水位线）。此后不随时间变化。

        分配口径：在各模型系统峰值时点，先按【当前自建量】保底（不把已在自建的流量赶去三方），
        再把剩余自建容量按【收入密度】优先分给待回收的三方流量，各客户封顶到其峰值需求。
        受专属集群约束（KSCC/XISHANJU 只服务对应客户）与集群级容量约束。
        """
        watermarks: dict[str, float] = {}
        by_model: dict[str, list[_Candidate]] = {}
        for c in accepted:
            by_model.setdefault(c.demand.model_name, []).append(c)

        for model, custs in by_model.items():
            custs = sorted(custs, key=lambda c: c.unit_self_revenue, reverse=True)
            series = {c.demand.report_id: self._series_of(c.demand, timeline) for c in custs}
            # 系统峰值时点：该模型全部客户合计需求最大的时刻（水位线按此刻的容量竞争一次性定死）
            agg = [sum(series[c.demand.report_id][ti][1] for c in custs) for ti in range(len(timeline))]
            pk = max(range(len(timeline)), key=lambda ti: agg[ti]) if timeline else 0
            cluster_cap = {
                cc["cluster_name"]: float(cc.get("machine_count", 0) or 0) * float(cc.get("tpm_per_machine", 0) or 0)
                for cc in clusters
            }
            # 第一轮：按当前自建量保底（顺序无关，各客户从自己可服务集群抽取）
            base = {}
            for c in custs:
                rid = c.demand.report_id
                d_pk = series[rid][pk][1]
                cur_self = d_pk * c.demand.current_self_ratio
                base[rid] = self._draw(c.demand, clusters, cluster_cap, cur_self)
            # 第二轮：剩余容量按密度优先回收三方流量，封顶到峰值需求
            for c in custs:
                rid = c.demand.report_id
                d_pk = series[rid][pk][1]
                extra = self._draw(c.demand, clusters, cluster_cap, max(d_pk - base[rid], 0.0))
                watermarks[rid] = base[rid] + extra
        return watermarks

    def _integrate(self, accepted, watermarks, timeline, adjust: bool):
        """时序积分：水位线固定，逐时点 self(t)=min(需求(t), 水位线)；三方=需求−自建。
        分发占比随时间变化仅因客户跑量变化。adjust=False 用调整前的当前占比作对照基线。"""
        self_revenue = 0.0
        self_tpm_integral = 0.0
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
                self_revenue += self_t * unit
                self_tpm_integral += self_t
                if adjust:
                    ratio = (self_t / tpm_t) if tpm_t > 0 else 0.0
                    slots.append({
                        "ts": ts, "tpm": tpm_t, "self_ratio": round(ratio, 4),
                        "self_tpm": self_t, "vendor_tpm": vendor_t,
                        "vendor_ratios": {(c.best_vendor or {}).get("vendor", "vendor"): round(1 - ratio, 4)},
                    })
                    cust_gain += (self_t - tpm_t * c.demand.current_self_ratio) * unit
            if adjust:
                wm_out.append({
                    "report_id": rid, "customer_code": c.demand.customer_code,
                    "model": c.demand.model_name, "current_self_ratio": c.demand.current_self_ratio,
                    "watermark_self_tpm": level,        # 固定水位线（本次调整一次性设定）
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
            "model": c.demand.model_name, "unit_self_revenue": c.unit_self_revenue,
            "peak_tpm": c.peak_tpm, "peak_vendor_gap": c.peak_vendor_gap,
            "must_move": c.must_move, "fallback_vendor": (c.best_vendor or {}).get("vendor"),
            "score": c.score,
        }
