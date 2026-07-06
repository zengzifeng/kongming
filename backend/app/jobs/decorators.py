from __future__ import annotations

from functools import wraps

from ..extensions import db
from ..models import JobLog
from ..utils.time import utcnow


def with_job_log(name: str):
    def deco(fn):
        @wraps(fn)
        def wrapper(app, *args, **kwargs):
            with app.app_context():
                log = JobLog(job_name=name, started_at=utcnow(), status="running")
                db.session.add(log)
                db.session.commit()
                try:
                    result = fn(app, *args, **kwargs)
                    log.status = "success"
                    log.finished_at = utcnow()
                    log.payload_json = {"result": _safe(result)}
                    db.session.commit()
                    return result
                except Exception as exc:
                    db.session.rollback()
                    log = db.session.get(JobLog, log.id) or log
                    log.status = "failed"
                    log.finished_at = utcnow()
                    log.message = str(exc)[:1000]
                    db.session.add(log)
                    db.session.commit()
                    app.logger.exception("job %s failed: %s", name, exc)
                    raise
        return wrapper
    return deco


def _safe(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        return str(value)
    except Exception:
        return None
