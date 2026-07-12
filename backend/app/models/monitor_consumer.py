from datetime import datetime
from sqlalchemy import String, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class MonitorConsumer(BaseModel):
    """客户主表 + kingress 采集清单（原 customers 表已合并进来）。

    ``ai_consumer`` 既是接口 query 参数用的原始消费者串，也等同于客户名称（唯一）；
    ``customer_code`` 为平台内客户编码，``customer_name`` 为展示名，``level`` 为客户分级。
    采集时逐 enabled 的 ai_consumer 请求 kingress 侧监控数据。usage/sell_discount/demand
    等表通过 monitor_consumers.id 外键关联本表。
    """

    __tablename__ = "monitor_consumers"

    ai_consumer: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    customer_code: Mapped[str | None] = mapped_column(String(64), index=True)
    customer_name: Mapped[str | None] = mapped_column(String(128))
    # 客户分级（原 customers.level 合并进来）：A/B/... 供看板与评估口径使用。
    level: Mapped[str] = mapped_column(String(8), default="B", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    note: Mapped[str | None] = mapped_column(String(512))
    last_collected_at: Mapped[datetime | None] = mapped_column()
