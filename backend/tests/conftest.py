import pytest

from app import create_app
from app.extensions import db


@pytest.fixture()
def app():
    app = create_app("test")
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def seed_cluster(name, model, machine_count, tpm_per_machine,
                 current_tpm=0.0, provider=None, customer_name="c"):
    """按新数据源组装一个集群快照：监控实跑(cluster_model_tpm) + 容量(cluster_capacities)
    + provider 映射(provider_mappings)。同一测试内多次调用复用最新的 MonitorBatch。"""
    from datetime import datetime

    from app.models import (
        ClusterCapacity,
        ClusterModelTpm,
        MonitorBatch,
        MonitorBatchStatus,
        ProviderMapping,
    )
    from app.utils.time import utcnow

    batch = db.session.query(MonitorBatch).order_by(MonitorBatch.id.desc()).first()
    if batch is None:
        batch = MonitorBatch(batch_no="TEST-BATCH", triggered_by="test",
                             started_at=utcnow(), status=MonitorBatchStatus.SUCCESS)
        db.session.add(batch)
        db.session.flush()
    db.session.add(ClusterModelTpm(
        batch_id=batch.id, data_time=datetime(2026, 7, 7, 11, 0, 0),
        cluster_name=name, tpm=current_tpm, node_count=machine_count, node_avg_tpm=0,
    ))
    if db.session.query(ClusterCapacity).filter_by(cluster_name=name).first() is None:
        db.session.add(ClusterCapacity(cluster_name=name, tpm_per_machine=tpm_per_machine))
    if provider:
        db.session.add(ProviderMapping(
            customer_name=customer_name, model_name=model,
            provider=provider, cluster_name=name,
        ))
    db.session.flush()
