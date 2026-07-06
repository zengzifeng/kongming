from __future__ import annotations

from flask import Blueprint, request

from ..extensions import db
from ..repositories import EvaluationRepository
from ..schemas.common import model_to_dict
from ..schemas.evaluation_schema import ApproveRequest, EvaluateRequest, RejectRequest
from ..services import EvaluationService
from ..utils.errors import NotFound
from ..utils.pagination import parse_pagination
from ..utils.response import paginated, success


bp = Blueprint("evaluations", __name__)


@bp.post("/demands/<int:demand_id>/evaluate")
def evaluate(demand_id: int):
    payload = EvaluateRequest(**(request.get_json(silent=True) or {}))
    evaluation = EvaluationService().evaluate(demand_id, force=payload.force)
    db.session.commit()
    return success(model_to_dict(evaluation), status=201)


@bp.get("/evaluations")
def list_evaluations():
    page, page_size = parse_pagination()
    status = request.args.get("status")
    recommendation = request.args.get("recommendation")
    items, total = EvaluationRepository().list(
        status=status, recommendation=recommendation,
        page=page, page_size=page_size,
    )
    return paginated([model_to_dict(e) for e in items], page, page_size, total)


@bp.get("/evaluations/<int:evaluation_id>")
def get_evaluation(evaluation_id: int):
    from ..models import Evaluation
    evaluation = db.session.get(Evaluation, evaluation_id)
    if not evaluation:
        raise NotFound("评估不存在", details={"id": evaluation_id})
    return success(model_to_dict(evaluation))


@bp.post("/evaluations/<int:evaluation_id>/approve")
def approve(evaluation_id: int):
    payload = ApproveRequest(**(request.get_json(silent=True) or {}))
    evaluation = EvaluationService().approve(
        evaluation_id, operator=payload.operator, comment=payload.comment,
    )
    db.session.commit()
    return success(model_to_dict(evaluation))


@bp.post("/evaluations/<int:evaluation_id>/reject")
def reject(evaluation_id: int):
    payload = RejectRequest(**(request.get_json(silent=True) or {}))
    evaluation = EvaluationService().reject(
        evaluation_id, operator=payload.operator, reason=payload.reason,
    )
    db.session.commit()
    return success(model_to_dict(evaluation))
