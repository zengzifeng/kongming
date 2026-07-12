from __future__ import annotations

from flask import Blueprint, request

from ..extensions import db
from ..repositories import DemandRepository, EvaluationRepository
from ..repositories.policy_repository import PolicyRepository
from ..schemas.common import model_to_dict
from ..schemas.demand_schema import DemandPatch
from ..services import DemandService
from ..utils.pagination import parse_pagination
from ..utils.response import paginated, success


bp = Blueprint("demands", __name__)


@bp.get("/demands")
def list_demands():
    page, page_size = parse_pagination()
    status = request.args.get("status")
    customer_id = request.args.get("customer_id", type=int)
    model = request.args.get("model")
    repo = DemandRepository()
    items, total = repo.list(status=status, customer_id=customer_id, model=model,
                              page=page, page_size=page_size)
    return paginated([model_to_dict(d) for d in items], page, page_size, total)


@bp.get("/demands/<int:demand_id>")
def get_demand(demand_id: int):
    demand = DemandService().get(demand_id)
    eval_repo = EvaluationRepository()
    pol_repo = PolicyRepository()
    latest_eval = eval_repo.latest_for_demand(demand.id)
    policy = pol_repo.latest_for_demand(demand.id)
    return success({
        "demand": model_to_dict(demand),
        "latest_evaluation": model_to_dict(latest_eval) if latest_eval else None,
        "policy": model_to_dict(policy) if policy else None,
    })


@bp.patch("/demands/<int:demand_id>")
def patch_demand(demand_id: int):
    patch = DemandPatch(**(request.get_json(silent=True) or {}))
    demand = DemandService().patch(demand_id, patch.model_dump(exclude_unset=True))
    db.session.commit()
    return success(model_to_dict(demand))
