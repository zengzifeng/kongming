"""策略计算输入 clusters 改为「监控+容量+provider」组装：验证 DB 读取、消费方不破坏。"""
from datetime import timedelta

from app.algorithms.realtime_solver import RealtimeSolver
from app.algorithms.snapshot import build_snapshot
from app.extensions import db
from app.integrations import resource_client
from app.models import Demand, ModelListPrice, VendorQuota
from app.services.dashboard_service import DashboardService
from app.utils.time import utcnow

from tests.conftest import seed_cluster


def test_resource_client_mock_fallback_when_no_monitor_data(app):
    # 无监控数据 + mock 模式：snapshot() 回退合成集群（dev/测试便利），每个都带冗余机器数。
    snap = resource_client().snapshot()
    assert len(snap.clusters) == 3
    for c in snap.clusters:
        assert hasattr(c, "current_redundant_machines")


def test_build_snapshot_clusters_come_from_monitor(app):
    # 集群名 = 部署模型名（大小写不敏感匹配求解器需求）。容量 4×50k=200k，实跑 100k → 冗余 2 台。
    seed_cluster("qwen2.5-72b", "qwen2.5-72b", machine_count=4, tpm_per_machine=50_000,
                 current_tpm=100_000, provider="ksyun-qwen")
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
    assert "qwen2.5-72b" in names
    cl = next(c for c in snap.resources["clusters"] if c["cluster_name"] == "qwen2.5-72b")
    assert cl["current_redundant_machines"] == 2
    result = RealtimeSolver().solve(snap)
    assert result.summary["accepted_customers"]


def test_monitor_redundant_machines_drives_node_move(app):
    # 冗余台数（容量−实跑推导）应驱动 _donatable_machines：高密度客户靠腾挪承接。
    now = utcnow()
    # 目标集群满载无冗余；donor 集群 4 台、实跑 100k → 冗余 100k=2 台可供。
    seed_cluster("modelM", "modelM", machine_count=2, tpm_per_machine=50_000, current_tpm=100_000)
    seed_cluster("modelN", "modelN", machine_count=4, tpm_per_machine=50_000, current_tpm=100_000)
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
    assert result.summary["node_moves"], "冗余台数未驱动腾挪"
    assert result.summary["node_moves"][0]["from_cluster"] == "modelN"


def test_dashboard_resources_reflects_monitor(app):
    # 消费方不破坏：dashboard.resources() 返回组装后的集群（关注集群名 GLM-5.2 在默认清单内）。
    seed_cluster("GLM-5.2", "glm-5.2", machine_count=8, tpm_per_machine=2_600_000,
                 current_tpm=5_000_000, provider="ksyun-glm5.2-qy-10070")
    db.session.commit()
    data = DashboardService().resources()
    assert data["clusters"] and len(data["clusters"]) == 1
    assert data["total_capacity_tpm"] > 0
    sample = data["clusters"][0]
    for k in ("tpm_per_machine", "total_capacity_tpm", "current_redundant_tpm",
              "current_redundant_machines", "provider"):
        assert k in sample
