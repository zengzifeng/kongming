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

# 浮点护栏：容量求和会有残差，用它判断“缺口是否已实质填满 / 是否还有可分配容量”。
EPS = 1e-6


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

        # 峰值可行性硬约束基准：逐模型客户波形总需求峰值 / 三方额度 / 需保留的最小自建容量。
        # min_self_required = max(0, 峰值 − 三方额度)：三方接不住的那部分峰值必须由自建兜底，
        # 是「机器最多能挪走到什么程度」的物理下限（削峰可把峰值外抛给三方，但外抛不掉的必须留自建）。
        peak_demand = self._peak_demand_by_model(snapshot.demands, timeline)
        vendor_cap = self._vendor_cap_by_model(vendors)
        min_self_required = {m: max(0.0, peak_demand.get(m, 0.0) - vendor_cap.get(m, 0.0))
                             for m in peak_demand}

        # ---- A. 客户经济学（时间不变量）+ B. 需求时序剖面 ----
        candidates, rejected = self._build_candidates(snapshot.demands, vendors, model_prices, timeline)
        candidates.sort(key=lambda c: c.score, reverse=True)

        # ---- C. 一次机器重分配：按“每机器边际收入面积”配齐（机会成本加权，不只按峰值台数）----
        machines_before = {c["cluster_name"]: int(c.get("machine_count", 0) or 0) for c in clusters}
        node_moves, accepted, rejected = self._plan_reallocation(
            candidates, clusters, rejected, timeline, min_self_required)
        machines_after = {c["cluster_name"]: int(c.get("machine_count", 0) or 0) for c in clusters}

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
        before = self._integrate(considered, watermarks, timeline, adjust=False)
        revenue_gain = after["self_revenue"] - before["self_revenue"]
        accepted = kept                  # 汇总/约束里的 accepted 只列真正拿到自建的客户

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
                # 预警：三方侧亏损（售卖折扣<=采购折扣）的客户，供人工关注是否手动全挪自建
                "must_move_customers": [
                    {"report_id": c.demand.report_id, "customer_code": c.demand.customer_code}
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

    # ---------------- 峰值可行性（硬约束基准） ----------------
    def _peak_demand_by_model(self, demands: list[DemandSnapshotItem], timeline: list[str]) -> dict[str, float]:
        """逐模型：所有客户波形在同一时点求和后，取全时段峰值 = 该模型客户总需求峰值。"""
        by_model_ts: dict[str, dict[str, float]] = {}
        for d in demands:
            for ts, tpm in self._series_of(d, timeline):
                by_model_ts.setdefault(d.model_name, {}).setdefault(ts, 0.0)
                by_model_ts[d.model_name][ts] += float(tpm)
        return {m: (max(v.values()) if v else 0.0) for m, v in by_model_ts.items()}

    def _vendor_cap_by_model(self, vendors: list[dict]) -> dict[str, float]:
        cap: dict[str, float] = {}
        for v in vendors:
            cap[v.get("model")] = cap.get(v.get("model"), 0.0) + float(v.get("quota_tpm", 0) or 0)
        return cap

    def _self_cap_by_model(self, clusters: list[dict]) -> dict[str, float]:
        cap: dict[str, float] = {}
        for c in clusters:
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

    def _machine_area(self, cand, rate, timeline) -> float:
        """一台 `rate` 产能的机器全时段服务该客户能产出的自建收入「面积」（gross，covered=0）：
        density × Σ_t min(rate, 需求(t))。用于按“每机器面积”比较机会成本，而非按空闲台数或每 TPM 密度。
        —— 速率不同的集群间，一台机器的价值 = 速率 × 密度 × 有效时点数，这里直接积分出来。"""
        series = self._series_of(cand.demand, timeline)
        return cand.unit_self_revenue * sum(min(rate, max(tpm, 0.0)) for _, tpm in series)

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
        # 每集群名义可供出台数 = 机器数 − 最小保留台数（KSCC 等）；真正上限再由 model_slack 约束。
        donatable = {c["cluster_name"]: max(0, int(c.get("machine_count", 0) or 0) - self._min_reserve_machines(c))
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

            def time_above(rid, lv):
                return sum(1 for _, tpm in series[rid] if tpm > lv + EPS)

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
                    marginal = unit[rid] * time_above(rid, level[rid])  # 边际收入 = 密度 × 时点数
                    if marginal > best_marginal + EPS:
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
            if adjust and (level > EPS or c.demand.current_self_ratio > EPS):
                # 只对"有自建 or 曾有自建"的客户产出水位变更；wm=0 且从未自建的纯空转客户跳过。
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
