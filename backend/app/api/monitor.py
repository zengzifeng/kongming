from __future__ import annotations

from flask import Blueprint, request
from pydantic import BaseModel, Field

from ..extensions import db
from ..models import ClusterModelTpm, ConsumerModelTpm, GpuNodeCount, MonitorBatch
from ..schemas.common import model_to_dict
from ..services import ResourceMonitorService
from ..utils.pagination import parse_pagination
from ..utils.response import paginated, success


bp = Blueprint("monitor", __name__)


class MonitorCollectRequest(BaseModel):
    start_time: str | None = None
    end_time: str | None = None


class ConsumerCreateRequest(BaseModel):
    ai_consumer: str = Field(min_length=1, max_length=128)
    customer_code: str | None = Field(default=None, max_length=64)
    customer_name: str | None = Field(default=None, max_length=128)
    note: str | None = Field(default=None, max_length=512)


# ---------------- 采集 ----------------
@bp.post("/monitor/collect")
def collect():
    payload = MonitorCollectRequest(**(request.get_json(silent=True) or {}))
    batch = ResourceMonitorService().run_collection(
        triggered_by="manual", start_time=payload.start_time, end_time=payload.end_time)
    return success(model_to_dict(batch, exclude={"raw_json"}), status=202)


@bp.get("/monitor/batches")
def list_batches():
    page, page_size = parse_pagination()
    status = request.args.get("status")
    stmt = db.select(MonitorBatch).order_by(MonitorBatch.id.desc())
    if status:
        stmt = stmt.where(MonitorBatch.status == status)
    total = db.session.execute(
        db.select(db.func.count()).select_from(stmt.subquery())
    ).scalar_one()
    items = db.session.execute(
        stmt.limit(page_size).offset((page - 1) * page_size)
    ).scalars().all()
    return paginated([model_to_dict(b, exclude={"raw_json"}) for b in items],
                     page, page_size, total)


@bp.get("/monitor/batches/<int:batch_id>")
def get_batch(batch_id: int):
    batch = ResourceMonitorService().get_batch(batch_id)
    return success(model_to_dict(batch, exclude={"raw_json"}))


# ---------------- consumer 维护 ----------------
@bp.get("/monitor/consumers")
def list_consumers():
    enabled = request.args.get("enabled")
    flag = None if enabled is None else enabled.lower() in ("1", "true", "yes")
    items = ResourceMonitorService().list_consumers(enabled=flag)
    return success([model_to_dict(x) for x in items])


@bp.post("/monitor/consumers")
def add_consumer():
    payload = ConsumerCreateRequest(**(request.get_json(silent=True) or {}))
    consumer = ResourceMonitorService().add_consumer(
        ai_consumer=payload.ai_consumer, customer_code=payload.customer_code,
        customer_name=payload.customer_name, note=payload.note)
    return success(model_to_dict(consumer), status=201)


@bp.delete("/monitor/consumers/<ai_consumer>")
def remove_consumer(ai_consumer: str):
    hard = request.args.get("hard", "").lower() in ("1", "true", "yes")
    ResourceMonitorService().remove_consumer(ai_consumer, hard=hard)
    return success({"ai_consumer": ai_consumer, "hard": hard})


# ---------------- 最新快照查询 ----------------
@bp.get("/monitor/cluster-tpm")
def latest_cluster_tpm():
    """最新采集批次的集群瞬时产能（每集群取其在该批次内最后一个时间点）。"""
    batch_id = _latest_batch_id()
    if batch_id is None:
        return success({"batch_id": None, "items": []})
    rows = db.session.execute(
        db.select(ClusterModelTpm)
        .where(ClusterModelTpm.batch_id == batch_id)
        .order_by(ClusterModelTpm.cluster_name.asc(), ClusterModelTpm.data_time.asc())
    ).scalars().all()
    latest: dict[str, ClusterModelTpm] = {}
    for r in rows:
        latest[r.cluster_name] = r  # 升序遍历后保留最后一个
    return success({
        "batch_id": batch_id,
        "items": [model_to_dict(r) for r in latest.values()],
    })


@bp.get("/monitor/consumer-tpm")
def latest_consumer_tpm():
    """最新采集批次的客户×模型瞬时 TPM（可按 ai_consumer / ai_model 过滤，取各组合最后时间点）。"""
    batch_id = _latest_batch_id()
    if batch_id is None:
        return success({"batch_id": None, "items": []})
    ai_consumer = request.args.get("ai_consumer")
    ai_model = request.args.get("ai_model")
    stmt = db.select(ConsumerModelTpm).where(ConsumerModelTpm.batch_id == batch_id)
    if ai_consumer:
        stmt = stmt.where(ConsumerModelTpm.ai_consumer == ai_consumer)
    if ai_model:
        stmt = stmt.where(ConsumerModelTpm.ai_model == ai_model)
    stmt = stmt.order_by(ConsumerModelTpm.data_time.asc())
    rows = db.session.execute(stmt).scalars().all()
    latest: dict[tuple, ConsumerModelTpm] = {}
    for r in rows:
        latest[(r.ai_consumer, r.ai_model)] = r
    return success({
        "batch_id": batch_id,
        "items": [model_to_dict(r) for r in latest.values()],
    })


def _latest_batch_id() -> int | None:
    return db.session.execute(
        db.select(MonitorBatch.id).order_by(MonitorBatch.id.desc()).limit(1)
    ).scalar_one_or_none()
