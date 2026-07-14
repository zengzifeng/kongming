from __future__ import annotations

from flask import Blueprint, request
from sqlalchemy import select

from ..extensions import db
from ..models import VendorQuota
from ..schemas.common import model_to_dict
from ..utils.model_name import normalize_model_name
from ..utils.pagination import parse_pagination
from ..utils.response import paginated


bp = Blueprint("vendors", __name__)


@bp.get("/vendors/quotas")
def list_vendor_quotas():
    page, page_size = parse_pagination(default_size=50)
    filters = []
    vendor = request.args.get("vendor")
    model = request.args.get("model")
    status = request.args.get("status")
    if vendor:
        filters.append(VendorQuota.vendor == vendor)
    if model:
        filters.append(db.func.lower(VendorQuota.model) == normalize_model_name(model))
    if status:
        filters.append(VendorQuota.status == status)

    stmt = select(VendorQuota)
    count_stmt = select(db.func.count()).select_from(VendorQuota)
    if filters:
        stmt = stmt.where(*filters)
        count_stmt = count_stmt.where(*filters)
    stmt = stmt.order_by(VendorQuota.vendor.asc(), VendorQuota.model.asc(), VendorQuota.effective_from.desc())
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    items = db.session.execute(stmt).scalars().all()
    total = db.session.execute(count_stmt).scalar_one()
    payload = []
    for item in items:
        data = model_to_dict(item)
        data["model"] = normalize_model_name(data.get("model"))
        payload.append(data)
    return paginated(payload, page, page_size, total)
