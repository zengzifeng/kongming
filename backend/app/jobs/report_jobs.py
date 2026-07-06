from ..services import ReportService
from .decorators import with_job_log


@with_job_log("weekly_report")
def weekly_report(app):
    return ReportService().weekly()


@with_job_log("monthly_report")
def monthly_report(app):
    return ReportService().monthly()
