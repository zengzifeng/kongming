from __future__ import annotations

from flask import Blueprint, request

from ..extensions import db
from ..models import PolicyAuditLog
from ..repositories import PolicyRepository, PolicyRunRepository
from ..schemas.common import model_to_dict
from ..schemas.policy_schema import (
    PolicyAcceptRequest,
    PolicyCancelRequest,
    PolicyPatchRequest,
    PolicyRecalculateRequest,
    PolicyRunCreate,
)
from ..services import PolicyService
from ..services.policy_report_service import PolicyReportService
from ..utils.errors import NotFound
from ..utils.pagination import parse_pagination
from ..utils.response import paginated, success


bp = Blueprint("policies", __name__)


@bp.post("/policy-runs")
def create_policy_run():
    payload = PolicyRunCreate(**(request.get_json(silent=True) or {}))
    run = PolicyService().submit_run(
        algorithm=payload.algorithm,
        demand_ids=payload.demand_ids,
        params=payload.params,
        triggered_by="manual",
        demand_id=payload.demand_id,
    )
    db.session.commit()
    return success(model_to_dict(run, exclude={"input_snapshot_json"}), status=202)


@bp.get("/policy-runs")
def list_runs():
    page, page_size = parse_pagination()
    status = request.args.get("status")
    algorithm = request.args.get("algorithm")
    items, total = PolicyRunRepository().list(
        status=status, algorithm=algorithm, page=page, page_size=page_size,
    )
    return paginated(
        [model_to_dict(r, exclude={"input_snapshot_json"}) for r in items],
        page, page_size, total,
    )


@bp.get("/policy-runs/<int:run_id>")
def get_run(run_id: int):
    run = PolicyService().get_run(run_id)
    return success(model_to_dict(run, exclude={"input_snapshot_json"}))


@bp.get("/policy-runs/<int:run_id>/snapshot")
def get_run_snapshot(run_id: int):
    run = PolicyService().get_run(run_id)
    snapshot = run.input_snapshot_json or {}
    return success({
        "input_snapshot": snapshot,
        "input_hash": run.input_hash,
        "run": model_to_dict(run, exclude={"input_snapshot_json"}),
        "demands": snapshot.get("demands", []),
        "resources": snapshot.get("resources", snapshot.get("clusters", [])),
        "constraints": snapshot.get("constraints", snapshot.get("params", {})),
    })


@bp.get("/policies")
def list_policies():
    page, page_size = parse_pagination()
    status = request.args.get("status")
    algorithm = request.args.get("algorithm")
    policy_run_id = request.args.get("policy_run_id", type=int)
    exclude_status = request.args.get("exclude_status")
    demand_id = request.args.get("demand_id", type=int)
    # has_demand=true 仅需求评估触发的策略；false 仅人工/定时触发的全局策略。
    has_demand_arg = request.args.get("has_demand")
    has_demand = None
    if has_demand_arg is not None:
        has_demand = has_demand_arg.lower() in ("1", "true", "yes")
    items, total = PolicyRepository().list(
        status=status, algorithm=algorithm, policy_run_id=policy_run_id,
        exclude_status=exclude_status, demand_id=demand_id, has_demand=has_demand,
        page=page, page_size=page_size,
    )
    return paginated([model_to_dict(p) for p in items], page, page_size, total)


@bp.get("/policies/<int:policy_id>")
def get_policy(policy_id: int):
    policy = PolicyService().get_policy(policy_id)
    actions = PolicyRepository().actions_for(policy.id)
    return success({
        "policy": model_to_dict(policy),
        "actions": [model_to_dict(a) for a in actions],
    })


@bp.get("/policies/<int:policy_id>/audit-logs")
def list_policy_audit_logs(policy_id: int):
    PolicyService().get_policy(policy_id)  # 404 if missing
    logs = db.session.execute(
        db.select(PolicyAuditLog)
        .where(PolicyAuditLog.policy_id == policy_id)
        .order_by(PolicyAuditLog.id.desc())
    ).scalars().all()
    return success([model_to_dict(x) for x in logs])


@bp.get("/policies/<int:policy_id>/report")
def get_policy_report(policy_id: int):
    """时段策略结构化报告：逐调整收益(元/天) + 单TPM收入示例 + 集群利用率/共享池占用率 + 模型级再平衡。"""
    return success(PolicyReportService().build(policy_id))


@bp.patch("/policies/<int:policy_id>")
def patch_policy(policy_id: int):
    payload = PolicyPatchRequest(**(request.get_json(silent=True) or {}))
    fields = payload.model_dump(exclude_unset=True)
    operator = fields.pop("operator", "system")
    policy = PolicyService().patch(policy_id, fields, operator=operator)
    db.session.commit()
    return success(model_to_dict(policy))


@bp.post("/policies/<int:policy_id>/accept")
def accept_policy(policy_id: int):
    payload = PolicyAcceptRequest(**(request.get_json(silent=True) or {}))
    policy = PolicyService().accept(
        policy_id, operator=payload.operator,
        effective_from=payload.effective_from,
        comment=payload.comment,
    )
    db.session.commit()
    return success(model_to_dict(policy))


@bp.post("/policies/<int:policy_id>/recalculate")
def recalculate_policy(policy_id: int):
    payload = PolicyRecalculateRequest(**(request.get_json(silent=True) or {}))
    run = PolicyService().recalculate(policy_id, params=payload.params, operator=payload.operator)
    db.session.commit()
    return success(model_to_dict(run, exclude={"input_snapshot_json"}))


@bp.post("/policies/<int:policy_id>/cancel")
def cancel_policy(policy_id: int):
    payload = PolicyCancelRequest(**(request.get_json(silent=True) or {}))
    policy = PolicyService().cancel(
        policy_id, operator=payload.operator, reason=payload.reason)
    db.session.commit()
    return success(model_to_dict(policy))
