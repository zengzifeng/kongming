from datetime import date, datetime
from sqlalchemy import (
    String,
    ForeignKey,
    Numeric,
    BigInteger,
    Integer,
    DateTime,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class CustomerUsageHourly(BaseModel):
    """时序跑量明细：来源于「模型计量使用量明细」导出，按 timestamp（数据时间）存储的原始跑量。

    与 ``customer_usage_daily``（按天聚合的收入/成本口径）区分：本表保留最细粒度的
    带时间戳跑量，供后续聚合、时段分析与算法回溯使用。
    """

    __tablename__ = "customer_usage_hourly"
    __table_args__ = (
        UniqueConstraint(
            "customer_id",
            "user_id",
            "key_id",
            "data_time",
            "stat_date",
            "model",
            "provider",
            "phase",
            name="uq_usage_hourly_natural_key",
        ),
        Index("ix_usage_hourly_customer_time", "customer_id", "data_time"),
        Index("ix_usage_hourly_stat_date", "stat_date"),
    )

    # 归属客户（FK -> customers），并冗余客户名以便追溯原始导出
    customer_id: Mapped[int] = mapped_column(ForeignKey("monitor_consumers.id"), nullable=False)
    customer_name: Mapped[str] = mapped_column(String(128), nullable=False)

    # 账号维度
    user_id: Mapped[str] = mapped_column(String(32), nullable=False)   # 用户ID
    key_id: Mapped[str] = mapped_column(String(64), nullable=False)    # key_id

    # 时间维度
    data_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)  # 数据时间（timestamp）
    stat_date: Mapped[date] = mapped_column(nullable=False)                # 日期（结算日）

    # 业务维度
    phase: Mapped[str] = mapped_column(String(16), nullable=False)     # 阶段 p0/p1/p2/...
    model: Mapped[str] = mapped_column(String(64), nullable=False)     # 模型
    provider: Mapped[str] = mapped_column(String(64), nullable=False)  # provider
    model_source: Mapped[str | None] = mapped_column(String(16))       # 模型来源 第三方/自建
    data_source: Mapped[str | None] = mapped_column(String(16))        # 数据来源 生产/测试

    # 跑量指标（token）
    output_token: Mapped[int] = mapped_column(BigInteger, default=0)              # outputToken
    cache_token: Mapped[int] = mapped_column(BigInteger, default=0)              # cacheToken
    cache_miss_token: Mapped[int] = mapped_column(BigInteger, default=0)         # cacheMissToken
    total_input: Mapped[int] = mapped_column(BigInteger, default=0)              # 总输入
    input_output: Mapped[int] = mapped_column(BigInteger, default=0)            # 输入+输出
    creation_cache_1h_token: Mapped[int] = mapped_column(BigInteger, default=0)  # creationCache1hToken
    creation_cache_5m_token: Mapped[int] = mapped_column(BigInteger, default=0)  # creationCache5mToken
    web_search_fc_count: Mapped[int] = mapped_column(Integer, default=0)         # webSearchFcCount
    av_duration: Mapped[float] = mapped_column(Numeric(18, 4), default=0)        # 音视频时长

    # 商务维度
    status: Mapped[str | None] = mapped_column(String(32))          # 状态
    account_type: Mapped[str | None] = mapped_column(String(16))   # 账户类型 内部/企业
    department: Mapped[str | None] = mapped_column(String(255))    # 部门
    business_owner: Mapped[str | None] = mapped_column(String(64))  # 商务负责人
    industry: Mapped[str | None] = mapped_column(String(64))       # 行业
