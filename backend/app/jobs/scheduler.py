from apscheduler.schedulers.background import BackgroundScheduler

from .revenue_jobs import customer_usage_daily, revenue_after_snapshot
from .report_jobs import monthly_report, weekly_report
from .sync_filing_jobs import sync_filings_hourly


_scheduler: BackgroundScheduler | None = None


def start_scheduler(app):
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")

    scheduler.add_job(sync_filings_hourly, "cron", minute=0, args=[app], id="sync_filings_hourly",
                      replace_existing=True, max_instances=1, coalesce=True)
    scheduler.add_job(revenue_after_snapshot, "interval", minutes=1, args=[app],
                      id="revenue_after_snapshot", replace_existing=True, max_instances=1, coalesce=True)
    scheduler.add_job(customer_usage_daily, "cron", hour=1, minute=15, args=[app],
                      id="customer_usage_daily", replace_existing=True, max_instances=1, coalesce=True)
    scheduler.add_job(weekly_report, "cron", day_of_week="mon", hour=8, minute=0, args=[app],
                      id="weekly_report", replace_existing=True)
    scheduler.add_job(monthly_report, "cron", day=1, hour=8, minute=0, args=[app],
                      id="monthly_report", replace_existing=True)

    scheduler.start()
    _scheduler = scheduler
    app.logger.info("Scheduler started with jobs: %s", [j.id for j in scheduler.get_jobs()])

    import atexit
    atexit.register(lambda: scheduler.shutdown(wait=False))
    return scheduler
