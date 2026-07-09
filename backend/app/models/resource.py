from datetime import date
from sqlalchemy import JSON, String, Numeric, Integer
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class ClusterResource(BaseModel):
    """集群-模型部署粒度的资源快照。

    每行表示某个集群当前承载某个部署模型的承接能力与冗余情况，按日落表。
    """

    __tablename__ = "cluster_resources"

    snapshot_date: Mapped[date] = mapped_column(nullable=False, index=True)

    cluster_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    deployed_model: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    primary_customer: Mapped[str | None] = mapped_column(String(128))

    machine_count: Mapped[int] = mapped_column(Integer, default=0)
    tpm_per_machine: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    total_capacity_tpm: Mapped[float] = mapped_column(Numeric(18, 2), default=0)

    peak_tpm_d1_23_24: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    peak_tpm_d2_23_24: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    peak_tpm_d3_23_24: Mapped[float] = mapped_column(Numeric(18, 2), default=0)

    peak_tpm_idle: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    idle_redundant_tpm: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    idle_redundant_machines: Mapped[int] = mapped_column(Integer, default=0)

    peak_tpm_busy: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    busy_redundant_tpm: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    busy_redundant_machines: Mapped[int] = mapped_column(Integer, default=0)

    current_tpm: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    current_redundant_tpm: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    # 当前冗余台数（可供出机器数，录入「自建集群冗余台数」）。求解器 _donatable_machines 的正典键，
    # 与 current_redundant_tpm 配对；缺省时求解器回退 busy_redundant_machines。
    current_redundant_machines: Mapped[int] = mapped_column(Integer, default=0)

    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)
