from __future__ import annotations

from apscheduler.triggers.cron import CronTrigger

from ..extensions import db
from ..models import JobSchedule, JobTriggerType
from ..utils.errors import NotFound, ValidationFailed


class JobScheduleService:
    """定时任务配置的查询与修改。改动落库，并对运行中的调度器即时生效
    （拿不到运行中调度器时仅落库，下次启动时读取生效）。
    """

    def list(self) -> list[JobSchedule]:
        return list(
            db.session.execute(db.select(JobSchedule).order_by(JobSchedule.id.asc())).scalars()
        )

    def get(self, job_name: str) -> JobSchedule:
        schedule = db.session.execute(
            db.select(JobSchedule).where(JobSchedule.job_name == job_name)
        ).scalar_one_or_none()
        if not schedule:
            raise NotFound("定时任务不存在", details={"job_name": job_name})
        return schedule

    def update(self, job_name: str, patch: dict) -> JobSchedule:
        schedule = self.get(job_name)

        trigger_type = patch.get("trigger_type", schedule.trigger_type)
        cron_expr = patch.get("cron_expr", schedule.cron_expr)
        interval_seconds = patch.get("interval_seconds", schedule.interval_seconds)
        self._validate_trigger(trigger_type, cron_expr, interval_seconds)

        for key in ("description", "trigger_type", "cron_expr", "interval_seconds",
                    "enabled", "args_json"):
            if key in patch and patch[key] is not None:
                setattr(schedule, key, patch[key])
        db.session.flush()

        self._apply_to_running(schedule)
        db.session.commit()
        return schedule

    @staticmethod
    def _validate_trigger(trigger_type: str, cron_expr, interval_seconds) -> None:
        if trigger_type == JobTriggerType.INTERVAL:
            if not interval_seconds or int(interval_seconds) <= 0:
                raise ValidationFailed("interval 触发需要正整数 interval_seconds")
        elif trigger_type == JobTriggerType.CRON:
            if not cron_expr:
                raise ValidationFailed("cron 触发需要 cron_expr")
            try:
                CronTrigger.from_crontab(cron_expr)
            except Exception as exc:  # noqa: BLE001
                raise ValidationFailed(f"cron_expr 非法: {exc}")
        else:
            raise ValidationFailed(
                "未知 trigger_type", details={"allowed": ["cron", "interval"]})

    @staticmethod
    def _apply_to_running(schedule: JobSchedule) -> None:
        # 延迟导入避免与 scheduler 模块循环依赖。
        from ..jobs.scheduler import add_job_from_schedule, get_scheduler
        from flask import current_app

        scheduler = get_scheduler()
        if scheduler is None or not scheduler.running:
            return
        add_job_from_schedule(scheduler, current_app._get_current_object(), schedule)
