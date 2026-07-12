from datetime import datetime
from sqlalchemy import JSON, String, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class PolicyStatus:
    DRAFT = "draft"
    ACCEPTED = "accepted"
    CANCELLED = "cancelled"


class Policy(BaseModel):
    __tablename__ = "policies"

    policy_run_id: Mapped[int] = mapped_column(ForeignKey("policy_runs.id"), nullable=False, index=True)
    # 需求评估触发的策略绑定其 demand；NULL 表示人工/定时触发的全局策略，与单一客户需求无关。
    demand_id: Mapped[int | None] = mapped_column(ForeignKey("demands.id"), nullable=True, index=True)
    policy_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    algorithm: Mapped[str] = mapped_column(String(32), default="realtime")
    summary_json: Mapped[dict] = mapped_column(JSON, default=dict)
    expected_revenue_gain: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    expected_peak_shaving_gain: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    expected_off_peak_gain: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    constraints_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default=PolicyStatus.DRAFT, index=True)
    accepted_by: Mapped[str | None] = mapped_column(String(64))
    accepted_at: Mapped[datetime | None] = mapped_column()
    cancel_reason: Mapped[str | None] = mapped_column(String(512))
    effective_from: Mapped[datetime | None] = mapped_column()
    effective_to: Mapped[datetime | None] = mapped_column()
