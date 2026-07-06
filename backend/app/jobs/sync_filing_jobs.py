from ..services import SyncService
from .decorators import with_job_log


@with_job_log("sync_filings_hourly")
def sync_filings_hourly(app):
    return SyncService().run_sync(triggered_by="cron").id
