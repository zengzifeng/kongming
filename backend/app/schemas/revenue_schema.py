from pydantic import BaseModel, Field


class AlertPatch(BaseModel):
    action: str = Field(pattern="^(ack|close)$")
    operator: str | None = Field(default=None, max_length=64)


class RevenueAnalysisArchiveRequest(BaseModel):
    operator: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=1024)
