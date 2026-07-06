from __future__ import annotations

from sqlalchemy import select

from ..models import MetricSnapshot
from .base_repository import BaseRepository


class MetricSnapshotRepository(BaseRepository[MetricSnapshot]):
    model = MetricSnapshot

    def for_policy(self, policy_id: int) -> list[MetricSnapshot]:
        return self.session.execute(
            select(MetricSnapshot).where(MetricSnapshot.policy_id == policy_id)
            .order_by(MetricSnapshot.id.asc())
        ).scalars().all()
