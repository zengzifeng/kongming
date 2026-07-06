from __future__ import annotations

from flask import Blueprint, request

from ..extensions import db
from ..models import RawFiling, SyncBatch
from ..schemas.demand_schema import SyncTriggerRequest
from ..services import SyncService
from ..utils.errors import NotFound
from ..utils.pagination import parse_pagination
from ..utils.response import paginated, success
from ..schemas.common import model_to_dict


bp = Blueprint("sync", __name__)


@bp.get("/sync-batches")
def list_batches():
    page, page_size = parse_pagination()
    status = request.args.get("status")
    stmt = db.select(SyncBatch).order_by(SyncBatch.id.desc())
    if status:
        stmt = stmt.where(SyncBatch.status == status)
    total = db.session.execute(
        db.select(db.func.count()).select_from(stmt.subquery())
    ).scalar_one()
    items = db.session.execute(
        stmt.limit(page_size).offset((page - 1) * page_size)
    ).scalars().all()
    return paginated([model_to_dict(b) for b in items], page, page_size, total)


@bp.post("/sync-batches/run")
def trigger_sync():
    SyncTriggerRequest(**(request.get_json(silent=True) or {}))
    batch = SyncService().run_sync(triggered_by="manual")
    return success(model_to_dict(batch), status=202)


@bp.get("/sync-batches/<int:batch_id>")
def get_batch(batch_id: int):
    batch = db.session.get(SyncBatch, batch_id)
    if not batch:
        raise NotFound("批次不存在", details={"id": batch_id})
    return success(model_to_dict(batch))


@bp.get("/raw-filings")
def list_raw_filings():
    page, page_size = parse_pagination()
    batch_id = request.args.get("batch_id", type=int)
    report_id = request.args.get("report_id")
    stmt = db.select(RawFiling).order_by(RawFiling.id.desc())
    if batch_id:
        stmt = stmt.where(RawFiling.batch_id == batch_id)
    if report_id:
        stmt = stmt.where(RawFiling.report_id == report_id)
    total = db.session.execute(
        db.select(db.func.count()).select_from(stmt.subquery())
    ).scalar_one()
    items = db.session.execute(
        stmt.limit(page_size).offset((page - 1) * page_size)
    ).scalars().all()
    return paginated([model_to_dict(r) for r in items], page, page_size, total)
