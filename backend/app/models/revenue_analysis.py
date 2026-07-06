from datetime import datetime
from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class PolicyRevenueAnalysis(BaseModel):
    __tablename__ = "policy_revenue_analyses"

    policy_id: Mapped[int] = mapped_column(ForeignKey("policies.id"), unique=True, nullable=False, index=True)
    analysis_reason: Mapped[str | None] = mapped_column(String(1024))
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    archived_by: Mapped[str | None] = mapped_column(String(64))
    archived_at: Mapped[datetime | None] = mapped_column()
