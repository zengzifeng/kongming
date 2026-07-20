from __future__ import annotations

from flask import Blueprint, request
from pydantic import BaseModel, Field

from ..extensions import db
from ..models import MonitorConsumer, ProviderMapping
from ..schemas.common import model_to_dict
from ..services import WaveFittingService
from ..utils.response import success


bp = Blueprint("fittings", __name__)


class FittingConfigCreate(BaseModel):
    customer_code: str = Field(min_length=1, max_length=64)  # user_id，自然主键
    model_name: str = Field(min_length=1, max_length=64)
    period: str = Field(pattern="^(idle|busy)$")
    algo_name: str = Field(min_length=1, max_length=64)
    params_json: dict | None = None
    enabled: bool | None = None


class FittingConfigPatch(BaseModel):
    period: str | None = Field(default=None, pattern="^(idle|busy)$")
    algo_name: str | None = Field(default=None, max_length=64)
    params_json: dict | None = None
    enabled: bool | None = None


# ---- 算法目录（只读；有哪些算法可选管理在库，不支持 API 修改）----
@bp.get("/fittings/algorithms")
def list_algorithms():
    items = WaveFittingService().list_algorithms()
    return success([model_to_dict(x) for x in items])


# ---- 客户关联配置（可查/可增/可改）----
@bp.get("/fittings/configs")
def list_configs():
    items = WaveFittingService().list_configs(
        customer_code=request.args.get("customer_code"),
        model_name=request.args.get("model_name"),
        period=request.args.get("period"),
    )
    return success([model_to_dict(x) for x in items])


@bp.get("/fittings/configs/<int:config_id>")
def get_config(config_id: int):
    cfg = WaveFittingService().get_config(config_id)
    return success(model_to_dict(cfg))


@bp.post("/fittings/configs")
def create_config():
    payload = FittingConfigCreate(**(request.get_json(silent=True) or {}))
    cfg = WaveFittingService().upsert_config(payload.model_dump(exclude_unset=True))
    return success(model_to_dict(cfg))


@bp.patch("/fittings/configs/<int:config_id>")
def patch_config(config_id: int):
    payload = FittingConfigPatch(**(request.get_json(silent=True) or {}))
    cfg = WaveFittingService().update_config(
        config_id, payload.model_dump(exclude_unset=True))
    return success(model_to_dict(cfg))


# ---- 跑拟合 & 查看波形 ----
@bp.post("/fittings/run")
def run_fitting():
    summary = WaveFittingService().run_fitting()
    return success(summary)


def _truthy_arg(name: str) -> bool:
    return str(request.args.get(name, "")).lower() in {"1", "true", "yes", "on"}


def _fitting_result_to_dict(item, consumers_by_code: dict[str, MonitorConsumer],
                            clusters_by_consumer_model: dict[tuple[str, str], str]) -> dict:
    data = model_to_dict(item)
    data["ai_consumer"] = None
    data["customer_name"] = None
    consumer = consumers_by_code.get(item.customer_code or "")
    if consumer:
        customer_name = consumer.customer_name or consumer.ai_consumer
        data["ai_consumer"] = consumer.ai_consumer
        data["customer_name"] = customer_name
        if not data.get("cluster_name"):
            data["cluster_name"] = clusters_by_consumer_model.get((customer_name, item.model_name))
    return data


@bp.get("/fittings/results")
def list_results():
    items, total = WaveFittingService().result_repo.list(
        level=request.args.get("level"),
        customer_code=request.args.get("customer_code"),
        model_name=request.args.get("model_name"),
        period=request.args.get("period"),
        page=int(request.args.get("page", 1)),
        page_size=int(request.args.get("page_size", 50)),
        restrict_to_sell_discount=_truthy_arg("restrict_to_sell_discount"),
    )
    customer_codes = {item.customer_code for item in items if item.customer_code}
    consumers = list(db.session.execute(
        db.select(MonitorConsumer).where(MonitorConsumer.customer_code.in_(customer_codes))
    ).scalars()) if customer_codes else []
    consumers_by_code = {consumer.customer_code: consumer for consumer in consumers}
    customer_names = {consumer.customer_name or consumer.ai_consumer for consumer in consumers}
    model_names = {item.model_name for item in items}
    clusters_by_consumer_model: dict[tuple[str, str], str] = {}
    if customer_names and model_names:
        mappings = db.session.execute(
            db.select(ProviderMapping)
            .where(
                ProviderMapping.customer_name.in_(customer_names),
                ProviderMapping.model_name.in_(model_names),
                ProviderMapping.cluster_name.is_not(None),
            )
            .order_by(
                ProviderMapping.customer_name.asc(),
                ProviderMapping.model_name.asc(),
                ProviderMapping.id.asc(),
            )
        ).scalars()
        for mapping in mappings:
            if mapping.cluster_name:
                clusters_by_consumer_model.setdefault(
                    (mapping.customer_name, mapping.model_name), mapping.cluster_name)
    return success({
        "items": [
            _fitting_result_to_dict(x, consumers_by_code, clusters_by_consumer_model)
            for x in items
        ],
        "total": total,
    })
