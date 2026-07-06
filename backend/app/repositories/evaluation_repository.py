from sqlalchemy import select

from ..models import Evaluation, EvaluationStatus
from .base_repository import BaseRepository


class EvaluationRepository(BaseRepository[Evaluation]):
    model = Evaluation

    def latest_for_demand(self, demand_id: int) -> Evaluation | None:
        return self.session.execute(
            select(Evaluation).where(Evaluation.demand_id == demand_id)
            .order_by(Evaluation.id.desc()).limit(1)
        ).scalar_one_or_none()

    def list(self, status: str | None = None, recommendation: str | None = None,
             page: int = 1, page_size: int = 20):
        filters = []
        if status:
            filters.append(Evaluation.status == status)
        if recommendation:
            filters.append(Evaluation.recommendation == recommendation)
        return self.list_paginated(filters=filters, page=page, page_size=page_size)
