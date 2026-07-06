from __future__ import annotations

from sqlalchemy import func, select

from ..extensions import db
from ..models import Policy, PolicyRevenueAnalysis, RevenueAttribution
from ..utils.errors import NotFound
from ..utils.time import utcnow


class RevenueAnalysisService:
    def analysis(self) -> dict:
        revenue_by_policy = dict(
            db.session.execute(
                select(
                    RevenueAttribution.policy_id,
                    func.coalesce(func.sum(RevenueAttribution.revenue_delta), 0),
                ).group_by(RevenueAttribution.policy_id)
            ).all()
        )
        analysis_by_policy = {
            item.policy_id: item
            for item in db.session.execute(select(PolicyRevenueAnalysis)).scalars().all()
        }
        policies = db.session.execute(select(Policy).order_by(Policy.created_at.desc())).scalars().all()

        items = []
        for policy in policies:
            expected = float(policy.expected_revenue_gain or 0)
            actual = float(revenue_by_policy.get(policy.id, 0) or 0)
            gap = actual - expected
            achievement_status = "achieved" if actual >= expected else "not_achieved"
            persisted = analysis_by_policy.get(policy.id)
            reason = persisted.analysis_reason if persisted and persisted.analysis_reason else self._default_reason(achievement_status, gap)
            item = {
                "policy_id": policy.id,
                "policy_no": policy.policy_no,
                "algorithm": policy.algorithm,
                "policy_status": policy.status,
                "expected_revenue_gain": expected,
                "actual_revenue_gain": actual,
                "revenue_gap": gap,
                "achievement_status": achievement_status,
                "analysis_reason": reason,
                "archived": bool(persisted.archived) if persisted else False,
                "archived_by": persisted.archived_by if persisted else None,
                "archived_at": persisted.archived_at.isoformat() if persisted and persisted.archived_at else None,
            }
            items.append(item)

        achieved = sum(1 for item in items if item["achievement_status"] == "achieved")
        not_achieved = len(items) - achieved
        unarchived_not_achieved = [
            item for item in items
            if item["achievement_status"] == "not_achieved" and not item["archived"]
        ]
        by_algorithm = {}
        for item in items:
            bucket = by_algorithm.setdefault(item["algorithm"], {"achieved": 0, "not_achieved": 0, "total": 0})
            bucket[item["achievement_status"]] += 1
            bucket["total"] += 1

        return {
            "underperforming": unarchived_not_achieved,
            "overview": {
                "total": len(items),
                "achieved": achieved,
                "not_achieved": not_achieved,
                "achieved_ratio": achieved / len(items) if items else 0,
                "not_achieved_ratio": not_achieved / len(items) if items else 0,
                "by_algorithm": by_algorithm,
            },
            "items": items,
        }

    def archive(self, policy_id: int, operator: str, reason: str) -> dict:
        policy = db.session.get(Policy, policy_id)
        if not policy:
            raise NotFound("策略不存在", details={"id": policy_id})
        item = db.session.execute(
            select(PolicyRevenueAnalysis).where(PolicyRevenueAnalysis.policy_id == policy_id)
        ).scalar_one_or_none()
        if not item:
            item = PolicyRevenueAnalysis(policy_id=policy_id)
            db.session.add(item)
        item.analysis_reason = reason
        item.archived = True
        item.archived_by = operator
        item.archived_at = utcnow()
        db.session.flush()
        return self.analysis()

    @staticmethod
    def _default_reason(achievement_status: str, gap: float) -> str:
        if achievement_status == "achieved":
            return "已达到预期收益"
        return f"实际收益低于预期，差额 {abs(gap):.2f}，待人工分析"
