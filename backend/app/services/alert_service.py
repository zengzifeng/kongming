from __future__ import annotations

from datetime import datetime

from ..extensions import db
from ..models import Alert
from ..models.alert import AlertSeverity, AlertStatus
from ..utils.errors import NotFound
from ..utils.time import utcnow


class AlertService:
    def create(self, alert_type: str, severity: str, message: str,
               subject_type: str | None = None, subject_id: str | None = None,
               payload: dict | None = None) -> Alert:
        alert = Alert(
            alert_type=alert_type,
            severity=severity,
            subject_type=subject_type,
            subject_id=subject_id,
            message=message,
            payload_json=payload or {},
            status=AlertStatus.OPEN,
        )
        db.session.add(alert)
        db.session.flush()
        return alert

    def patch(self, alert_id: int, action: str, operator: str | None = None) -> Alert:
        alert = db.session.get(Alert, alert_id)
        if not alert:
            raise NotFound("预警不存在", details={"id": alert_id})
        now = utcnow()
        if action == "ack":
            alert.status = AlertStatus.ACK
            alert.acked_by = operator
            alert.acked_at = now
        elif action == "close":
            alert.status = AlertStatus.CLOSED
            alert.closed_at = now
            if operator:
                alert.acked_by = alert.acked_by or operator
                alert.acked_at = alert.acked_at or now
        db.session.flush()
        return alert
