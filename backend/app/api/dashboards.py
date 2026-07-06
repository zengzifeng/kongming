from flask import Blueprint, request

from ..services import DashboardService, ReportService
from ..utils.response import success


bp = Blueprint("dashboards", __name__)


@bp.get("/dashboard/operations")
def operations():
    return success(DashboardService().operations())


@bp.get("/dashboard/customers")
def customers():
    customer_id = request.args.get("customer_id", type=int)
    return success(DashboardService().customers(customer_id))


@bp.get("/dashboard/management")
def management():
    return success(DashboardService().management(range=request.args.get("range", "7d")))


@bp.get("/dashboard/resources")
def resources():
    return success(DashboardService().resources(
        cluster_name=request.args.get("cluster_name"),
        deployed_model=request.args.get("deployed_model"),
        gpu_model=request.args.get("gpu_model"),
        datacenter=request.args.get("datacenter"),
    ))


@bp.get("/reports/weekly")
def weekly():
    return success(ReportService().weekly(week=request.args.get("week")))


@bp.get("/reports/monthly")
def monthly():
    return success(ReportService().monthly(month=request.args.get("month")))
