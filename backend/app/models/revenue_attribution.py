from datetime import datetime
from sqlalchemy import String, ForeignKey, Numeric, Index
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class RevenueMechanism:
    PEAK_SHAVING = "peak_shaving"
    OFF_PEAK_ADJUST = "off_peak_adjust"


class RevenueAttribution(BaseModel):
    __tablename__ = "revenue_attributions"
    __table_args__ = (Index("ix_attr_policy_mechanism_project", "policy_id", "mechanism", "project_code"),)

    policy_id: Mapped[int] = mapped_column(ForeignKey("policies.id"), nullable=False)
    mechanism: Mapped[str] = mapped_column(String(32), nullable=False)
    project_code: Mapped[str] = mapped_column(String(64), nullable=False)
    project_name: Mapped[str | None] = mapped_column(String(128))
    revenue_delta: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    cost_delta: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    margin_delta: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    allocation_ratio: Mapped[float] = mapped_column(Numeric(6, 4), default=0)
    computed_at: Mapped[datetime] = mapped_column(nullable=False)
