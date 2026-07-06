from sqlalchemy import JSON, String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class ApprovalLog(BaseModel):
    __tablename__ = "approval_logs"

    evaluation_id: Mapped[int] = mapped_column(ForeignKey("evaluations.id"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    operator: Mapped[str] = mapped_column(String(64), nullable=False)
    comment: Mapped[str | None] = mapped_column(String(1024))
    before_json: Mapped[dict] = mapped_column(JSON, default=dict)
    after_json: Mapped[dict] = mapped_column(JSON, default=dict)
