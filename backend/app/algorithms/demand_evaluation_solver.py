from __future__ import annotations

from ..utils.errors import AlgorithmError
from .base import ConstraintHit, PolicyActionDraft, PolicyInputSnapshot, PolicyResult


class DemandEvaluationSolver:
    """Build a policy proposal for manual demand evaluation approval."""

    name = "demand_evaluation"

    def solve(self, snapshot: PolicyInputSnapshot) -> PolicyResult:
        if not snapshot.demands:
            raise AlgorithmError("快照中无可处理需求", code="ALGORITHM_FAILED")

        evaluation_map = {
            int(item.get("demand_id", 0)): item
            for item in snapshot.params.get("evaluations", [])
            if item.get("demand_id") is not None
        }
        actions: list[PolicyActionDraft] = []
        proposals: list[dict] = []
        total_margin = 0.0
        feasibility_values: list[float] = []
        benefit_values: list[float] = []

        for demand in snapshot.demands:
            demand_id = int(snapshot.params.get("demand_id_by_report_id", {}).get(demand.report_id, 0))
            evaluation = evaluation_map.get(demand_id, {})
            feasibility = float(evaluation.get("feasibility_score", 0) or 0)
            benefit = float(evaluation.get("customer_value_score", 0) or 0)
            expected_revenue = float(evaluation.get("expected_revenue", 0) or 0)
            expected_cost = float(evaluation.get("expected_cost", 0) or 0)
            expected_margin = float(evaluation.get("expected_margin", expected_revenue - expected_cost) or 0)
            recommendation = str(evaluation.get("recommendation") or "manual_review")
            proposal = {
                "demand_id": demand_id,
                "report_id": demand.report_id,
                "customer_code": demand.customer_code,
                "model": demand.model_name,
                "expected_tpm": demand.expected_tpm,
                "expected_rpm": demand.expected_rpm,
                "discount_rate": demand.discount_rate,
                "evaluation_id": evaluation.get("id"),
                "demand_strategy_id": f"DES-{demand.report_id}",
                "feasibility_score": feasibility,
                "benefit_score": benefit,
                "expected_revenue": expected_revenue,
                "expected_cost": expected_cost,
                "expected_margin": expected_margin,
                "recommendation": recommendation,
            }
            proposals.append(proposal)
            total_margin += expected_margin
            feasibility_values.append(feasibility)
            benefit_values.append(benefit)
            actions.append(PolicyActionDraft(
                action_type="demand_evaluation_plan",
                payload=proposal,
                expected_gain=expected_margin,
            ))

        primary = proposals[0]
        avg_feasibility = sum(feasibility_values) / max(len(feasibility_values), 1)
        avg_benefit = sum(benefit_values) / max(len(benefit_values), 1)
        return PolicyResult(
            expected_revenue_gain=total_margin,
            expected_peak_shaving_gain=0.0,
            expected_off_peak_gain=0.0,
            constraints=[
                ConstraintHit(
                    name="manual_evaluation_required",
                    hit=True,
                    threshold=0.7,
                    actual=avg_feasibility,
                    description="需求评估策略需人工确认或驳回",
                ),
            ],
            actions=actions,
            diagnostics={"solver": self.name, "proposal_count": len(proposals)},
            summary={
                "template": "需求评估策略",
                "module": "demand_evaluation",
                "target": f"{primary['report_id']} 需求评估",
                "demand_id": primary["demand_id"],
                "report_id": primary["report_id"],
                "evaluation_id": primary.get("evaluation_id"),
                "demand_strategy_id": primary["demand_strategy_id"],
                "customer_code": primary["customer_code"],
                "model": primary["model"],
                "expected_tpm": primary["expected_tpm"],
                "expected_rpm": primary["expected_rpm"],
                "feasibility_score": primary["feasibility_score"],
                "benefit_score": primary["benefit_score"],
                "expected_revenue": primary["expected_revenue"],
                "expected_cost": primary["expected_cost"],
                "expected_margin": primary["expected_margin"],
                "recommendation": primary["recommendation"],
                "avg_feasibility_score": avg_feasibility,
                "avg_benefit_score": avg_benefit,
                "demand_status": "awaiting_approval",
                "proposals": proposals,
            },
        )
