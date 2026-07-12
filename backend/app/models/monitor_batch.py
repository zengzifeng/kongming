from datetime import datetime
from sqlalchemy import JSON, String, Integer
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class MonitorBatchStatus:
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class MonitorBatch(BaseModel):
    """资源模型监控数据的一次采集批次。

    一次采集 = 全局拉一次 token 侧（集群/GPU 产能，与客户无关）+ 逐 ai_consumer 拉一次
    kingress 侧（客户×售卖模型的瞬时 TPM）。窗口口径记录在 window_start/window_end。
    """

    __tablename__ = "monitor_batches"

    batch_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    triggered_by: Mapped[str] = mapped_column(String(16), default="cron")
    window_start: Mapped[datetime | None] = mapped_column()
    window_end: Mapped[datetime | None] = mapped_column()
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column()

    consumers_total: Mapped[int] = mapped_column(Integer, default=0)   # 计划拉取的客户数
    consumers_ok: Mapped[int] = mapped_column(Integer, default=0)      # 成功拉取的客户数
    cluster_rows: Mapped[int] = mapped_column(Integer, default=0)      # 落库集群瞬时行数
    consumer_rows: Mapped[int] = mapped_column(Integer, default=0)     # 落库客户瞬时行数

    status: Mapped[str] = mapped_column(String(16), default=MonitorBatchStatus.RUNNING, index=True)
    error_message: Mapped[str | None] = mapped_column(String(2048))
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)
