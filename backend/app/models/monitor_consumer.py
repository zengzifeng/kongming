from datetime import datetime
from sqlalchemy import String, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class MonitorConsumer(BaseModel):
    """客户拉取清单：采集时逐 ai_consumer 请求 kingress 侧监控数据的客户集合。

    维护方式（手动 + 按需求驱动）：初始阶段手动录入一批；之后有新客户需求就新增一条，
    客户不再有需求就停用/删除。``ai_consumer`` 是接口 query 参数用的原始消费者串，
    ``customer_code`` 关联平台内客户（可空，未关联时仅按 ai_consumer 采集）。
    """

    __tablename__ = "monitor_consumers"

    ai_consumer: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    customer_code: Mapped[str | None] = mapped_column(String(64), index=True)
    customer_name: Mapped[str | None] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    note: Mapped[str | None] = mapped_column(String(512))
    last_collected_at: Mapped[datetime | None] = mapped_column()
