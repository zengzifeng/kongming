from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select

from ..extensions import db
from ..models import Alert, Demand, Policy, RevenueAttribution
from ..models.alert import AlertStatus
from ..models.demand import DemandStatus
from ..models.policy import PolicyStatus
from ..utils.time import utcnow


class ReportService:
    def weekly(self, week: str | None = None) -> dict:
        now = utcnow()
        since = now - timedelta(days=7)
        return self._summary("weekly", since, now, week)

    def monthly(self, month: str | None = None) -> dict:
        now = utcnow()
        since = now - timedelta(days=30)
        return self._summary("monthly", since, now, month)

    def _summary(self, kind: str, since, now, label: str | None) -> dict:
        new_demands = db.session.execute(
            select(func.count(Demand.id)).where(Demand.created_at >= since)
        ).scalar_one()
        new_policies = db.session.execute(
            select(func.count(Policy.id)).where(Policy.created_at >= since)
        ).scalar_one()
        revenue_delta = db.session.execute(
            select(func.coalesce(func.sum(RevenueAttribution.revenue_delta), 0))
            .where(RevenueAttribution.computed_at >= since)
        ).scalar_one()
        pending_demands = db.session.execute(
            select(func.count(Demand.id)).where(Demand.status.in_([
                DemandStatus.PENDING,
                DemandStatus.EVALUATING,
                DemandStatus.AWAITING_APPROVAL,
            ]))
        ).scalar_one()
        accepted_policies = db.session.execute(
            select(func.count(Policy.id)).where(
                Policy.status == PolicyStatus.ACCEPTED)
        ).scalar_one()
        expected_revenue_gain = db.session.execute(
            select(func.coalesce(func.sum(Policy.expected_revenue_gain), 0))
        ).scalar_one()
        open_alerts = db.session.execute(
            select(func.count(Alert.id)).where(
                Alert.status == AlertStatus.OPEN)
        ).scalar_one()
        demand_status_rows = db.session.execute(
            select(Demand.status, func.count(
                Demand.id)).group_by(Demand.status)
        ).all()
        policy_gain_rows = db.session.execute(
            select(Policy.algorithm, func.coalesce(
                func.sum(Policy.expected_revenue_gain), 0))
            .group_by(Policy.algorithm)
        ).all()
        period = label or (now.strftime("%G-W%V") if kind ==
                           "weekly" else now.strftime("%Y-%m"))
        expected_gain_value = float(expected_revenue_gain or 0)
        return {
            "kind": kind,
            "label": label,
            "range": {"from": since.isoformat(), "to": now.isoformat()},
            "new_demands": new_demands,
            "new_policies": new_policies,
            "revenue_delta": float(revenue_delta or 0),
            "period": period,
            "generated_at": now.isoformat(),
            "summary": {
                "new_demands": new_demands,
                "pending_demands": pending_demands,
                "accepted_policies": accepted_policies,
                "expected_revenue_gain": expected_gain_value,
                "open_alerts": open_alerts,
            },
            "highlights": [
                f"新增需求 {new_demands} 个",
                f"已采纳策略 {accepted_policies} 个",
                f"预期收益增量 {expected_gain_value:.2f}",
            ],
            "charts": {
                "demand_status": {status: count for status, count in demand_status_rows},
                "policy_gain_by_algorithm": {
                    algorithm: float(gain or 0)
                    for algorithm, gain in policy_gain_rows
                },
            },
        }
