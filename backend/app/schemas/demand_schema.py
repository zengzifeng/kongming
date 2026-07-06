from datetime import datetime
from pydantic import BaseModel, Field


class DemandPatch(BaseModel):
    status: str | None = None
    expected_start_at: datetime | None = None
    expected_end_at: datetime | None = None
    extra: dict | None = None


class SyncTriggerRequest(BaseModel):
    reason: str = Field(default="manual", max_length=128)
