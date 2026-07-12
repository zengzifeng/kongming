from sqlalchemy import JSON, String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class PolicyAuditAction:
    ACCEPT = "accept"
    PATCH = "patch"
    CANCEL = "cancel"
    RECALCULATE = "recalculate"


class PolicyAuditLog(BaseModel):
    """策略操作审计：accept/patch/cancel/recalculate 各留一条前后镜像。

    与 ApprovalLog（外键绑 evaluation，服务于需求评估线）平行、互不干扰。
    recalculate 记在旧策略上，after_json 指向新 run/policy 便于追溯血缘。
    """

    __tablename__ = "policy_audit_logs"

    policy_id: Mapped[int] = mapped_column(ForeignKey("policies.id"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    operator: Mapped[str] = mapped_column(String(64), nullable=False)
    comment: Mapped[str | None] = mapped_column(String(1024))
    before_json: Mapped[dict] = mapped_column(JSON, default=dict)
    after_json: Mapped[dict] = mapped_column(JSON, default=dict)
