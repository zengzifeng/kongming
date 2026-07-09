"""策略计算输入 clusters 改为 DB 驱动：验证 seed 回退、DB 读取、消费方不破坏。"""
from datetime import timedelta

from app.algorithms.realtime_solver import RealtimeSolver
from app.algorithms.snapshot import build_snapshot
from app.extensions import db
from app.integrations import resource_client
from app.models import ClusterResource, Demand, ModelListPrice, VendorQuota
from app.services.dashboard_service import DashboardService
from app.utils.time import utcnow


def test_resource_client_seeds_empty_db(app):
    # 空库 + mode==mock：snapshot() 应写入 3 条 mock 集群并返回，且每个都带 current_redundant_machines。
    assert db.session.query(ClusterResource).count() == 0
    snap = resource_client().snapshot()
    assert len(snap.clusters) == 3
    for c in snap.clusters:
        assert hasattr(c, "current_redundant_machines")
        assert c.current_redundant_machines == c.idle_redundant_machines
    # 已落库
    assert db.session.query(ClusterResource).count() == 3


def _seed_cluster(name, model, machines, rate, red_tpm, red_machines, primary=None, day=None):
    db.session.add(ClusterResource(
        snapshot_date=day or utcnow().date(),
        cluster_name=name, deployed_model=model, primary_customer=primary,
        machine_count=machines, tpm_per_machine=rate, total_capacity_tpm=machines * rate,
        current_tpm=0, current_redundant_tpm=red_tpm, current_redundant_machines=red_machines,
    ))


def test_build_snapshot_clusters_come_from_db(app):
    # 手工插入集群 → build_snapshot 的 resources.clusters 应来自 DB，且键含 current_redundant_machines。
    _seed_cluster("db-qwen", "qwen2.5-72b", 4, 50_000, 100_000, 2)
    now = utcnow()
    db.session.add(VendorQuota(
        vendor="tp-qwen", model="qwen2.5-72b", quota_tpm=500_000,
        unit_cost=0.0003, unit_price=0.0010, effective_from=now - timedelta(days=1),
    ))
    db.session.add(ModelListPrice(
        model_name="qwen2.5-72b", input_cache_hit_price=0.0002,
        input_cache_miss_price=0.0010, output_price=0.0015,
        effective_from=now - timedelta(days=1),
    ))
    d = Demand(report_id="R-DBCL", model_name="qwen2.5-72b", expected_tpm=50_000,
               discount_rate=0.8, current_self_ratio=0.1,
               current_vendor_ratios={"tp-qwen": 0.9}, input_ratio=1.5, cache_hit_rate=0.3)
    db.session.add(d)
    db.session.flush()

    snap = build_snapshot("realtime", [d])
    names = {c["cluster_name"] for c in snap.resources["clusters"]}
    assert "db-qwen" in names
    cl = next(c for c in snap.resources["clusters"] if c["cluster_name"] == "db-qwen")
    assert cl["current_redundant_machines"] == 2
    # 求解器能吃这份 DB 快照并产出结果
    result = RealtimeSolver().solve(snap)
    assert result.summary["accepted_customers"]


def test_db_cluster_redundant_machines_drives_node_move(app):
    # DB 里的 current_redundant_machines 应真正驱动 _donatable_machines：高密度客户靠腾挪承接。
    now = utcnow()
    # 目标集群无冗余无机器；donor 集群有 2 台可供机器（current_redundant_machines=2）。
    _seed_cluster("tgt", "modelM", 2, 50_000, 0, 0)
    _seed_cluster("donor", "modelN", 4, 50_000, 100_000, 2)
    for m in ("modelM", "modelN"):
        db.session.add(VendorQuota(vendor=f"tp-{m}", model=m, quota_tpm=10_000_000,
                                   unit_cost=0.0002, unit_price=0.0010,
                                   effective_from=now - timedelta(days=1)))
        db.session.add(ModelListPrice(model_name=m, input_cache_hit_price=0.0002,
                                      input_cache_miss_price=0.0010, output_price=0.0010,
                                      effective_from=now - timedelta(days=1)))
    d = Demand(report_id="R-HD", model_name="modelM", expected_tpm=100_000,
               discount_rate=0.9, current_self_ratio=0.0,
               current_vendor_ratios={"tp-modelM": 1.0}, input_ratio=1.0, cache_hit_rate=0.0)
    db.session.add(d)
    db.session.flush()

    snap = build_snapshot("realtime", [d])
    result = RealtimeSolver().solve(snap)
    assert result.summary["node_moves"], "DB 的 current_redundant_machines 未驱动腾挪"
    assert result.summary["node_moves"][0]["from_cluster"] == "donor"


def test_dashboard_resources_still_works_with_seed(app):
    # 消费方不破坏：dashboard.resources() 在空库 seed 回退下仍返回完整结构。
    data = DashboardService().resources()
    assert data["clusters"] and len(data["clusters"]) == 3
    assert data["total_capacity_tpm"] > 0
    # clusters_payload 仍含全部展示字段
    sample = data["clusters"][0]
    for k in ("peak_tpm_idle", "idle_redundant_machines", "busy_redundant_machines", "current_redundant_tpm"):
        assert k in sample
