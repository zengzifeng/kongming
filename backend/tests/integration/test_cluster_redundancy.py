"""cluster_redundancy：验证策略运行前从实跑量计算集群当前冗余。"""
from datetime import datetime

from app.algorithms.snapshot import build_snapshot
from app.extensions import db
from app.models import CustomerUsageHourly

from tests.conftest import seed_cluster


def _hourly(dt, io):
    return CustomerUsageHourly(
        customer_id=1, customer_name="c", user_id="u",
        data_time=dt, stat_date=dt.date(), model="glm-5.1",
        provider="ksyun-glm5.1-qy-10056", model_source="自建", data_source="生产",
        output_token=0, cache_token=0, cache_miss_token=0, total_input=0,
        input_output=io,
    )


def _seed(app):
    # 集群：单台 100万 TPM，2 台 → 总容量 200万；监控实跑 50万；provider 由 provider_mappings 关联。
    seed_cluster("GLM-5.1-FP8", "glm-5.1", machine_count=2, tpm_per_machine=1_000_000,
                 current_tpm=500_000, provider="ksyun-glm5.1-qy-10056")
    # 该 provider 最新整点自建负载：io=60,000,000 → 60,000,000/60 = 1,000,000 TPM
    t_old = datetime(2026, 7, 7, 10, 0, 0)
    t_new = datetime(2026, 7, 7, 11, 0, 0)  # 最新整点
    db.session.add_all([_hourly(t_old, 999_999_999), _hourly(t_new, 60_000_000)])
    db.session.flush()


def test_redundancy_computed_from_latest_hour_load(app):
    _seed(app)
    snap = build_snapshot("realtime", demand_items=[], enrich_cluster_redundancy=True)
    c = next(c for c in snap.resources["clusters"] if c["cluster_name"] == "GLM-5.1-FP8")
    # 富集：当前负载 = 最新整点自建 60,000,000/60 = 1,000,000（覆盖监控原始实跑）
    assert c["current_tpm"] == 1_000_000
    # 冗余 = 200万 - 100万 = 100万；冗余机器 = 100万/100万 = 1
    assert c["current_redundant_tpm"] == 1_000_000
    assert c["current_redundant_machines"] == 1
    assert snap.resources["total_current_redundant_tpm"] == 1_000_000


def test_no_enrich_uses_monitor_load(app):
    _seed(app)
    # 不富集：当前负载取监控实跑（50万），冗余 = 200万 - 50万 = 150万
    snap = build_snapshot("realtime", demand_items=[], enrich_cluster_redundancy=False)
    c = next(c for c in snap.resources["clusters"] if c["cluster_name"] == "GLM-5.1-FP8")
    assert c["current_tpm"] == 500_000
    assert c["current_redundant_tpm"] == 1_500_000
