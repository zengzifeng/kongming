from datetime import datetime
from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class JobLog(BaseModel):
    __tablename__ = "job_logs"

    job_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(16), default="running")
    message: Mapped[str | None] = mapped_column(String(1024))
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
