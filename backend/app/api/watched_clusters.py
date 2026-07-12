from __future__ import annotations

from flask import Blueprint, request
from pydantic import BaseModel, Field

from ..schemas.common import model_to_dict
from ..services import WatchedClusterService
from ..utils.response import success


bp = Blueprint("watched_clusters", __name__)


class WatchedClusterCreate(BaseModel):
    cluster_name: str = Field(min_length=1, max_length=128)
    enabled: bool = True
    sort_order: int | None = Field(default=None, ge=0)


class WatchedClusterPatch(BaseModel):
    cluster_name: str | None = Field(default=None, min_length=1, max_length=128)
    enabled: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)


@bp.get("/watched-clusters")
def list_watched_clusters():
    include_disabled = request.args.get("include_disabled", "false").lower() in {"1", "true", "yes"}
    items = WatchedClusterService().list(include_disabled=include_disabled)
    return success([model_to_dict(item) for item in items])


@bp.get("/watched-clusters/<int:cluster_id>")
def get_watched_cluster(cluster_id: int):
    item = WatchedClusterService().get(cluster_id)
    return success(model_to_dict(item))


@bp.post("/watched-clusters")
def create_watched_cluster():
    payload = WatchedClusterCreate(**(request.get_json(silent=True) or {}))
    item = WatchedClusterService().create(payload.model_dump(exclude_unset=True))
    return success(model_to_dict(item), status=201)


@bp.patch("/watched-clusters/<int:cluster_id>")
def patch_watched_cluster(cluster_id: int):
    payload = WatchedClusterPatch(**(request.get_json(silent=True) or {}))
    item = WatchedClusterService().update(cluster_id, payload.model_dump(exclude_unset=True))
    return success(model_to_dict(item))


@bp.delete("/watched-clusters/<int:cluster_id>")
def delete_watched_cluster(cluster_id: int):
    WatchedClusterService().delete(cluster_id)
    return success({"deleted": cluster_id})
