from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class PolicyRunCreate(BaseModel):
    algorithm: str = Field(default="realtime")
    demand_ids: list[int] | None = None
    # 需求评估触发时传入，绑定产出策略到该 demand；不传=人工触发的全局策略。
    demand_id: int | None = None
    params: dict | None = None


class PolicyAcceptRequest(BaseModel):
    operator: str = Field(min_length=1, max_length=64)
    effective_from: datetime | None = None
    comment: str | None = Field(default=None, max_length=1024)


class PolicyRecalculateRequest(BaseModel):
    operator: str = Field(default="system", min_length=1, max_length=64)
    params: dict | None = None


class PolicyCancelRequest(BaseModel):
    operator: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=1024)


class PolicyPatchRequest(BaseModel):
    operator: str = Field(default="system", min_length=1, max_length=64)
    summary_json: dict | None = None
    constraints_json: dict | None = None
    expected_revenue_gain: float | None = None
    expected_peak_shaving_gain: float | None = None
    expected_off_peak_gain: float | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
