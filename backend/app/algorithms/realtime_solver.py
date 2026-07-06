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
    best_vendor: dict
    vendor_purchase_discount: float
    vendor_margin_per_tpm: float
    score: float
    vendor_gap_tpm: float  # 当前走三方、可回收到自建的流量 = expected_tpm * (1 - current_self_ratio)
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
        cluster_remaining = {
            c["cluster_name"]: float(c.get("current_redundant_tpm", 0) or 0)
            for c in clusters
        }
        cluster_extra_machines = {
            c["cluster_name"]: self._donatable_machines(c)
            for c in clusters
        }

        candidates, rejected = self._build_candidates(snapshot.demands, snapshot.vendors, model_prices)
        candidates.sort(key=lambda c: c.score, reverse=True)

        actions: list[PolicyActionDraft] = []
        accepted_customers: list[dict] = []
        watermark_changes: list[dict] = []
        node_moves: list[dict] = []
        total_self_tpm = 0.0
        expected_self_revenue = 0.0
        expected_vendor_cost = 0.0
        remaining_candidates: list[_Candidate] = []

        for candidate in candidates:
            allocated = self._allocate_to_existing_cluster(candidate, clusters, cluster_remaining)
            if allocated <= 0:
                remaining_candidates.append(candidate)
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

        # 集群角色互斥：一个集群在本轮内只能是“供出方(donor)”或“接收方(receiver)”，不得两者兼具，
        # 从而杜绝 A->B->C 的资源倒手。
        donors_used: set[str] = set()
        receivers_used: set[str] = set()
        for candidate in remaining_candidates:
            moves = self._plan_node_move(candidate, clusters, cluster_extra_machines, cluster_remaining, donors_used, receivers_used)
            if not moves:
                rejected.append({
                    "report_id": candidate.demand.report_id,
                    "customer_code": candidate.demand.customer_code,
                    "reason": "self_cluster_capacity_insufficient",
                })
                continue

            # 修复 P8：一个客户可由多次腾挪共同承接
            for move in moves:
                src = move["from_cluster"]
                cluster_extra_machines[src] -= move["machine_count"]
                # 修复 P9（双重计数）：源集群失去这些机器的闲置产能（按源单机能力）
                cluster_remaining[src] = cluster_remaining.get(src, 0.0) - move["removed_tpm"]
                # P1（修正）：目标集群新增产能按目标单机能力计入
                cluster_remaining[move["to_cluster"]] = cluster_remaining.get(move["to_cluster"], 0.0) + move["added_tpm"]
                donors_used.add(src)
                receivers_used.add(move["to_cluster"])
                node_moves.append(move)
                actions.append(PolicyActionDraft(
                    action_type="node_move",
                    payload=move,
                    expected_gain=0.0,
                ))

            allocated = self._allocate_to_existing_cluster(candidate, clusters, cluster_remaining)
            if allocated <= 0:
                rejected.append({
                    "report_id": candidate.demand.report_id,
                    "customer_code": candidate.demand.customer_code,
                    "reason": "self_cluster_capacity_insufficient_after_node_move",
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
            # 修复 M1：以“单位TPM自建收入(密度)”为主排序键。机器成本固定、自建TPM有限时，
            # 最大化自建收入 = 分数背包，最优是按收入密度从高到低填满容量，而非按总额。
            # must_move 客户置顶（+大常数），其次按密度，密度相同再看总量。
            score = (
                (1e9 if must_move else 0.0)
                + unit_self_revenue * 1e6
                + max(demand.quality_score, 0) * 0.01
            )
            candidates.append(_Candidate(
                demand=demand,
                unit_self_revenue=unit_self_revenue,
                best_vendor=vendor,
                vendor_purchase_discount=purchase_discount,
                vendor_margin_per_tpm=vendor_margin,
                score=score,
                vendor_gap_tpm=current_vendor_tpm,
                must_move=must_move,
            ))
        return candidates, rejected

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

    def _allocate_to_existing_cluster(self, candidate: _Candidate, clusters: list[dict], cluster_remaining: dict[str, float]) -> float:
        # 修复 P4：只需回收「当前走三方的部分」，而非整份 expected_tpm，避免过量占用冗余
        remaining_need = candidate.vendor_gap_tpm
        allocated = 0.0
        for cluster in self._matching_clusters(candidate.demand.model_name, clusters, candidate.demand.customer_code):
            name = cluster["cluster_name"]
            available = cluster_remaining.get(name, 0.0)
            if available <= 0:
                continue
            take = min(remaining_need, available)
            cluster_remaining[name] = available - take
            remaining_need -= take
            allocated += take
            if remaining_need <= 0:
                break
        return allocated

    def _plan_node_move(
        self,
        candidate: _Candidate,
        clusters: list[dict],
        cluster_extra_machines: dict[str, int],
        cluster_remaining: dict[str, float],
        donors_used: set[str],
        receivers_used: set[str],
    ) -> list[dict] | None:
        matching = self._matching_clusters(candidate.demand.model_name, clusters, candidate.demand.customer_code)
        if not matching:
            return None
        # 禁止“倒手”：已作为供出方(donor)的集群不能再作为接收目标，否则会形成 A->B->C 的资源倒手
        target_candidates = [c for c in matching if c["cluster_name"] not in donors_used]
        if not target_candidates:
            return None
        target = max(target_candidates, key=lambda c: float(c.get("tpm_per_machine", 0) or 0))
        target_rate = float(target.get("tpm_per_machine", 0) or 0)
        if target_rate <= 0:
            return None
        # 修复 P4：腾挪只需覆盖三方待回收部分
        need = candidate.vendor_gap_tpm
        if need <= 0:
            return None

        sources = [
            c for c in clusters
            if c["cluster_name"] != target["cluster_name"]
            and c["cluster_name"] not in receivers_used          # 禁止“倒手”：已接收过机器的集群不得再供出
            and cluster_extra_machines.get(c["cluster_name"], 0) > 0
            and float(c.get("tpm_per_machine", 0) or 0) > 0
        ]
        sources.sort(key=lambda c: cluster_extra_machines.get(c["cluster_name"], 0), reverse=True)

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
            # 修复 P9（双重计数）：能真正搬走的机器数还受源集群当前仍空闲TPM限制（已被本集群客户占用的不能挪）
            movable = min(
                cluster_extra_machines.get(name, 0),
                int(cluster_remaining.get(name, 0.0) // src_rate),
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
