from datetime import datetime
from sqlalchemy import JSON, String, Index
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class AlertSeverity:
    INFO = "info"
    WARN = "warn"
    CRITICAL = "critical"


class AlertStatus:
    OPEN = "open"
    ACK = "ack"
    CLOSED = "closed"


class Alert(BaseModel):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_status_severity_created", "status", "severity", "created_at"),)

    alert_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), default=AlertSeverity.WARN, nullable=False)
    subject_type: Mapped[str | None] = mapped_column(String(64))
    subject_id: Mapped[str | None] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(String(1024), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default=AlertStatus.OPEN, nullable=False, index=True)
    acked_by: Mapped[str | None] = mapped_column(String(64))
    acked_at: Mapped[datetime | None] = mapped_column()
    closed_at: Mapped[datetime | None] = mapped_column()
