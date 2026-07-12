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

    def list(self, customer_code: str | None = None, model_name: str | None = None,
             period: str | None = None) -> list[CustomerFittingConfig]:
        stmt = select(CustomerFittingConfig)
        if customer_code:
            stmt = stmt.where(CustomerFittingConfig.customer_code == customer_code)
        if model_name:
            stmt = stmt.where(CustomerFittingConfig.model_name == model_name)
        if period:
            stmt = stmt.where(CustomerFittingConfig.period == period)
        stmt = stmt.order_by(CustomerFittingConfig.id.asc())
        return list(self.session.execute(stmt).scalars())

    def get_natural(self, customer_code: str, model_name: str, period: str) -> CustomerFittingConfig | None:
        return self.session.execute(
            select(CustomerFittingConfig).where(
                CustomerFittingConfig.customer_code == customer_code,
                CustomerFittingConfig.model_name == model_name,
                CustomerFittingConfig.period == period,
            )
        ).scalar_one_or_none()

    def list_enabled(self) -> list[CustomerFittingConfig]:
        return list(
            self.session.execute(
                select(CustomerFittingConfig)
                .where(CustomerFittingConfig.enabled.is_(True))
                .order_by(CustomerFittingConfig.id.asc())
            ).scalars()
        )


class FittingResultRepository(BaseRepository[FittingResult]):
    model = FittingResult

    def list(self, level: str | None = None, customer_code: str | None = None,
             model_name: str | None = None, period: str | None = None,
             page: int = 1, page_size: int = 50):
        filters = []
        if level:
            filters.append(FittingResult.level == level)
        if customer_code:
            filters.append(FittingResult.customer_code == customer_code)
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

    def latest_for(self, level: str, customer_code: str | None, model_name: str,
                   period: str, cluster_name: str | None = None) -> FittingResult | None:
        stmt = select(FittingResult).where(
            FittingResult.level == level,
            FittingResult.model_name == model_name,
            FittingResult.period == period,
        )
        if customer_code is not None:
            stmt = stmt.where(FittingResult.customer_code == customer_code)
        if cluster_name is not None:
            stmt = stmt.where(FittingResult.cluster_name == cluster_name)
        stmt = stmt.order_by(FittingResult.generated_at.desc())
        return self.session.execute(stmt).scalars().first()
