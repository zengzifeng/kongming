from datetime import datetime
from sqlalchemy import JSON, String, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class Customer(BaseModel):
    __tablename__ = "customers"

    customer_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    level: Mapped[str] = mapped_column(String(8), default="B", nullable=False)
    strategic_tag: Mapped[str | None] = mapped_column(String(64))
    paid_amount_total: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    signed_at: Mapped[datetime | None] = mapped_column()
    extra_json: Mapped[dict] = mapped_column(JSON, default=dict)
