from sqlalchemy import JSON, String, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class PolicyAction(BaseModel):
    __tablename__ = "policy_actions"

    policy_id: Mapped[int] = mapped_column(ForeignKey("policies.id"), nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    expected_gain: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
