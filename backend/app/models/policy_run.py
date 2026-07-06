from datetime import datetime
from sqlalchemy import JSON, String, Integer
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class PolicyRunStatus:
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class PolicyRun(BaseModel):
    __tablename__ = "policy_runs"

    run_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    triggered_by: Mapped[str] = mapped_column(String(64), default="manual")
    algorithm: Mapped[str] = mapped_column(String(32), default="realtime", index=True)
    input_snapshot_json: Mapped[dict] = mapped_column(JSON, default=dict)
    input_hash: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), default=PolicyRunStatus.QUEUED, index=True)
    started_at: Mapped[datetime | None] = mapped_column()
    finished_at: Mapped[datetime | None] = mapped_column()
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(String(2048))
