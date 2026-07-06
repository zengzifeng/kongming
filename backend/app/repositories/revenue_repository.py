from __future__ import annotations

from datetime import date
from sqlalchemy import select

from ..models import RevenueAttribution, CustomerUsageDaily
from .base_repository import BaseRepository


class RevenueAttributionRepository(BaseRepository[RevenueAttribution]):
    model = RevenueAttribution

    def list(self, policy_id=None, mechanism=None, project_code=None,
             page=1, page_size=20):
        filters = []
        if policy_id:
            filters.append(RevenueAttribution.policy_id == policy_id)
        if mechanism:
            filters.append(RevenueAttribution.mechanism == mechanism)
        if project_code:
            filters.append(RevenueAttribution.project_code == project_code)
        return self.list_paginated(filters=filters, page=page, page_size=page_size)

    def for_policy(self, policy_id: int) -> list[RevenueAttribution]:
        return self.session.execute(
            select(RevenueAttribution).where(RevenueAttribution.policy_id == policy_id)
        ).scalars().all()


class CustomerUsageRepository(BaseRepository[CustomerUsageDaily]):
    model = CustomerUsageDaily

    def for_customer(self, customer_id: int, start: date | None = None, end: date | None = None):
        filters = [CustomerUsageDaily.customer_id == customer_id]
        if start:
            filters.append(CustomerUsageDaily.stat_date >= start)
        if end:
            filters.append(CustomerUsageDaily.stat_date <= end)
        return self.session.execute(
            select(CustomerUsageDaily).where(*filters).order_by(CustomerUsageDaily.stat_date.desc())
        ).scalars().all()

    def for_report(self, report_id: str):
        return self.session.execute(
            select(CustomerUsageDaily).where(CustomerUsageDaily.report_id == report_id)
            .order_by(CustomerUsageDaily.stat_date.desc())
        ).scalars().all()
