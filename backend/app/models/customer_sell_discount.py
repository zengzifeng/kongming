from datetime import date
from sqlalchemy import String, ForeignKey, Numeric, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class CustomerSellDiscount(BaseModel):
    """客户售卖折扣主数据：来源于「平台输入.售卖」sheet。

    一条记录表示某客户在某模型上的售卖折扣（长期定价主数据），与
    ``model_list_prices``（列表价）、``vendor_quotas.purchase_discount``（采购折扣）
    并列，用于售卖侧收入测算。

    注意与 ``demands.discount_rate`` 区分：后者是"某张需求报备单"的随单折扣，
    带生命周期状态；本表是客户×模型的售卖折扣主数据。
    """

    __tablename__ = "customer_sell_discounts"
    __table_args__ = (
        UniqueConstraint("customer_id", "model_name", "effective_from",
                         name="uq_sell_discount_customer_model_effective"),
        Index("ix_sell_discount_model", "model_name"),
    )

    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    customer_name: Mapped[str] = mapped_column(String(128), nullable=False)  # 冗余客户名，便于追溯
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)      # 模型名称
    sell_discount: Mapped[float] = mapped_column(Numeric(6, 4), default=0)   # 售卖折扣
    effective_from: Mapped[date] = mapped_column(nullable=False)             # 生效日
    effective_to: Mapped[date | None] = mapped_column()
