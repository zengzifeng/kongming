from datetime import datetime
from sqlalchemy import ForeignKey, String, Numeric, DateTime, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class ConsumerModelTpm(BaseModel):
    """kingress 侧客户瞬时跑量快照（每分钟 × 客户 × 售卖模型）。

    瞬时 TPM 口径（不是累计 token —— 累计 token 属收益计算）。客户由采集时请求的
    ai_consumer 标定（写入 ai_consumer/customer_code），售卖模型取 series.labels.ai_model。
    自建/第三方占比、平均输入输出 token、缓存命中率随同一时间点一并落库，供切量策略消费。
    """

    __tablename__ = "consumer_model_tpm"
    __table_args__ = (
        UniqueConstraint("batch_id", "ai_consumer", "ai_model", "data_time",
                         name="uq_consumer_model_tpm"),
        Index("ix_consumer_model_tpm_consumer_time", "ai_consumer", "data_time"),
        Index("ix_consumer_model_tpm_model_time", "ai_model", "data_time"),
    )

    batch_id: Mapped[int] = mapped_column(ForeignKey("monitor_batches.id"), nullable=False, index=True)
    data_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    ai_consumer: Mapped[str] = mapped_column(String(128), nullable=False)  # 采集时的消费者标识
    customer_code: Mapped[str | None] = mapped_column(String(64), index=True)
    ai_model: Mapped[str] = mapped_column(String(64), nullable=False)      # 售卖模型名

    tpm: Mapped[float] = mapped_column(Numeric(20, 2), default=0)                 # kingress_model_tpm
    self_ratio: Mapped[float | None] = mapped_column(Numeric(6, 2))               # kingress_ksyun_ratio %
    thirdparty_ratio: Mapped[float | None] = mapped_column(Numeric(6, 2))         # kingress_thirdparty_ratio %
    avg_input_token: Mapped[float | None] = mapped_column(Numeric(20, 4))         # kingress_avg_input_token
    avg_output_token: Mapped[float | None] = mapped_column(Numeric(20, 4))        # kingress_avg_output_token
    cache_hit_rate: Mapped[float | None] = mapped_column(Numeric(6, 2))           # kingress_cache_hit_rate %
