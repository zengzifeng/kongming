from __future__ import annotations

from sqlalchemy import select

from ..models import (
    CustomerFittingConfig,
    FittingAlgorithm,
    FittingResult,
)
from .base_repository import BaseRepository


class FittingAlgorithmRepository(BaseRepository[FittingAlgorithm]):
    model = FittingAlgorithm

    def list_all(self) -> list[FittingAlgorithm]:
        return list(
            self.session.execute(
                select(FittingAlgorithm).order_by(FittingAlgorithm.id.asc())
            ).scalars()
        )

    def get_by_name(self, algo_name: str) -> FittingAlgorithm | None:
        return self.session.execute(
            select(FittingAlgorithm).where(FittingAlgorithm.algo_name == algo_name)
        ).scalar_one_or_none()


class CustomerFittingConfigRepository(BaseRepository[CustomerFittingConfig]):
    model = CustomerFittingConfig

    def list(self, ai_consumer: str | None = None, model_name: str | None = None,
             period: str | None = None) -> list[CustomerFittingConfig]:
        stmt = select(CustomerFittingConfig)
        if ai_consumer:
            stmt = stmt.where(CustomerFittingConfig.ai_consumer == ai_consumer)
        if model_name:
            stmt = stmt.where(CustomerFittingConfig.model_name == model_name)
        if period:
            stmt = stmt.where(CustomerFittingConfig.period == period)
        stmt = stmt.order_by(CustomerFittingConfig.id.asc())
        return self._unique_by_consumer_model(self.session.execute(stmt).scalars())

    def get_natural(self, ai_consumer: str, model_name: str) -> CustomerFittingConfig | None:
        return self.session.execute(
            select(CustomerFittingConfig)
            .where(
                CustomerFittingConfig.ai_consumer == ai_consumer,
                CustomerFittingConfig.model_name == model_name,
            )
            .order_by(CustomerFittingConfig.id.asc())
        ).scalars().first()

    def list_enabled(self) -> list[CustomerFittingConfig]:
        rows = self.session.execute(
            select(CustomerFittingConfig)
            .where(CustomerFittingConfig.enabled.is_(True))
            .order_by(CustomerFittingConfig.id.asc())
        ).scalars()
        return self._unique_by_consumer_model(rows)

    @staticmethod
    def _unique_by_consumer_model(rows) -> list[CustomerFittingConfig]:
        seen: set[tuple[str, str]] = set()
        unique: list[CustomerFittingConfig] = []
        for row in rows:
            key = (row.ai_consumer, row.model_name)
            if key in seen:
                continue
            seen.add(key)
            unique.append(row)
        return unique


class FittingResultRepository(BaseRepository[FittingResult]):
    model = FittingResult

    def list(self, level: str | None = None, ai_consumer: str | None = None,
             model_name: str | None = None, period: str | None = None,
             page: int = 1, page_size: int = 50):
        filters = []
        if level:
            filters.append(FittingResult.level == level)
        if ai_consumer:
            filters.append(FittingResult.ai_consumer == ai_consumer)
        if model_name:
            filters.append(FittingResult.model_name == model_name)
        if period:
            filters.append(FittingResult.period == period)
        return self.list_paginated(
            filters=filters,
            order_by=FittingResult.generated_at.desc(),
            page=page,
            page_size=page_size,
        )

    def latest_for(self, level: str, ai_consumer: str | None, model_name: str,
                   period: str, cluster_name: str | None = None) -> FittingResult | None:
        stmt = select(FittingResult).where(
            FittingResult.level == level,
            FittingResult.model_name == model_name,
            FittingResult.period == period,
        )
        if ai_consumer is not None:
            stmt = stmt.where(FittingResult.ai_consumer == ai_consumer)
        if cluster_name is not None:
            stmt = stmt.where(FittingResult.cluster_name == cluster_name)
        stmt = stmt.order_by(FittingResult.generated_at.desc())
        return self.session.execute(stmt).scalars().first()
