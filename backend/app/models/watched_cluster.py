from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class WatchedCluster(BaseModel):
    __tablename__ = "watched_clusters"

    cluster_name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 该集群部署的模型（小写规范形，与需求/客户跑量的 model_name 一致）。
    # 拟合叠加按此列把「模型级叠加波形」归属到对应集群；缺省回退 cluster_name 小写形。
    deployed_model: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
