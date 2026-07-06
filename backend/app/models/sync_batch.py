from datetime import datetime
from sqlalchemy import String, Integer
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class SyncBatchStatus:
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class SyncBatch(BaseModel):
    __tablename__ = "sync_batches"

    batch_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="filing_platform")
    triggered_by: Mapped[str] = mapped_column(String(16), default="cron")
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column()
    total_pulled: Mapped[int] = mapped_column(Integer, default=0)
    total_inserted: Mapped[int] = mapped_column(Integer, default=0)
    total_updated: Mapped[int] = mapped_column(Integer, default=0)
    total_skipped: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default=SyncBatchStatus.RUNNING, index=True)
    error_message: Mapped[str | None] = mapped_column(String(1024))
