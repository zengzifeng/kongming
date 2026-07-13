from sqlalchemy import String, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class ProviderMapping(BaseModel):
    """客户×模型 到 provider/集群 的映射表。

    kingress 侧监控数据只给到 ai_consumer(客户) × ai_model(模型)，缺少 provider 与
    自建集群名；本表补全这层映射，供聚合到 customer_usage_hourly、以及资源看板关联
    自建集群时查询。同一(客户,模型)可能对应多个 provider（如多机型/多集群），故自然键
    含 provider。
    """

    __tablename__ = "provider_mappings"
    __table_args__ = (
        UniqueConstraint("customer_name", "model_name", "provider",
                         name="uq_provider_mapping"),
        Index("ix_provider_mapping_customer_model", "customer_name", "model_name"),
    )

    customer_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    cluster_name: Mapped[str | None] = mapped_column(String(64))  # 自建集群名，可空（部分无对应集群）
