from flask import Blueprint, jsonify

from ..extensions import db


bp = Blueprint("health", __name__)


@bp.get("/healthz")
def healthz():
    return jsonify({"data": {"status": "ok"}, "message": "ok", "errors": None})


@bp.get("/readyz")
def readyz():
    try:
        db.session.execute(db.text("SELECT 1"))
        ready = True
    except Exception:
        ready = False
    payload = {"data": {"ready": ready}, "message": "ok" if ready else "not ready", "errors": None}
    return jsonify(payload), 200 if ready else 503
