from __future__ import annotations

from dataclasses import asdict

from ..integrations import (
    resource_client,
    monitoring_client,
    vendor_client,
)
from ..models import Demand
from ..utils.time import utcnow
from .base import DemandSnapshotItem, PolicyInputSnapshot


def build_snapshot(algorithm: str, demands: list[Demand], params: dict | None = None) -> PolicyInputSnapshot:
    resources = resource_client().snapshot()
    monitoring = monitoring_client().tpm_series()
    vendors = vendor_client().quotas()

    params = params or {}
    demand_params = params.get("demands", {})
    default_input_ratio = float(params.get("default_input_ratio", 1.0))

    demand_items = []
    for d in demands:
        overrides = demand_params.get(d.report_id, {})
        demand_items.append(DemandSnapshotItem(
            report_id=d.report_id,
            customer_code=str(d.customer_id) if d.customer_id else "unknown",
            model_name=d.model_name,
            expected_tpm=float(d.expected_tpm or 0),
            expected_rpm=float(d.expected_rpm or 0),
            discount_rate=float(d.discount_rate or 1.0),
            input_ratio=float(overrides.get("input_ratio", default_input_ratio)),
            cache_hit_rate=float(overrides.get("cache_hit_rate", params.get("default_cache_hit_rate", 0.0))),
            current_self_ratio=float(overrides.get("current_self_ratio", 0.0)),
            current_vendor_ratios=dict(overrides.get("current_vendor_ratios", {})),
            quality_score=float(overrides.get("quality_score", 0.0)),
        ))

    return PolicyInputSnapshot(
        captured_at=utcnow(),
        algorithm=algorithm,
        demands=demand_items,
        resources={
            "captured_at": resources.captured_at,
            "clusters": [asdict(c) for c in resources.clusters],
            "total_capacity_tpm": resources.total_capacity_tpm,
            "total_current_redundant_tpm": resources.total_current_redundant_tpm,
            "total_idle_redundant_tpm": resources.total_idle_redundant_tpm,
            "total_busy_redundant_tpm": resources.total_busy_redundant_tpm,
        },
        monitoring={
            "captured_at": monitoring.captured_at,
            "window_minutes": len(monitoring.points),
            "avg_tpm_self": (
                sum(p.tpm_self for p in monitoring.points) / max(len(monitoring.points), 1)
            ),
            "avg_tpm_vendor": (
                sum(p.tpm_vendor for p in monitoring.points) / max(len(monitoring.points), 1)
            ),
            "avg_cache_hit_rate": (
                sum(p.cache_hit_rate for p in monitoring.points) / max(len(monitoring.points), 1)
            ),
        },
        vendors=[asdict(v) for v in vendors],
        params=params,
    )
