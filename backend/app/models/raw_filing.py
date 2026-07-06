from datetime import datetime
from sqlalchemy import JSON, String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class RawFiling(BaseModel):
    __tablename__ = "raw_filings"
    __table_args__ = (UniqueConstraint("batch_id", "report_id", name="uq_raw_filings_batch_report"),)

    batch_id: Mapped[int] = mapped_column(ForeignKey("sync_batches.id"), nullable=False, index=True)
    report_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    pulled_at: Mapped[datetime] = mapped_column(nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
