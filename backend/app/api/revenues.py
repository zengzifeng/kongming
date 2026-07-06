from __future__ import annotations

from datetime import date

from flask import Blueprint, request

from ..extensions import db
from ..repositories import (
    AlertRepository,
    CustomerUsageRepository,
    MetricSnapshotRepository,
    RevenueAttributionRepository,
)
from ..schemas.common import model_to_dict
from ..schemas.revenue_schema import AlertPatch, RevenueAnalysisArchiveRequest
from ..services import CustomerTrackingService, PolicyService, RevenueAnalysisService
from ..services.alert_service import AlertService
from ..utils.errors import NotFound, ValidationFailed
from ..utils.pagination import parse_pagination
from ..utils.response import paginated, success


bp = Blueprint("revenues", __name__)


@bp.get("/revenue/attributions")
def list_attributions():
    page, page_size = parse_pagination()
    items, total = RevenueAttributionRepository().list(
        policy_id=request.args.get("policy_id", type=int),
        mechanism=request.args.get("mechanism"),
        project_code=request.args.get("project_code"),
        page=page, page_size=page_size,
    )
    return paginated([model_to_dict(a) for a in items], page, page_size, total)


@bp.get("/revenue/analysis")
def revenue_analysis():
    return success(RevenueAnalysisService().analysis())


@bp.post("/revenue/analysis/<int:policy_id>/archive")
def archive_revenue_analysis(policy_id: int):
    payload = RevenueAnalysisArchiveRequest(
        **(request.get_json(silent=True) or {}))
    data = RevenueAnalysisService().archive(
        policy_id, operator=payload.operator, reason=payload.reason)
    db.session.commit()
    return success(data)


@bp.get("/revenue/policies/<int:policy_id>")
def policy_revenue(policy_id: int):
    policy = PolicyService().get_policy(policy_id)
    snapshots = MetricSnapshotRepository().for_policy(policy_id)
    attributions = RevenueAttributionRepository().for_policy(policy_id)
    analysis_items = RevenueAnalysisService().analysis().get("items", [])
    analysis = next((item for item in analysis_items if item.get(
        "policy_id") == policy_id), None)
    return success({
        "policy_id": policy_id,
        "policy": model_to_dict(policy),
        "snapshots": [model_to_dict(s) for s in snapshots],
        "attributions": [model_to_dict(a) for a in attributions],
        "analysis": analysis,
    })


@bp.get("/customers/<int:customer_id>/usage")
def customer_usage(customer_id: int):
    granularity = request.args.get("granularity", "day")
    if granularity != "day":
        # V1 仅日聚合
        raise ValidationFailed("V1 仅支持 granularity=day", details={
                               "granularity": granularity})

    from datetime import datetime

    def parse(arg):
        v = request.args.get(arg)
        if not v:
            return None
        try:
            return date.fromisoformat(v)
        except ValueError as e:
            raise ValidationFailed(
                f"参数 {arg} 不是合法日期", details={"value": v}) from e

    rows = CustomerUsageRepository().for_customer(
        customer_id, start=parse("from"), end=parse("to"),
    )
    return success({"items": [model_to_dict(r) for r in rows]})


@bp.get("/customer-demands/<report_id>/tracking")
def report_tracking(report_id: str):
    return success(CustomerTrackingService().tracking_for_report(report_id))


@bp.get("/alerts")
def list_alerts():
    page, page_size = parse_pagination()
    items, total = AlertRepository().list(
        status=request.args.get("status"),
        severity=request.args.get("severity"),
        alert_type=request.args.get("type"),
        page=page, page_size=page_size,
    )
    return paginated([model_to_dict(a) for a in items], page, page_size, total)


@bp.patch("/alerts/<int:alert_id>")
def patch_alert(alert_id: int):
    payload = AlertPatch(**(request.get_json(silent=True) or {}))
    alert = AlertService().patch(
        alert_id, action=payload.action, operator=payload.operator)
    db.session.commit()
    return success(model_to_dict(alert))
