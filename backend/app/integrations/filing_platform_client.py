from __future__ import annotations

import hashlib
import json
import random
from datetime import datetime, timedelta, timezone
from typing import Iterable

from ..utils.errors import IntegrationError
from ..utils.time import utcnow


def _hash_payload(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class FilingPayload(dict):
    """Raw payload from filing platform; dict-shaped for direct JSON storage."""


class FilingPlatformClient:
    def __init__(self, mode: str = "mock", base_url: str = ""):
        self.mode = mode
        self.base_url = base_url

    def fetch_pending_filings(self, since: datetime | None = None) -> list[FilingPayload]:
        if self.mode != "mock":
            raise IntegrationError("真实报备平台 client 未实现", code="INTEGRATION_FAILED")
        return list(_mock_filings(since))


def _mock_filings(since: datetime | None) -> Iterable[FilingPayload]:
    now = utcnow()
    rng = random.Random(now.strftime("%Y%m%d%H"))
    customers = [
        ("C0001", "光合传媒", "A"),
        ("C0002", "星海智算", "S"),
        ("C0003", "墨方科技", "B"),
    ]
    models = ["gpt-4o-mini", "qwen2.5-72b", "deepseek-v3", "llama-3.1-70b"]
    n = rng.randint(2, 5)
    for i in range(n):
        cust = customers[i % len(customers)]
        report_id = f"R{now.strftime('%Y%m%d%H')}{i:03d}"
        payload = FilingPayload({
            "report_id": report_id,
            "customer_code": cust[0],
            "customer_name": cust[1],
            "customer_level": cust[2],
            "model": rng.choice(models),
            "expected_tpm": rng.choice([5_000, 20_000, 80_000, 200_000]),
            "expected_rpm": rng.choice([200, 800, 2000]),
            "discount_rate": rng.choice([0.7, 0.8, 0.9, 1.0]),
            "expected_start_at": (now + timedelta(days=rng.randint(0, 5))).isoformat(),
            "expected_end_at": (now + timedelta(days=rng.randint(30, 365))).isoformat(),
            "pulled_at": now.isoformat(),
        })
        payload["_hash"] = _hash_payload({k: v for k, v in payload.items() if k != "pulled_at"})
        yield payload
