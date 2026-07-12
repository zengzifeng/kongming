from datetime import datetime
from sqlalchemy import ForeignKey, String, Integer, DateTime, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class GpuNodeCount(BaseModel):
    """token 侧 GPU 加速卡台数瞬时快照（每分钟 × 加速卡型号）。

    口径：token_gpu_node_count，按 label_accelerator 聚合，是全局台数、无法拆到单模型，
    因此独立成表（不并入 cluster_model_tpm）。
    """

    __tablename__ = "gpu_node_count"
    __table_args__ = (
        UniqueConstraint("batch_id", "accelerator", "data_time",
                         name="uq_gpu_node_count"),
        Index("ix_gpu_node_count_acc_time", "accelerator", "data_time"),
    )

    batch_id: Mapped[int] = mapped_column(ForeignKey("monitor_batches.id"), nullable=False, index=True)
    data_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    accelerator: Mapped[str] = mapped_column(String(64), nullable=False)  # label_accelerator
    node_count: Mapped[int] = mapped_column(Integer, default=0)
