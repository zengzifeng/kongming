from datetime import datetime
from sqlalchemy import JSON, String, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class VendorStatus:
    ACTIVE = "active"
    INACTIVE = "inactive"


class VendorQuota(BaseModel):
    """三方供应商在特定模型上的配额与价格主数据。

    一条记录表示某 vendor 在某 model 上、在 [effective_from, effective_to)
    时间段内的承接额度与单价。允许按时间段维护历史价位，便于回溯归因。
    """

    __tablename__ = "vendor_quotas"
    __table_args__ = (
        UniqueConstraint("vendor", "model", "effective_from",
                         name="uq_vendor_model_effective"),
    )

    vendor: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    quota_tpm: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    unit_cost: Mapped[float] = mapped_column(Numeric(12, 6), default=0)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 6), default=0)
    effective_from: Mapped[datetime] = mapped_column(nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(16), default=VendorStatus.ACTIVE,
                                        nullable=False, index=True)
    contact: Mapped[str | None] = mapped_column(String(128))
    notes: Mapped[str | None] = mapped_column(String(512))
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)
