from pydantic import BaseModel, Field


class EvaluateRequest(BaseModel):
    force: bool = False


class ApproveRequest(BaseModel):
    operator: str = Field(min_length=1, max_length=64)
    comment: str | None = Field(default=None, max_length=1024)


class RejectRequest(BaseModel):
    operator: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=1024)
