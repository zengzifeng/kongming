from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..utils.time import utcnow


@dataclass
class TPMPoint:
    ts: datetime
    tpm_self: float
    tpm_vendor: float
    cache_hit_rate: float
    gpu_utilization: float


@dataclass
class MonitoringSnapshot:
    captured_at: str
    points: list[TPMPoint] = field(default_factory=list)


class MonitoringClient:
    def __init__(self, mode: str = "mock"):
        self.mode = mode

    def tpm_series(self, window_minutes: int = 60, group_by: str = "global") -> MonitoringSnapshot:
        now = utcnow()
        points = []
        for i in range(window_minutes):
            ts = now - timedelta(minutes=window_minutes - i)
            base = 500_000 + 200_000 * (1 if 9 <= ts.hour <= 20 else 0)
            points.append(TPMPoint(ts, base * 0.7, base * 0.2, 0.42, 0.65))
        return MonitoringSnapshot(captured_at=now.isoformat(), points=points)

    def aggregate_for_report(self, report_id: str, days: int = 7) -> dict:
        return {
            "report_id": report_id,
            "days": days,
            "avg_actual_tpm": 15_000,
        }
