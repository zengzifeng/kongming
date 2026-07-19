from datetime import timedelta

from app.extensions import db
from app.models import ConsumerModelTpm, MonitorBatch, VendorQuota
from app.services import VendorRuntimeSyncService
from app.utils.time import utcnow


def test_vendor_runtime_sync_distributes_latest_thirdparty_tpm(app):
    now = utcnow()
    batch = MonitorBatch(
        batch_no="vendor-runtime-sync-test",
        triggered_by="test",
        started_at=now,
        finished_at=now,
        status="success",
    )
    db.session.add(batch)
    db.session.flush()

    db.session.add(ConsumerModelTpm(
        batch_id=batch.id,
        data_time=now - timedelta(minutes=1),
        ai_consumer="consumer-a",
        customer_code="user-a",
        ai_model="GLM-5.2",
        tpm=1_000_000,
        thirdparty_ratio=20,
    ))
    db.session.add(ConsumerModelTpm(
        batch_id=batch.id,
        data_time=now,
        ai_consumer="consumer-a",
        customer_code="user-a",
        ai_model="GLM-5.2",
        tpm=2_000_000,
        thirdparty_ratio=50,
    ))
    db.session.add(VendorQuota(
        vendor="vendor-a",
        model="GLM-5.2",
        quota_tpm=3_000_000,
        actual_tpm=0,
        actual_redundant_tpm=0,
        effective_from=now - timedelta(days=1),
        status="active",
    ))
    db.session.add(VendorQuota(
        vendor="vendor-b",
        model="glm-5.2",
        quota_tpm=1_000_000,
        actual_tpm=0,
        actual_redundant_tpm=0,
        effective_from=now - timedelta(days=1),
        status="active",
    ))
    db.session.commit()

    result = VendorRuntimeSyncService().sync_from_latest_consumer_tpm()

    assert result["updated"] == 2
    vendor_a = db.session.execute(
        db.select(VendorQuota).where(VendorQuota.vendor == "vendor-a")
    ).scalar_one()
    vendor_b = db.session.execute(
        db.select(VendorQuota).where(VendorQuota.vendor == "vendor-b")
    ).scalar_one()
    assert float(vendor_a.actual_tpm) == 750_000
    assert float(vendor_a.actual_redundant_tpm) == 2_250_000
    assert float(vendor_b.actual_tpm) == 250_000
    assert float(vendor_b.actual_redundant_tpm) == 750_000
