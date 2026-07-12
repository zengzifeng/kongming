from __future__ import annotations

from flask import Blueprint, request
from pydantic import BaseModel, Field

from ..schemas.common import model_to_dict
from ..services import WaveFittingService
from ..utils.response import success


bp = Blueprint("fittings", __name__)


class FittingConfigCreate(BaseModel):
    customer_code: str = Field(min_length=1, max_length=64)
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


@bp.get("/fittings/results")
def list_results():
    items, total = WaveFittingService().result_repo.list(
        level=request.args.get("level"),
        customer_code=request.args.get("customer_code"),
        model_name=request.args.get("model_name"),
        period=request.args.get("period"),
        page=int(request.args.get("page", 1)),
        page_size=int(request.args.get("page_size", 50)),
    )
    return success({
        "items": [model_to_dict(x) for x in items],
        "total": total,
    })
