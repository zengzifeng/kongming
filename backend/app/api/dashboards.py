from flask import Blueprint, request

from ..extensions import db
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


@bp.patch("/dashboard/resources/clusters")
def update_cluster_resource():
    payload = request.get_json(silent=True) or {}
    data = DashboardService().update_cluster_tpm_per_machine(
        cluster_name=str(payload.get("cluster_name") or ""),
        deployed_model=str(payload.get("deployed_model") or ""),
        tpm_per_machine_w=float(payload.get("tpm_per_machine_w") or 0),
        machine_count=int(payload["machine_count"]) if payload.get("machine_count") is not None else None,
        current_tpm_w=float(payload["current_tpm_w"]) if payload.get("current_tpm_w") is not None else None,
        provider=str(payload.get("provider") or ""),
    )
    db.session.commit()
    return success(data)


@bp.get("/reports/weekly")
def weekly():
    return success(ReportService().weekly(week=request.args.get("week")))


@bp.get("/reports/monthly")
def monthly():
    return success(ReportService().monthly(month=request.args.get("month")))
