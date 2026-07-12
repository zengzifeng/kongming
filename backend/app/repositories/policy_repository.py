from __future__ import annotations

from sqlalchemy import select

from ..models import Policy, PolicyRun, PolicyAction
from .base_repository import BaseRepository


class PolicyRunRepository(BaseRepository[PolicyRun]):
    model = PolicyRun

    def list(self, status=None, algorithm=None, page=1, page_size=20):
        filters = []
        if status:
            filters.append(PolicyRun.status == status)
        if algorithm:
            filters.append(PolicyRun.algorithm == algorithm)
        return self.list_paginated(filters=filters, page=page, page_size=page_size)


class PolicyRepository(BaseRepository[Policy]):
    model = Policy

    def list(self, status=None, algorithm=None, policy_run_id=None, exclude_status=None,
             demand_id=None, has_demand=None, page=1, page_size=20):
        filters = []
        if status:
            filters.append(Policy.status == status)
        if exclude_status:
            filters.append(Policy.status != exclude_status)
        if algorithm:
            filters.append(Policy.algorithm == algorithm)
        if policy_run_id:
            filters.append(Policy.policy_run_id == policy_run_id)
        if demand_id is not None:
            filters.append(Policy.demand_id == demand_id)
        if has_demand is True:
            filters.append(Policy.demand_id.isnot(None))
        elif has_demand is False:
            filters.append(Policy.demand_id.is_(None))
        return self.list_paginated(filters=filters, page=page, page_size=page_size)

    def actions_for(self, policy_id: int) -> list[PolicyAction]:
        return self.session.execute(
            select(PolicyAction).where(PolicyAction.policy_id == policy_id)
        ).scalars().all()

    def latest_for_demand(self, demand_id: int) -> Policy | None:
        # 一个需求对应一条策略：取该 demand 最新的产出策略。
        return self.session.execute(
            select(Policy).where(Policy.demand_id == demand_id)
            .order_by(Policy.id.desc()).limit(1)
        ).scalar_one_or_none()
