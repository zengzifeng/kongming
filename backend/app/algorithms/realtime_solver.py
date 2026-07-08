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

# 浮点护栏：多集群冗余求和会有 ~1e-9 残差，用它判断“缺口是否已实质填满”，
# 避免为几乎为 0 的残缺口触发一次“至少搬一整台机器”的无谓腾挪。
EPS = 1e-6


@dataclass
class _Candidate:
    demand: DemandSnapshotItem
    unit_self_revenue: float
    best_vendor: dict
    vendor_purchase_discount: float
    vendor_margin_per_tpm: float
    score: float
    vendor_gap_tpm: float  # 当前走三方、可回收到自建的流量 = expected_tpm * (1 - current_self_ratio)
    target_tpm_per_machine: float = 0.0  # 该需求腾挪目标集群的单台承载能力（排序时用作单台产能权重）
    must_move: bool = False  # 售卖折扣 <= 采购折扣：留在三方是亏的，必须优先全挪自建


class RealtimeSolver(SolverEconomicsMixin):
    """分钟级实时调度：在自建容量与三方兜底约束下最大化自建承接收益。"""

    name = "realtime"

    def solve(self, snapshot: PolicyInputSnapshot) -> PolicyResult:
        if not snapshot.demands:
            raise AlgorithmError("快照中无可处理需求", code="ALGORITHM_FAILED")
        if not snapshot.resources or not snapshot.vendors:
            raise AlgorithmError("快照缺少资源或三方供应数据", code="ALGORITHM_FAILED")

        clusters = [dict(c) for c in snapshot.resources.get("clusters", [])]
        if not clusters:
            raise AlgorithmError("快照缺少自建集群数据", code="ALGORITHM_FAILED")

        model_prices = snapshot.params.get("model_prices", {})
        vendor_remaining = {
            self._vendor_key(v): float(v.get("quota_tpm", 0) or 0)
            for v in snapshot.vendors
        }
        # 冗余分账：native_idle = 集群“原生”空闲 TPM（可被分配消耗，也可背书供出机器）；
        # received_idle = 腾挪“接收”到的机器带来的 TPM（只能被分配消耗，永不背书供出）。
        # 这样杜绝“原生冗余被分配吃空后、又靠接收余量供出已占用的原生机器”的容量重复占用，
        # 从而可以安全允许一个集群既供出又接收（A→B & C→A），无需集群级“禁止倒手”互斥。
        native_idle = {
            c["cluster_name"]: float(c.get("current_redundant_tpm", 0) or 0)
            for c in clusters
        }
        received_idle = {c["cluster_name"]: 0.0 for c in clusters}
        cluster_extra_machines = {
            c["cluster_name"]: self._donatable_machines(c)
            for c in clusters
        }

        candidates, rejected = self._build_candidates(snapshot.demands, snapshot.vendors, model_prices, clusters)
        candidates.sort(key=lambda c: c.score, reverse=True)

        actions: list[PolicyActionDraft] = []
        accepted_customers: list[dict] = []
        watermark_changes: list[dict] = []
        node_moves: list[dict] = []
        total_self_tpm = 0.0
        expected_self_revenue = 0.0
        expected_vendor_cost = 0.0

        # 统一单趟（密度序）：每个候选在自己这一轮内依次完成
        #   ① 用现有冗余分配 → ② 不足则跨集群腾挪机器再分配 → ③ 按总分配量记一次账。
        # 这样高密度客户即使第一步只吃到部分冗余，也会立刻用腾挪补齐（修复“部分承接不回炉”）；
        # 且高密度客户先于低密度客户占用/腾挪同一集群容量（修复“密度倒挂”）。
        for candidate in candidates:
            need = candidate.vendor_gap_tpm
            allocated = self._allocate_to_existing_cluster(candidate, clusters, native_idle, received_idle, need)

            node_move_attempted = False
            if need - allocated > EPS:
                remaining = need - allocated
                moves = self._plan_node_move(candidate, clusters, cluster_extra_machines, native_idle, remaining)
                if moves:
                    node_move_attempted = True
                    # 修复 P8：一个客户可由多次腾挪共同承接
                    for move in moves:
                        src = move["from_cluster"]
                        cluster_extra_machines[src] -= move["machine_count"]
                        # P9：源集群失去这些机器的“原生”闲置产能（按源单机能力）
                        native_idle[src] = native_idle.get(src, 0.0) - move["removed_tpm"]
                        # P1：目标集群新增产能按目标单机能力计入，且只进“接收池”——不可再被供出
                        received_idle[move["to_cluster"]] = received_idle.get(move["to_cluster"], 0.0) + move["added_tpm"]
                        node_moves.append(move)
                        actions.append(PolicyActionDraft(
                            action_type="node_move",
                            payload=move,
                            expected_gain=0.0,
                        ))
                    allocated += self._allocate_to_existing_cluster(candidate, clusters, native_idle, received_idle, remaining)

            if allocated <= 0:
                rejected.append({
                    "report_id": candidate.demand.report_id,
                    "customer_code": candidate.demand.customer_code,
                    "reason": "self_cluster_capacity_insufficient_after_node_move" if node_move_attempted
                    else "self_cluster_capacity_insufficient",
                })
                continue

            accepted = self._record_customer_actions(
                candidate,
                allocated,
                vendor_remaining,
                actions,
                accepted_customers,
                watermark_changes,
            )
            total_self_tpm += accepted["self_tpm"]
            expected_self_revenue += accepted["self_revenue"]
            expected_vendor_cost += accepted["vendor_cost"]

        # 分配后各集群剩余可分配 TPM = 原生剩余 + 接收剩余（供诊断/约束汇总）
        cluster_remaining = {
            name: native_idle.get(name, 0.0) + received_idle.get(name, 0.0)
            for name in native_idle
        }
        expected_revenue_gain = expected_self_revenue - expected_vendor_cost
        constraints = self._build_constraints(
            candidates=candidates,
            rejected=rejected,
            expected_revenue_gain=expected_revenue_gain,
            cluster_remaining=cluster_remaining,
            vendor_remaining=vendor_remaining,
            node_moves=node_moves,
        )

        return PolicyResult(
            expected_revenue_gain=expected_revenue_gain,
            expected_peak_shaving_gain=expected_revenue_gain,
            expected_off_peak_gain=0.0,
            constraints=constraints,
            actions=actions,
            diagnostics={
                "solver": self.name,
                "candidate_count": len(candidates),
                "rejected": rejected,
                "cluster_remaining_tpm": cluster_remaining,
                "vendor_remaining_tpm": vendor_remaining,
                # 预警：三方侧亏损（售卖折扣<=采购折扣）的客户，供人工关注是否手动全挪自建
                "must_move_customers": [
                    {"report_id": c.demand.report_id, "customer_code": c.demand.customer_code}
                    for c in candidates if c.must_move
                ],
            },
            summary={
                "accepted_customers": accepted_customers,
                "total_self_tpm_added": total_self_tpm,
                "expected_self_revenue": expected_self_revenue,
                "expected_vendor_cost": expected_vendor_cost,
                "expected_revenue_gain": expected_revenue_gain,
                "node_moves": node_moves,
                "watermark_changes": watermark_changes,
            },
        )

    def _build_candidates(
        self,
        demands: list[DemandSnapshotItem],
        vendors: list[dict],
        model_prices: dict,
        clusters: list[dict],
    ) -> tuple[list[_Candidate], list[dict]]:
        candidates: list[_Candidate] = []
        rejected: list[dict] = []
        for demand in demands:
            if demand.expected_tpm <= 0:
                rejected.append(self._reject(demand, "non_positive_tpm"))
                continue

            unit_self_revenue = self._unit_self_revenue(demand, model_prices, vendors)
            vendor = self._best_vendor(demand, vendors)
            if vendor is None:
                rejected.append(self._reject(demand, "vendor_capacity_or_model_unavailable"))
                continue

            purchase_discount = self._purchase_discount(vendor)
            vendor_cost = float(vendor.get("unit_cost", 0) or 0)
            vendor_margin = unit_self_revenue - vendor_cost
            # 修复 M3：不再因“三方不赚钱”而拒收——自建边际成本≈0，越是在三方亏的客户越该挪到自建。
            # 售卖折扣 <= 采购折扣，意味着留在三方那部分是亏的，标记为“必须优先全挪自建”。
            must_move = demand.discount_rate <= purchase_discount

            current_vendor_tpm = demand.expected_tpm * max(1 - demand.current_self_ratio, 0)
            # 修复 P4：已全部自建的客户没有可回收流量，直接跳过，不占用冗余、不虚增收益
            if current_vendor_tpm <= 0:
                rejected.append(self._reject(demand, "already_fully_self_hosted"))
                continue
            # 排序键 = 单位TPM自建收入密度 × 目标集群单台承载能力 = 该需求“每台机器”的自建收入。
            #
            # 为什么不是纯密度：跨模型客户争夺的稀缺资源是【整台可腾挪机器】（不可分割），一台机器
            # 搬到目标集群后按【目标单台产能】产出 TPM。若只按密度排序，可能把机器给了“密度高但目标
            # 集群单台产能很低”的客户（承载很少 TPM），而挤掉“密度略低但单台产能极高”的客户——后者
            # 单台自建收入反而更高。故乘上 target_tpm_per_machine 修正为“单台收益”口径。
            #
            # 口径自洽性：同模型（且同目标）客户 target 相同，乘常数不改变其相对序，冗余池（按模型
            # 隔离、不跨模型争用）的分数背包最优性不受影响；差异只体现在跨模型的整机争夺上，正是要修的点。
            # must_move（售卖折扣<=采购折扣、三方侧亏损）不参与排序，仅作诊断预警。
            target_rate = self._target_rate(demand, clusters)
            score = unit_self_revenue * target_rate if target_rate > 0 else unit_self_revenue
            candidates.append(_Candidate(
                demand=demand,
                unit_self_revenue=unit_self_revenue,
                best_vendor=vendor,
                vendor_purchase_discount=purchase_discount,
                vendor_margin_per_tpm=vendor_margin,
                score=score,
                vendor_gap_tpm=current_vendor_tpm,
                target_tpm_per_machine=target_rate,
                must_move=must_move,
            ))
        return candidates, rejected

    def _target_rate(self, demand: DemandSnapshotItem, clusters: list[dict]) -> float:
        # 该需求可承接集群里单台承载能力最高者（与 _plan_node_move 选目标同口径）。
        # 无匹配集群时返回 0——该需求本就无法自建承接，最终会被拒收，排序位置不影响结果。
        matching = self._matching_clusters(demand.model_name, clusters, demand.customer_code)
        if not matching:
            return 0.0
        return max(float(c.get("tpm_per_machine", 0) or 0) for c in matching)

    def _record_customer_actions(
        self,
        candidate: _Candidate,
        allocated_self_tpm: float,
        vendor_remaining: dict[str, float],
        actions: list[PolicyActionDraft],
        accepted_customers: list[dict],
        watermark_changes: list[dict],
    ) -> dict:
        demand = candidate.demand
        target_self_ratio = min(1.0, demand.current_self_ratio + allocated_self_tpm / demand.expected_tpm)
        target_self_tpm = demand.expected_tpm * target_self_ratio
        remaining_vendor_tpm = max(demand.expected_tpm - target_self_tpm, 0.0)
        vendor_key = self._vendor_key(candidate.best_vendor)
        vendor_cost = remaining_vendor_tpm * float(candidate.best_vendor.get("unit_cost", 0) or 0) * 60
        vendor_remaining[vendor_key] = vendor_remaining.get(vendor_key, 0.0) - remaining_vendor_tpm
        self_revenue = allocated_self_tpm * candidate.unit_self_revenue * 60
        expected_gain = self_revenue - vendor_cost
        watermark = {
            "report_id": demand.report_id,
            "customer_code": demand.customer_code,
            "model": demand.model_name,
            "from_self_ratio": demand.current_self_ratio,
            "to_self_ratio": target_self_ratio,
            "from_vendor_ratios": demand.current_vendor_ratios,
            "fallback_vendor": candidate.best_vendor.get("vendor"),
            "allocated_tpm_self": target_self_tpm,
            "incremental_tpm_self": allocated_self_tpm,
            "allocated_tpm_vendor": remaining_vendor_tpm,
        }
        watermark_changes.append(watermark)
        accepted_customers.append({
            "report_id": demand.report_id,
            "customer_code": demand.customer_code,
            "model": demand.model_name,
            "allocated_tpm_self": target_self_tpm,
            "incremental_tpm_self": allocated_self_tpm,
            "unit_self_revenue": candidate.unit_self_revenue,
            "fallback_vendor": candidate.best_vendor.get("vendor"),
            "score": candidate.score,
        })
        actions.append(PolicyActionDraft(
            action_type="watermark_adjust",
            payload=watermark,
            expected_gain=expected_gain,
        ))
        actions.append(PolicyActionDraft(
            action_type="model_assign",
            payload={
                "report_id": demand.report_id,
                "customer_code": demand.customer_code,
                "model": demand.model_name,
                "allocated_tpm_self": target_self_tpm,
                "incremental_tpm_self": allocated_self_tpm,
                "allocated_tpm_vendor": remaining_vendor_tpm,
                "fallback_vendor": candidate.best_vendor.get("vendor"),
            },
            expected_gain=expected_gain,
        ))
        return {
            "self_tpm": allocated_self_tpm,
            "self_revenue": self_revenue,
            "vendor_cost": vendor_cost,
        }

    def _allocate_to_existing_cluster(
        self,
        candidate: _Candidate,
        clusters: list[dict],
        native_idle: dict[str, float],
        received_idle: dict[str, float],
        need: float,
    ) -> float:
        # 只回收 need（首次=当前走三方缺口；腾挪后=剩余缺口），避免过量占用冗余、重复分配。
        remaining_need = need
        allocated = 0.0
        for cluster in self._matching_clusters(candidate.demand.model_name, clusters, candidate.demand.customer_code):
            name = cluster["cluster_name"]
            available = native_idle.get(name, 0.0) + received_idle.get(name, 0.0)
            if available <= 0:
                continue
            take = min(remaining_need, available)
            # 先扣“接收池”再扣“原生池”：接收机器锁定在本集群、优先用掉，把原生机器尽量留作可供出。
            from_received = min(take, received_idle.get(name, 0.0))
            received_idle[name] = received_idle.get(name, 0.0) - from_received
            native_idle[name] = native_idle.get(name, 0.0) - (take - from_received)
            remaining_need -= take
            allocated += take
            if remaining_need <= EPS:
                break
        return allocated

    def _plan_node_move(
        self,
        candidate: _Candidate,
        clusters: list[dict],
        cluster_extra_machines: dict[str, int],
        native_idle: dict[str, float],
        need: float,
    ) -> list[dict] | None:
        matching = self._matching_clusters(candidate.demand.model_name, clusters, candidate.demand.customer_code)
        if not matching:
            return None
        # 目标 = 匹配集群里单机能力最高者。无需再排除“donor”：供出只来自各集群自身仍空闲的
        # 原生机器（native_idle 背书），接收到的机器只进 received_idle、不可再供出，故不存在
        # A->B->C 的真 relay；集群既供又收（A→B & C→A）是安全的。
        target = max(matching, key=lambda c: float(c.get("tpm_per_machine", 0) or 0))
        target_rate = float(target.get("tpm_per_machine", 0) or 0)
        if target_rate <= 0:
            return None
        if need <= EPS:
            return None

        sources = [
            c for c in clusters
            if c["cluster_name"] != target["cluster_name"]
            and cluster_extra_machines.get(c["cluster_name"], 0) > 0
            and float(c.get("tpm_per_machine", 0) or 0) > 0
        ]
        # 供出源优先级：优先供出【单台产能低】的机器。因为搬走一台机器让源集群失去
        # removed_tpm = 台数 × 源单台产能 的原生产能（源侧机会成本），而目标新增恒为 台数 × 目标单台产能，
        # 与源无关。故先搬低产能机器可在拿到同样目标产能的同时，最小化源侧产能损失
        # （避免“搬走 7M/台的机器去当 2M/台用、白毁 5M”）。同产能再按可供台数多者优先。
        sources.sort(key=lambda c: (
            float(c.get("tpm_per_machine", 0) or 0),
            -cluster_extra_machines.get(c["cluster_name"], 0),
        ))

        # 修复 P8：跨多个源集群累积腾挪，直到覆盖 need（单源不够就继续找下一个）
        # P1（修正）：机器搬到目标集群后按【目标集群】单机能力评估产能——因为它要重部署为目标模型/配置。
        #   因此：目标新增 = 台数 × 目标单机能力；源集群失去 = 台数 × 源单机能力（两者不同）。
        moves: list[dict] = []
        added = 0.0
        for source in sources:
            if added >= need:
                break
            name = source["cluster_name"]
            src_rate = float(source.get("tpm_per_machine", 0) or 0)
            # 安全关键（P9 强化）：可搬走台数受源集群仍空闲的【原生】TPM 限制——只有 native_idle
            # 背书的机器才可供出；接收得到的 received_idle 不计入，杜绝供出已被占用的原生机器。
            movable = min(
                cluster_extra_machines.get(name, 0),
                int((native_idle.get(name, 0.0) + EPS) // src_rate),
            )
            if movable <= 0:
                continue
            shortfall = need - added
            machines = min(movable, max(1, ceil(shortfall / target_rate)))  # 按目标速率估算所需台数
            if machines <= 0:
                continue
            add_tpm = machines * target_rate      # 目标集群新增产能（目标单机能力）
            removed_tpm = machines * src_rate      # 源集群失去的闲置产能（源单机能力）
            moves.append({
                "from_cluster": name,
                "to_cluster": target["cluster_name"],
                "model": candidate.demand.model_name,
                "machine_count": machines,
                "added_tpm": add_tpm,
                "removed_tpm": removed_tpm,
                "from_tpm_per_machine": src_rate,
                "to_tpm_per_machine": target_rate,
                "reason": f"承接高收益客户 {candidate.demand.customer_code}",
            })
            added += add_tpm
        return moves or None

    def _build_constraints(
        self,
        candidates: list[_Candidate],
        rejected: list[dict],
        expected_revenue_gain: float,
        cluster_remaining: dict[str, float],
        vendor_remaining: dict[str, float],
        node_moves: list[dict],
    ) -> list[ConstraintHit]:
        rejected_reasons = {r["reason"] for r in rejected}
        return [
            ConstraintHit(
                name="vendor_capacity_sufficient",
                hit="vendor_capacity_or_model_unavailable" not in rejected_reasons and all(v >= 0 for v in vendor_remaining.values()),
                threshold=0.0,
                actual=min(vendor_remaining.values()) if vendor_remaining else 0.0,
                description="水位调整后三方供应商剩余额度必须能够承接未迁移流量",
            ),
            ConstraintHit(
                name="vendor_margin_positive",
                hit=bool(candidates) and "vendor_margin_discount_not_positive" not in rejected_reasons and "vendor_margin_not_positive" not in rejected_reasons,
                threshold=0.0,
                actual=min((c.vendor_margin_per_tpm for c in candidates), default=0.0),
                description="三方供应商承接时售卖折扣需高于采购折扣且毛利为正",
            ),
            ConstraintHit(
                name="self_cluster_capacity_sufficient",
                hit="self_cluster_capacity_insufficient" not in rejected_reasons,
                threshold=0.0,
                actual=sum(cluster_remaining.values()),
                description="自建集群容量需要足够承接选中的客户流量",
            ),
            ConstraintHit(
                name="model_match_satisfied",
                hit="vendor_capacity_or_model_unavailable" not in rejected_reasons,
                threshold=None,
                actual=None,
                description="客户模型需要匹配自建集群和三方供应商模型",
            ),
            ConstraintHit(
                name="node_move_feasible",
                hit="self_cluster_capacity_insufficient_after_node_move" not in rejected_reasons,
                threshold=0.0,
                actual=sum(m["machine_count"] for m in node_moves),
                description="容量不足时需要能够给出可执行的机器腾挪方案",
            ),
            ConstraintHit(
                name="positive_revenue_gain",
                hit=expected_revenue_gain > 0,
                threshold=0.0,
                actual=expected_revenue_gain,
                description="实时调整后的预期收益需要为正",
            ),
        ]
