from __future__ import annotations

from ..extensions import db
from ..integrations import crm_client, resource_client
from ..models import (
    ApprovalLog,
    Customer,
    Demand,
    DemandStatus,
    Evaluation,
    EvaluationRecommendation,
    EvaluationStatus,
)
from ..utils.errors import NotFound, StateConflict
from ..utils.time import utcnow
from .demand_service import DemandService


LEVEL_SCORE = {"S": 1.0, "A": 0.85, "B": 0.6, "C": 0.4}


class EvaluationService:
    def __init__(self):
        self.demand_service = DemandService()

    def evaluate(self, demand_id: int, force: bool = False) -> Evaluation:
        demand = self.demand_service.get(demand_id)
        if demand.status not in (DemandStatus.PENDING, DemandStatus.EVALUATING) and not force:
            raise StateConflict(
                "当前需求不可评估",
                details={"status": demand.status, "force": force},
            )

        feasibility = self._feasibility(demand)
        customer_value = self._customer_value(demand)
        expected_revenue, expected_cost = self._estimate_financials(demand)
        margin = expected_revenue - expected_cost

        recommendation = self._recommend(feasibility, customer_value, margin)

        evaluation = Evaluation(
            demand_id=demand.id,
            feasibility_score=feasibility,
            customer_value_score=customer_value,
            expected_revenue=expected_revenue,
            expected_cost=expected_cost,
            expected_margin=margin,
            factors_json={
                "feasibility": feasibility,
                "customer_value": customer_value,
                "expected_margin": margin,
                "discount_rate": float(demand.discount_rate or 1.0),
            },
            recommendation=recommendation,
            status=EvaluationStatus.PENDING,
        )
        db.session.add(evaluation)
        db.session.flush()

        db.session.add(ApprovalLog(
            evaluation_id=evaluation.id,
            action="create",
            operator="system",
            comment="评估生成",
            after_json={
                "feasibility": feasibility,
                "customer_value": customer_value,
                "recommendation": recommendation,
            },
        ))

        # 评估生成后统一进入待审批态（PENDING/EVALUATING → AWAITING_APPROVAL）。
        demand.status = DemandStatus.AWAITING_APPROVAL
        db.session.flush()
        self._submit_demand_evaluation_policy(demand.id)
        return evaluation

    def approve(self, evaluation_id: int, operator: str, comment: str | None = None) -> Evaluation:
        evaluation, demand = self._load(evaluation_id)
        if evaluation.status != EvaluationStatus.PENDING:
            raise StateConflict(
                "评估状态不可审批",
                details={"status": evaluation.status},
            )
        self._approve(evaluation, demand, operator=operator, comment=comment)
        return evaluation

    def reject(self, evaluation_id: int, operator: str, reason: str) -> Evaluation:
        evaluation, demand = self._load(evaluation_id)
        if evaluation.status != EvaluationStatus.PENDING:
            raise StateConflict("评估状态不可驳回", details={"status": evaluation.status})
        before = {"status": evaluation.status}
        evaluation.status = EvaluationStatus.REJECTED
        evaluation.decided_by = operator
        evaluation.decided_at = utcnow()
        evaluation.decided_reason = reason
        demand.status = DemandStatus.REJECTED
        db.session.add(ApprovalLog(
            evaluation_id=evaluation.id,
            action="reject",
            operator=operator,
            comment=reason,
            before_json=before,
            after_json={"status": evaluation.status},
        ))
        db.session.flush()
        return evaluation

    def _approve(self, evaluation: Evaluation, demand: Demand, operator: str, comment: str | None):
        before = {"status": evaluation.status}
        evaluation.status = EvaluationStatus.APPROVED
        evaluation.decided_by = operator
        evaluation.decided_at = utcnow()
        evaluation.decided_reason = comment
        demand.status = DemandStatus.APPROVED
        db.session.add(ApprovalLog(
            evaluation_id=evaluation.id,
            action="approve",
            operator=operator,
            comment=comment,
            before_json=before,
            after_json={"status": evaluation.status},
        ))
        db.session.flush()

    def _submit_demand_evaluation_policy(self, demand_id: int):
        from .policy_service import PolicyService
        PolicyService().submit_run(
            "demand_evaluation",
            demand_ids=[demand_id],
            params={"template": "需求评估策略", "module": "demand_evaluation"},
            triggered_by="demand_evaluation",
            demand_id=demand_id,
        )

    def _load(self, evaluation_id: int):
        evaluation = db.session.get(Evaluation, evaluation_id)
        if not evaluation:
            raise NotFound("评估不存在", details={"id": evaluation_id})
        demand = db.session.get(Demand, evaluation.demand_id)
        if not demand:
            raise NotFound("评估关联的需求不存在", details={"demand_id": evaluation.demand_id})
        return evaluation, demand

    def _feasibility(self, demand: Demand) -> float:
        snapshot = resource_client().snapshot()
        if snapshot.total_capacity_tpm == 0:
            return 0
        redundant = snapshot.total_current_redundant_tpm
        ratio = float(demand.expected_tpm or 0) / redundant if redundant else 1
        feasibility = max(0.0, min(1.0, 1.0 - ratio * 0.5))
        return round(feasibility, 4)

    def _customer_value(self, demand: Demand) -> float:
        customer = db.session.get(Customer, demand.customer_id) if demand.customer_id else None
        if not customer:
            return 0.5
        profile = crm_client().profile(customer.customer_code)
        level_score = LEVEL_SCORE.get(profile.level, 0.5)
        achievement_bonus = min(profile.historical_achievement_rate, 1.2) * 0.2
        return round(min(1.0, level_score + achievement_bonus), 4)

    def _estimate_financials(self, demand: Demand) -> tuple[float, float]:
        unit_revenue = 0.0014 * float(demand.discount_rate or 1.0)
        unit_cost_self = 0.0007
        tpm = float(demand.expected_tpm or 0)
        # assume per-minute revenue * 60 * 24 * 30 days as monthly estimate
        revenue = tpm * unit_revenue * 60 * 24 * 30
        cost = tpm * unit_cost_self * 60 * 24 * 30
        return round(revenue, 2), round(cost, 2)

    def _recommend(self, feasibility, customer_value, margin) -> str:
        if margin < 0:
            return EvaluationRecommendation.REJECT
        if feasibility >= 0.7 and customer_value >= 0.7 and margin >= 10_000:
            return EvaluationRecommendation.AUTO_APPROVE
        return EvaluationRecommendation.MANUAL_REVIEW
