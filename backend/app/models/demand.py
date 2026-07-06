from datetime import datetime
from sqlalchemy import String, ForeignKey, Numeric, Index
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class DemandStatus:
    PENDING = "pending"
    EVALUATING = "evaluating"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    LIVE = "live"
    CLOSED = "closed"
    REJECTED = "rejected"

    ALL = {PENDING, EVALUATING, AWAITING_APPROVAL, APPROVED, SCHEDULED, LIVE, CLOSED, REJECTED}


VALID_TRANSITIONS = {
    DemandStatus.PENDING: {DemandStatus.EVALUATING, DemandStatus.REJECTED, DemandStatus.CLOSED},
    DemandStatus.EVALUATING: {DemandStatus.AWAITING_APPROVAL, DemandStatus.APPROVED, DemandStatus.REJECTED},
    DemandStatus.AWAITING_APPROVAL: {DemandStatus.APPROVED, DemandStatus.REJECTED},
    DemandStatus.APPROVED: {DemandStatus.SCHEDULED, DemandStatus.REJECTED, DemandStatus.CLOSED},
    DemandStatus.SCHEDULED: {DemandStatus.LIVE, DemandStatus.CLOSED},
    DemandStatus.LIVE: {DemandStatus.CLOSED},
    DemandStatus.CLOSED: set(),
    DemandStatus.REJECTED: set(),
}


class Demand(BaseModel):
    __tablename__ = "demands"
    __table_args__ = (
        Index("ix_demands_status_created_at", "status", "created_at"),
    )

    report_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_tpm: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    expected_rpm: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    discount_rate: Mapped[float] = mapped_column(Numeric(6, 4), default=1.0)
    expected_start_at: Mapped[datetime | None] = mapped_column()
    expected_end_at: Mapped[datetime | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(32), default=DemandStatus.PENDING, nullable=False, index=True)
    source_batch_id: Mapped[int | None] = mapped_column(ForeignKey("sync_batches.id"))
    source_payload_hash: Mapped[str | None] = mapped_column(String(64))
    field_completeness_score: Mapped[float] = mapped_column(Numeric(5, 4), default=0)
