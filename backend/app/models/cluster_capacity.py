from sqlalchemy import String, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class ClusterCapacity(BaseModel):
    """自建集群单机承接能力（前端手动录入）。

    cluster_resources 表废弃后，唯一无法从监控数据（cluster_model_tpm）得到的
    「单机承接能力 TPM」由本表维护；总承接能力 = 台数(node_count) × tpm_per_machine
    在组装资源快照时实时计算。cluster_name 大小写不敏感匹配（存 lower）。
    """

    __tablename__ = "cluster_capacities"

    cluster_name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    tpm_per_machine: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
