from datetime import datetime
from sqlalchemy import JSON, String, ForeignKey, Numeric, Index
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class SnapshotPhase:
    BEFORE = "before"
    AFTER = "after"


class MetricSnapshot(BaseModel):
    __tablename__ = "metric_snapshots"
    __table_args__ = (Index("ix_metric_snapshots_policy_phase", "policy_id", "phase"),)

    policy_id: Mapped[int] = mapped_column(ForeignKey("policies.id"), nullable=False)
    phase: Mapped[str] = mapped_column(String(16), nullable=False)
    window_start: Mapped[datetime] = mapped_column(nullable=False)
    window_end: Mapped[datetime] = mapped_column(nullable=False)
    tpm_self: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    tpm_vendor: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    revenue: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    cost_self: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    cost_vendor: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    cache_hit_rate: Mapped[float] = mapped_column(Numeric(6, 4), default=0)
    gpu_utilization: Mapped[float] = mapped_column(Numeric(6, 4), default=0)
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)
