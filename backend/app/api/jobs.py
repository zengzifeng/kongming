from __future__ import annotations

from flask import Blueprint, request
from pydantic import BaseModel, Field

from ..schemas.common import model_to_dict
from ..services import JobScheduleService
from ..utils.response import success


bp = Blueprint("jobs", __name__)


class JobSchedulePatch(BaseModel):
    description: str | None = Field(default=None, max_length=256)
    trigger_type: str | None = None
    cron_expr: str | None = Field(default=None, max_length=64)
    interval_seconds: int | None = Field(default=None, gt=0)
    enabled: bool | None = None
    args_json: dict | None = None


@bp.get("/jobs")
def list_jobs():
    items = JobScheduleService().list()
    return success([model_to_dict(x) for x in items])


@bp.get("/jobs/<job_name>")
def get_job(job_name: str):
    schedule = JobScheduleService().get(job_name)
    return success(model_to_dict(schedule))


@bp.patch("/jobs/<job_name>")
def patch_job(job_name: str):
    payload = JobSchedulePatch(**(request.get_json(silent=True) or {}))
    schedule = JobScheduleService().update(
        job_name, payload.model_dump(exclude_unset=True))
    return success(model_to_dict(schedule))
