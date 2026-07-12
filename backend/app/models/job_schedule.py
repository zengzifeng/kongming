from datetime import datetime
from sqlalchemy import JSON, Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class JobTriggerType:
    CRON = "cron"
    INTERVAL = "interval"


class JobSchedule(BaseModel):
    """定时任务的可持久化配置：调度器启动时 seed 默认项并据此建任务，
    前端可通过 /api/v1/jobs 查询与修改（改 cron/interval/enabled），改动落库且对运行中调度器即时生效。

    cron_expr：5 段 crontab（分 时 日 月 周），trigger_type=cron 时使用。
    interval_seconds：间隔秒数，trigger_type=interval 时使用。
    args_json：预留给需要参数的任务（如 policy_auto_run 的 algorithm）。
    """

    __tablename__ = "job_schedules"

    job_name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(256), default="")
    trigger_type: Mapped[str] = mapped_column(String(16), default=JobTriggerType.CRON)
    cron_expr: Mapped[str | None] = mapped_column(String(64))
    interval_seconds: Mapped[int | None] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    args_json: Mapped[dict] = mapped_column(JSON, default=dict)
    last_run_at: Mapped[datetime | None] = mapped_column()
    next_run_at: Mapped[datetime | None] = mapped_column()
