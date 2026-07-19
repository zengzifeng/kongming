from datetime import datetime
from sqlalchemy import JSON, Boolean, String, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class WavePeriod:
    """波形拟合的时段维度：闲时 / 忙时。小时边界由 config.WAVE_FIT_BUSY_HOURS 统一定义。"""

    IDLE = "idle"
    BUSY = "busy"

    ALL = {IDLE, BUSY}


class FitLevel:
    """拟合波形粒度：客户级（单客户+模型）/ 集群级（同模型客户波形叠加）。"""

    CUSTOMER = "customer"
    CLUSTER = "cluster"

    ALL = {CUSTOMER, CLUSTER}


class FittingAlgorithm(BaseModel):
    """拟合算法注册表（主数据）：登记可选算法的名称、调用入口与默认参数。

    DB 管理，API 只读——有哪些算法可选不支持 API 修改，只能改库/seed。
    entry_ref：算法在 registry 中的注册键（如 "demo"），run 时据此取实现。
    """

    __tablename__ = "fitting_algorithms"

    algo_name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    description: Mapped[str] = mapped_column(String(512), default="")
    entry_ref: Mapped[str] = mapped_column(String(128), nullable=False)  # registry 注册键
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    default_params: Mapped[dict] = mapped_column(JSON, default=dict)


class CustomerFittingConfig(BaseModel):
    """客户+模型 → 拟合算法 的关联关系（含人工配置的算法输入参数）。

    管理粒度：每个客户及模型只配一条，拟合运行时同一配置同时产出闲时、忙时结果。
    params_json：人工配置的算法输入，如 {"delta_tpm": 增/减量}（正为增、负为减）。
    """

    __tablename__ = "customer_fitting_configs"
    __table_args__ = (
        UniqueConstraint(
            "customer_code", "model_name",
            name="uq_customer_fitting_natural_key",
        ),
        Index("ix_customer_fitting_consumer_model", "customer_code", "model_name"),
    )

    customer_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    period: Mapped[str] = mapped_column(String(16), nullable=False)  # idle / busy
    algo_name: Mapped[str] = mapped_column(String(64), nullable=False)
    params_json: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class FittingResult(BaseModel):
    """一次拟合产出的目标时段波形（落库，可审计/复用/被求解流程消费）。

    level=customer：单客户(customer_code)+模型+时段的拟合波形，algo_name 为该配置的拟合算法；
    level=cluster ：同一 deployed_model 下所有客户拟合波形按时间戳叠加后的集群波形，
                    是聚合结果、无拟合算法，algo_name 为 NULL。
    series_json：[[timestamp_iso, tpm], ...] 目标时段波形序列。
    """

    __tablename__ = "fitting_results"
    __table_args__ = (
        Index("ix_fitting_result_lookup", "level", "customer_code", "model_name", "period"),
        Index("ix_fitting_result_cluster", "level", "cluster_name", "model_name", "period"),
    )

    level: Mapped[str] = mapped_column(String(16), nullable=False)  # customer / cluster
    customer_code: Mapped[str | None] = mapped_column(String(64), index=True)
    cluster_name: Mapped[str | None] = mapped_column(String(64))
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    period: Mapped[str] = mapped_column(String(16), nullable=False)  # idle / busy
    algo_name: Mapped[str | None] = mapped_column(String(64))  # 客户级=拟合算法；集群级聚合=NULL
    generated_at: Mapped[datetime] = mapped_column(nullable=False, index=True)
    series_json: Mapped[list] = mapped_column(JSON, default=list)
    meta_json: Mapped[dict] = mapped_column(JSON, default=dict)
