from __future__ import annotations

from datetime import datetime

from flask import Blueprint, request
from pydantic import BaseModel, Field

from ..extensions import db
from ..models import ClusterModelTpm, ConsumerModelTpm, GpuNodeCount, MonitorBatch, WatchedCluster
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
    customer_code: str = Field(min_length=1, max_length=64)  # user_id，自然主键，必填
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


@bp.delete("/monitor/consumers/<customer_code>")
def remove_consumer(customer_code: str):
    hard = request.args.get("hard", "").lower() in ("1", "true", "yes")
    ResourceMonitorService().remove_consumer(customer_code, hard=hard)
    return success({"customer_code": customer_code, "hard": hard})


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
    watched_names = _watched_cluster_names()
    latest: dict[str, ClusterModelTpm] = {}
    for r in rows:
        if watched_names and r.cluster_name not in watched_names:
            continue
        latest[r.cluster_name] = r  # 升序遍历后保留最后一个
    return success({
        "batch_id": batch_id,
        "items": [model_to_dict(r) for r in latest.values()],
    })


@bp.get("/monitor/consumer-tpm/options")
def consumer_tpm_options():
    """客户模型跑量图筛选项，来自已落库的监控快照。"""
    return success({
        "ai_models": _distinct_values(ConsumerModelTpm.ai_model),
        "ai_consumers": _distinct_values(ConsumerModelTpm.ai_consumer),
        "customer_codes": _distinct_values(ConsumerModelTpm.customer_code),
    })


@bp.get("/monitor/consumer-tpm")
def latest_consumer_tpm():
    """客户×模型 TPM；传 start_time/end_time 时返回范围序列，否则返回最新批次每组合最后一点。"""
    ai_consumer = request.args.get("ai_consumer")
    ai_model = request.args.get("ai_model")
    customer_code = request.args.get("customer_code")
    start_time = _parse_datetime_arg("start_time")
    end_time = _parse_datetime_arg("end_time")

    stmt = db.select(ConsumerModelTpm)
    if start_time or end_time:
        if start_time:
            stmt = stmt.where(ConsumerModelTpm.data_time >= start_time)
        if end_time:
            stmt = stmt.where(ConsumerModelTpm.data_time <= end_time)
    else:
        batch_id = _latest_batch_id()
        if batch_id is None:
            return success({"batch_id": None, "items": []})
        stmt = stmt.where(ConsumerModelTpm.batch_id == batch_id)

    if ai_consumer:
        stmt = stmt.where(ConsumerModelTpm.ai_consumer == ai_consumer)
    if ai_model:
        stmt = stmt.where(ConsumerModelTpm.ai_model == ai_model)
    if customer_code:
        stmt = stmt.where(ConsumerModelTpm.customer_code == customer_code)

    rows = db.session.execute(
        stmt.order_by(
            ConsumerModelTpm.data_time.asc(),
            ConsumerModelTpm.ai_model.asc(),
            ConsumerModelTpm.ai_consumer.asc(),
        )
    ).scalars().all()

    if not (start_time or end_time):
        latest: dict[tuple, ConsumerModelTpm] = {}
        for r in rows:
            latest[(r.customer_code, r.ai_model)] = r  # per-user_id：按 customer_code 去重取最后一点
        rows = list(latest.values())

    return success({
        "batch_id": rows[-1].batch_id if rows else None,
        "items": [model_to_dict(r) for r in rows],
    })


def _latest_batch_id() -> int | None:
    return db.session.execute(
        db.select(MonitorBatch.id).order_by(MonitorBatch.id.desc()).limit(1)
    ).scalar_one_or_none()


def _distinct_values(column) -> list[str]:
    rows = db.session.execute(
        db.select(column).where(column.is_not(None)).distinct().order_by(column.asc())
    ).scalars().all()
    return [str(value) for value in rows if value]


def _parse_datetime_arg(name: str) -> datetime | None:
    value = request.args.get(name)
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def _watched_cluster_names() -> set[str]:
    return {
        item.cluster_name
        for item in db.session.execute(
            db.select(WatchedCluster).where(WatchedCluster.enabled.is_(True))
        ).scalars()
    }

