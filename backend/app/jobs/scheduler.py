from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .revenue_jobs import customer_usage_daily, revenue_after_snapshot
from .report_jobs import monthly_report, weekly_report
from .sync_filing_jobs import sync_filings_hourly
from .policy_jobs import policy_auto_run
from .monitor_jobs import resource_monitor_collect, usage_hourly_aggregate


# 任务名 -> 可调用（均接受 app 作为首参；额外参数由 job_schedules.args_json 提供）。
JOB_REGISTRY = {
    "sync_filings_hourly": sync_filings_hourly,
    "revenue_after_snapshot": revenue_after_snapshot,
    "customer_usage_daily": customer_usage_daily,
    "weekly_report": weekly_report,
    "monthly_report": monthly_report,
    "policy_auto_run": policy_auto_run,
    "resource_monitor_collect": resource_monitor_collect,
    "usage_hourly_aggregate": usage_hourly_aggregate,
}

# 默认调度配置：首次启动时 seed 到 job_schedules 表（幂等，不覆盖已存在项）。
# cron_expr 为 5 段 crontab（分 时 日 月 周）。
DEFAULT_SCHEDULES = [
    {"job_name": "sync_filings_hourly", "description": "每小时同步报备平台",
     "trigger_type": "cron", "cron_expr": "0 * * * *"},
    {"job_name": "revenue_after_snapshot", "description": "采纳后收益快照补采与归因",
     "trigger_type": "interval", "interval_seconds": 60},
    {"job_name": "customer_usage_daily", "description": "客户用量日聚合",
     "trigger_type": "cron", "cron_expr": "15 1 * * *"},
    {"job_name": "weekly_report", "description": "周报",
     "trigger_type": "cron", "cron_expr": "0 8 * * 1"},
    {"job_name": "monthly_report", "description": "月报",
     "trigger_type": "cron", "cron_expr": "0 8 1 * *"},
    {"job_name": "policy_auto_run", "description": "后台定时策略测算（time_period，每天）",
     "trigger_type": "cron", "cron_expr": "30 2 * * *",
     "args_json": {"algorithm": "time_period"}},
    {"job_name": "resource_monitor_collect", "description": "资源模型监控数据采集（每小时）",
     "trigger_type": "cron", "cron_expr": "5 * * * *"},
    {"job_name": "usage_hourly_aggregate", "description": "consumer_model_tpm 小时聚合写入 usage_hourly",
     "trigger_type": "cron", "cron_expr": "10 * * * *"},
]


_scheduler: BackgroundScheduler | None = None


def get_scheduler() -> BackgroundScheduler | None:
    """返回当前运行中的调度器（供 JobScheduleService 即时 reschedule/pause/resume）。"""
    return _scheduler


def _seed_defaults(app):
    """把 DEFAULT_SCHEDULES 幂等写入 job_schedules 表（已存在的 job_name 跳过，保留用户改动）。"""
    from ..extensions import db
    from ..models import JobSchedule

    existing = {
        s.job_name
        for s in db.session.execute(db.select(JobSchedule)).scalars()
    }
    added = False
    for cfg in DEFAULT_SCHEDULES:
        if cfg["job_name"] in existing:
            continue
        db.session.add(JobSchedule(
            job_name=cfg["job_name"],
            description=cfg.get("description", ""),
            trigger_type=cfg["trigger_type"],
            cron_expr=cfg.get("cron_expr"),
            interval_seconds=cfg.get("interval_seconds"),
            enabled=cfg.get("enabled", True),
            args_json=cfg.get("args_json", {}),
        ))
        added = True
    if added:
        db.session.commit()


def ensure_default_schedules(app):
    """在 app 上下文内幂等 seed 默认任务配置。create_app 调用（即使调度器线程未启动，
    前端仍可通过 /api/v1/jobs 管理任务）；start_scheduler 也会调用（幂等）。"""
    with app.app_context():
        _seed_defaults(app)



def build_trigger(schedule):
    """由 JobSchedule 记录构造 APScheduler 触发器。"""
    if schedule.trigger_type == "interval":
        return IntervalTrigger(seconds=int(schedule.interval_seconds or 60),
                               timezone="Asia/Shanghai")
    return CronTrigger.from_crontab(schedule.cron_expr or "0 * * * *",
                                    timezone="Asia/Shanghai")


def add_job_from_schedule(scheduler: BackgroundScheduler, app, schedule) -> None:
    """按一条 JobSchedule 注册/替换任务；enabled=False 则移除已存在任务。"""
    func = JOB_REGISTRY.get(schedule.job_name)
    if func is None:
        app.logger.warning("未知任务名，跳过调度: %s", schedule.job_name)
        return
    if not schedule.enabled:
        if scheduler.get_job(schedule.job_name):
            scheduler.remove_job(schedule.job_name)
        return
    kwargs = dict(schedule.args_json or {})
    scheduler.add_job(
        func, build_trigger(schedule), args=[app], kwargs=kwargs,
        id=schedule.job_name, replace_existing=True, max_instances=1, coalesce=True,
    )


def start_scheduler(app):
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler

    from ..extensions import db
    from ..models import JobSchedule

    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")

    with app.app_context():
        _seed_defaults(app)
        schedules = list(db.session.execute(db.select(JobSchedule)).scalars())
        for schedule in schedules:
            add_job_from_schedule(scheduler, app, schedule)

    scheduler.start()
    _scheduler = scheduler
    app.logger.info("Scheduler started with jobs: %s", [j.id for j in scheduler.get_jobs()])

    import atexit
    atexit.register(lambda: scheduler.shutdown(wait=False))
    return scheduler
