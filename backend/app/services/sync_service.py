from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Iterable

from sqlalchemy import select

from ..extensions import db
from ..integrations import filing_client
from ..models import (
    Demand,
    DemandStatus,
    RawFiling,
    SyncBatch,
)
from ..models.sync_batch import SyncBatchStatus
from ..utils.time import utcnow
from .demand_service import DemandService
from .alert_service import AlertService


class SyncService:
    def __init__(self):
        self.demand_service = DemandService()
        self.alert_service = AlertService()

    def run_sync(self, triggered_by: str = "cron") -> SyncBatch:
        now = utcnow()
        batch_no = "B" + now.strftime("%Y%m%d%H%M%S")
        batch = SyncBatch(
            batch_no=batch_no,
            source="filing_platform",
            triggered_by=triggered_by,
            started_at=now,
            status=SyncBatchStatus.RUNNING,
        )
        db.session.add(batch)
        db.session.flush()

        inserted = updated = skipped = 0
        try:
            payloads = filing_client().fetch_pending_filings()
            for payload in payloads:
                payload_hash = payload.get("_hash") or self._hash(payload)
                exists = db.session.execute(
                    select(RawFiling).where(
                        RawFiling.batch_id == batch.id,
                        RawFiling.report_id == payload["report_id"],
                    )
                ).scalar_one_or_none()
                if exists:
                    skipped += 1
                    continue
                raw = RawFiling(
                    batch_id=batch.id,
                    report_id=payload["report_id"],
                    payload_json=dict(payload),
                    pulled_at=now,
                    hash=payload_hash,
                )
                db.session.add(raw)
                db.session.flush()

                outcome = self.demand_service.upsert_from_raw(raw)
                if outcome == "inserted":
                    inserted += 1
                elif outcome == "updated":
                    updated += 1
                else:
                    skipped += 1

            batch.total_pulled = inserted + updated + skipped
            batch.total_inserted = inserted
            batch.total_updated = updated
            batch.total_skipped = skipped
            batch.status = SyncBatchStatus.SUCCESS
            batch.finished_at = utcnow()
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            batch = db.session.get(SyncBatch, batch.id)
            batch.status = SyncBatchStatus.FAILED
            batch.error_message = str(exc)[:1000]
            batch.finished_at = utcnow()
            db.session.commit()
            self.alert_service.create(
                alert_type="job_failed",
                severity="critical",
                subject_type="sync_batch",
                subject_id=str(batch.id),
                message=f"同步批次失败: {exc}",
                payload={"batch_no": batch.batch_no},
            )
        return batch

    @staticmethod
    def _hash(payload: dict) -> str:
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()
