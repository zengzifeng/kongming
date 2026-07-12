from datetime import datetime
from sqlalchemy import ForeignKey, String, Numeric, Integer, DateTime, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class ClusterModelTpm(BaseModel):
    """token 侧集群瞬时产能快照（每分钟 × 部署模型/集群）。

    口径：token 服务的 inference_model 即集群名（cluster_name），与客户无关的全局产能。
    tpm/tpm_per_machine 已从接口的「万」还原为原始 TPM（×10000）。
    """

    __tablename__ = "cluster_model_tpm"
    __table_args__ = (
        UniqueConstraint("batch_id", "cluster_name", "data_time",
                         name="uq_cluster_model_tpm"),
        Index("ix_cluster_model_tpm_cluster_time", "cluster_name", "data_time"),
    )

    batch_id: Mapped[int] = mapped_column(ForeignKey("monitor_batches.id"), nullable=False, index=True)
    data_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    cluster_name: Mapped[str] = mapped_column(String(64), nullable=False)  # = inference_model
    tpm: Mapped[float] = mapped_column(Numeric(20, 2), default=0)          # token_cluster_tpm ×10000
    node_count: Mapped[int] = mapped_column(Integer, default=0)            # token_node_count
    node_avg_tpm: Mapped[float] = mapped_column(Numeric(20, 2), default=0)  # token_node_avg_tpm ×10000
