from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class PolicyRunCreate(BaseModel):
    algorithm: str = Field(default="realtime")
    demand_ids: list[int] | None = None
    params: dict | None = None


class PolicyAcceptRequest(BaseModel):
    operator: str = Field(min_length=1, max_length=64)
    effective_from: datetime | None = None
    comment: str | None = Field(default=None, max_length=1024)


class PolicyRecalculateRequest(BaseModel):
    params: dict | None = None


class PolicyCancelRequest(BaseModel):
    operator: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=1024)


class PolicyPatchRequest(BaseModel):
    summary_json: dict | None = None
    constraints_json: dict | None = None
    expected_revenue_gain: float | None = None
    expected_peak_shaving_gain: float | None = None
    expected_off_peak_gain: float | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
