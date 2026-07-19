from datetime import datetime
from sqlalchemy import String, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class MonitorConsumer(BaseModel):
    """客户主表 + kingress 采集清单（原 customers 表已合并进来）。

    一行 = (ai_consumer, customer_code)。``customer_code`` 即接口侧 user_id，是全局唯一的
    自然主键；``ai_consumer`` 为客户名（公司名），同一客户名可对应多个 user_id（占多行）。
    ``customer_name`` 为展示名，``level`` 为客户分级。采集时逐 enabled 行以
    ``user_id=customer_code`` 过滤请求 kingress 侧监控数据（per-user_id 粒度）。
    usage/sell_discount/demand 等表通过 monitor_consumers.id 外键关联本表。
    """

    __tablename__ = "monitor_consumers"

    # 客户名（公司名）：同一客户名可对应多个 user_id，故不再唯一，仅建索引便于按名查询/聚合。
    ai_consumer: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    # customer_code = 接口侧 user_id，全局唯一（自然主键），一行 = (ai_consumer, customer_code)。
    # 一个 ai_consumer 多 customer_code 时占多行；逐客户采集按此过滤（user_id=customer_code）。
    customer_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    customer_name: Mapped[str | None] = mapped_column(String(128))
    # 客户分级（原 customers.level 合并进来）：A/B/... 供看板与评估口径使用。
    level: Mapped[str] = mapped_column(String(8), default="B", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    note: Mapped[str | None] = mapped_column(String(512))
    last_collected_at: Mapped[datetime | None] = mapped_column()
