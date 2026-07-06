from ..services import CustomerTrackingService, RevenueService
from .decorators import with_job_log


@with_job_log("revenue_after_snapshot")
def revenue_after_snapshot(app):
    return RevenueService().process_due_after_snapshots()


@with_job_log("customer_usage_daily")
def customer_usage_daily(app):
    return CustomerTrackingService().aggregate_daily()
