from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func

from ..extensions import db
from ..models import ConsumerModelTpm, MonitorBatch, VendorQuota, VendorStatus


class VendorRuntimeSyncService:
    """Use latest minute-level consumer TPM snapshots to refresh vendor runtime fields."""

    def sync_from_latest_consumer_tpm(self) -> dict:
        batch_id = self._latest_batch_id()
        active_vendors = self._active_vendors()
        if not active_vendors:
            return {"batch_id": batch_id, "models": 0, "vendors": 0, "updated": 0}

        thirdparty_by_model = self._thirdparty_tpm_by_model(batch_id) if batch_id else {}
        vendors_by_model: dict[str, list[VendorQuota]] = defaultdict(list)
        for vendor in active_vendors:
            vendors_by_model[self._model_key(vendor.model)].append(vendor)

        updated = 0
        for model_key, vendors in vendors_by_model.items():
            total_quota = sum(float(v.quota_tpm or 0) for v in vendors)
            model_actual = thirdparty_by_model.get(model_key, 0.0)
            for vendor in vendors:
                quota = float(vendor.quota_tpm or 0)
                actual = model_actual * quota / total_quota if total_quota > 0 else 0.0
                vendor.actual_tpm = actual
                vendor.actual_redundant_tpm = max(quota - actual, 0.0)
                updated += 1

        db.session.commit()
        return {
            "batch_id": batch_id,
            "models": len(vendors_by_model),
            "vendors": len(active_vendors),
            "updated": updated,
        }

    def _latest_batch_id(self) -> int | None:
        return db.session.execute(
            db.select(func.max(MonitorBatch.id))
        ).scalar_one_or_none()

    def _active_vendors(self) -> list[VendorQuota]:
        return list(db.session.execute(
            db.select(VendorQuota).where(VendorQuota.status == VendorStatus.ACTIVE)
        ).scalars())

    def _thirdparty_tpm_by_model(self, batch_id: int) -> dict[str, float]:
        rows = db.session.execute(
            db.select(ConsumerModelTpm)
            .where(ConsumerModelTpm.batch_id == batch_id)
            .order_by(
                ConsumerModelTpm.ai_consumer.asc(),
                ConsumerModelTpm.ai_model.asc(),
                ConsumerModelTpm.data_time.asc(),
                ConsumerModelTpm.id.asc(),
            )
        ).scalars()

        latest: dict[tuple[str, str], ConsumerModelTpm] = {}
        for row in rows:
            latest[(row.ai_consumer, row.ai_model)] = row

        by_model: dict[str, float] = defaultdict(float)
        for row in latest.values():
            ratio = self._ratio(float(row.thirdparty_ratio or 0))
            by_model[self._model_key(row.ai_model)] += float(row.tpm or 0) * ratio
        return dict(by_model)

    @staticmethod
    def _ratio(value: float) -> float:
        if value <= 0:
            return 0.0
        return value / 100 if value > 1 else value

    @staticmethod
    def _model_key(value: str | None) -> str:
        return str(value or "").strip().lower()
