from __future__ import annotations

from sqlalchemy import select

from ..models import Demand, DemandStatus
from .base_repository import BaseRepository


class DemandRepository(BaseRepository[Demand]):
    model = Demand

    def get_by_report_id(self, report_id: str) -> Demand | None:
        return self.session.execute(
            select(Demand).where(Demand.report_id == report_id)
        ).scalar_one_or_none()

    def list(self, status: str | None = None, customer_id: int | None = None, model: str | None = None,
             page: int = 1, page_size: int = 20):
        filters = []
        if status:
            filters.append(Demand.status == status)
        if customer_id:
            filters.append(Demand.customer_id == customer_id)
        if model:
            filters.append(Demand.model_name == model)
        return self.list_paginated(filters=filters, page=page, page_size=page_size)

    def count_by_status(self) -> dict[str, int]:
        from sqlalchemy import func
        rows = self.session.execute(
            select(Demand.status, func.count()).group_by(Demand.status)
        ).all()
        return {status: count for status, count in rows}
