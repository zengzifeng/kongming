from datetime import datetime
from sqlalchemy import JSON, String, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class EvaluationStatus:
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class EvaluationRecommendation:
    AUTO_APPROVE = "auto_approve"
    MANUAL_REVIEW = "manual_review"
    REJECT = "reject"


class Evaluation(BaseModel):
    __tablename__ = "evaluations"

    demand_id: Mapped[int] = mapped_column(ForeignKey("demands.id"), nullable=False, index=True)
    feasibility_score: Mapped[float] = mapped_column(Numeric(5, 4), default=0)
    customer_value_score: Mapped[float] = mapped_column(Numeric(5, 4), default=0)
    expected_revenue: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    expected_cost: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    expected_margin: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    factors_json: Mapped[dict] = mapped_column(JSON, default=dict)
    recommendation: Mapped[str] = mapped_column(String(32), default=EvaluationRecommendation.MANUAL_REVIEW)
    status: Mapped[str] = mapped_column(String(16), default=EvaluationStatus.PENDING, index=True)
    decided_by: Mapped[str | None] = mapped_column(String(64))
    decided_at: Mapped[datetime | None] = mapped_column()
    decided_reason: Mapped[str | None] = mapped_column(String(512))
