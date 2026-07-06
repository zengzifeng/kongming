from datetime import datetime, timezone

from app.algorithms.base import DemandSnapshotItem, PolicyInputSnapshot
from app.algorithms.realtime_solver import RealtimeSolver


def _snapshot(demands, clusters=None, vendors=None, params=None):
    return PolicyInputSnapshot(
        captured_at=datetime.now(timezone.utc),
        algorithm="realtime",
        demands=demands,
        resources={
            "clusters": clusters or [
                {
                    "cluster_name": "self-qwen",
                    "deployed_model": "qwen2.5-72b",
                    "machine_count": 4,
                    "tpm_per_machine": 50_000,
                    "current_redundant_tpm": 100_000,
                    "current_redundant_machines": 2,
                },
                {
                    "cluster_name": "self-deepseek",
                    "deployed_model": "deepseek-v3",
                    "machine_count": 4,
                    "tpm_per_machine": 40_000,
                    "current_redundant_tpm": 100_000,
                    "current_redundant_machines": 2,
                },
            ],
        },
        monitoring={},
        vendors=vendors or [
            {
                "vendor": "aliyun",
                "model": "qwen2.5-72b",
                "quota_tpm": 500_000,
                "unit_cost": 0.0003,
                "unit_price": 0.0010,
            },
            {
                "vendor": "volc",
                "model": "deepseek-v3",
                "quota_tpm": 500_000,
                "unit_cost": 0.0002,
                "unit_price": 0.0009,
            },
        ],
        params=params or {
            "model_prices": {
                "qwen2.5-72b": {
                    "input_cache_hit_price": 0.0002,
                    "input_cache_miss_price": 0.0010,
                    "output_price": 0.0015,
                },
                "deepseek-v3": {
                    "input_cache_hit_price": 0.0002,
                    "input_cache_miss_price": 0.0009,
                    "output_price": 0.0012,
                },
            },
        },
    )


def _demand(report_id, customer, model="qwen2.5-72b", tpm=50_000, discount=0.8, quality=0.0):
    return DemandSnapshotItem(
        report_id=report_id,
        customer_code=customer,
        model_name=model,
        expected_tpm=tpm,
        expected_rpm=100,
        discount_rate=discount,
        input_ratio=0.6,
        output_ratio=0.4,
        cache_hit_rate=0.3,
        current_self_ratio=0.1,
        current_vendor_ratios={"aliyun": 0.9},
        quality_score=quality,
    )


def test_realtime_prefers_high_revenue_customer():
    snapshot = _snapshot([
        _demand("low", "customer-low", tpm=100_000, discount=0.5),
        _demand("high", "customer-high", tpm=100_000, discount=0.9),
    ], clusters=[
        {
            "cluster_name": "self-qwen",
            "deployed_model": "qwen2.5-72b",
            "machine_count": 2,
            "tpm_per_machine": 50_000,
            "current_redundant_tpm": 100_000,
            "current_redundant_machines": 0,
        }
    ])

    result = RealtimeSolver().solve(snapshot)

    accepted = result.summary["accepted_customers"]
    # 高收益客户优先，并只占用其三方待回收部分(90k = 100k × (1-0.1))
    assert accepted[0]["report_id"] == "high"
    high = next(item for item in accepted if item["report_id"] == "high")
    assert high["incremental_tpm_self"] == 90_000
    # 修复 P4 后：high 吃满缺口仍剩 10k 冗余，应分给次优的 low（部分承接，不浪费冗余）
    low = next((item for item in accepted if item["report_id"] == "low"), None)
    assert low is not None and low["incremental_tpm_self"] == 10_000


def test_realtime_moves_unprofitable_vendor_customer_to_self():
    # 修复 M3：售卖折扣(0.2) < 采购折扣(0.4) 时，留在三方是亏的，应“必须全挪自建”而非拒收
    snapshot = _snapshot(
        [_demand("must-move", "customer", discount=0.2)],
        vendors=[{
            "vendor": "aliyun",
            "model": "qwen2.5-72b",
            "quota_tpm": 500_000,
            "unit_cost": 0.0004,
            "unit_price": 0.0010,
        }],
    )

    result = RealtimeSolver().solve(snapshot)

    accepted = result.summary["accepted_customers"]
    assert any(item["report_id"] == "must-move" for item in accepted)
    watermark = next(w for w in result.summary["watermark_changes"] if w["report_id"] == "must-move")
    assert watermark["to_self_ratio"] == 1.0  # 全部挪到自建，止住三方亏损


def test_realtime_emits_watermark_and_node_move():
    snapshot = _snapshot([
        _demand("move", "vip", tpm=60_000, quality=10),
    ], clusters=[
        {
            "cluster_name": "self-qwen",
            "deployed_model": "qwen2.5-72b",
            "machine_count": 2,
            "tpm_per_machine": 50_000,
            "current_redundant_tpm": 0,
            "current_redundant_machines": 0,
        },
        {
            "cluster_name": "self-deepseek",
            "deployed_model": "deepseek-v3",
            "machine_count": 4,
            "tpm_per_machine": 40_000,
            "current_redundant_tpm": 100_000,
            "current_redundant_machines": 2,
        },
    ])

    result = RealtimeSolver().solve(snapshot)

    action_types = [action.action_type for action in result.actions]
    assert "node_move" in action_types
    assert "watermark_adjust" in action_types
    assert result.summary["node_moves"][0]["machine_count"] == 2
    assert result.summary["watermark_changes"][0]["to_self_ratio"] == 1.0
