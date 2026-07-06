from ..models import Alert, AlertStatus
from .base_repository import BaseRepository


class AlertRepository(BaseRepository[Alert]):
    model = Alert

    def list(self, status=None, severity=None, alert_type=None, page=1, page_size=20):
        filters = []
        if status:
            filters.append(Alert.status == status)
        if severity:
            filters.append(Alert.severity == severity)
        if alert_type:
            filters.append(Alert.alert_type == alert_type)
        return self.list_paginated(filters=filters, page=page, page_size=page_size)
