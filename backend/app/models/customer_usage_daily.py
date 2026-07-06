from datetime import date
from sqlalchemy import String, ForeignKey, Numeric, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class CustomerUsageDaily(BaseModel):
    __tablename__ = "customer_usage_daily"
    __table_args__ = (
        UniqueConstraint("customer_id", "report_id", "stat_date", name="uq_usage_customer_report_date"),
        Index("ix_usage_customer_date", "customer_id", "stat_date"),
    )

    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    report_id: Mapped[str] = mapped_column(String(64), nullable=False)
    stat_date: Mapped[date] = mapped_column(nullable=False)
    expected_tpm: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    actual_tpm: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    achievement_rate: Mapped[float] = mapped_column(Numeric(8, 4), default=0)
    revenue: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    cost_self: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    cost_vendor: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    margin: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
