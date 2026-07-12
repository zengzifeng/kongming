"""PolicyReportService：从持久化的 Policy.summary_json + PolicyRun.input_snapshot_json
汇结构化报告 payload，验证元/天折算、单TPM收入、集群利用率、以及收益对账。"""
from app.extensions import db
from app.models import MonitorConsumer, Policy, PolicyRun
from app.services.policy_report_service import PolicyReportService, Y


def _seed_policy(app):
    db.session.add(MonitorConsumer(ai_consumer="报告客户", customer_code="C0300", customer_name="报告客户", level="A"))
    db.session.flush()

    demands = [{
        "report_id": "USG-C0300-m", "customer_code": "C0300", "model_name": "m",
        "expected_tpm": 100.0, "expected_rpm": 0.0, "discount_rate": 0.8,
        "input_ratio": 2.0, "cache_hit_rate": 0.4, "current_self_ratio": 0.2,
        "current_vendor_ratios": {"v": 0.8}, "quality_score": 0.0,
        "tpm_series": [["2026-07-07T02:00:00", 100.0],
                       ["2026-07-07T14:00:00", 300.0],
                       ["2026-07-07T22:00:00", 100.0]],
    }]
    snapshot = {
        "algorithm": "time_period", "demands": demands,
        "resources": {"clusters": [
            {"cluster_name": "self-m", "deployed_model": "m", "machine_count": 5, "tpm_per_machine": 100.0},
        ]},
        "vendors": [{"vendor": "v", "model": "m", "unit_price": 0.001}],
        "params": {"model_prices": {
            "m": {"input_cache_hit_price": 0.0002, "input_cache_miss_price": 0.001, "output_price": 0.002}}},
    }
    gain = 1_000_000.0  # 积分口径；expected_revenue_gain 设为同值 → Σattribution 应对账
    summary = {
        "watermark_changes": [{
            "customer_code": "C0300", "model": "m", "watermark_self_tpm": 200.0,
            "current_self_ratio": 0.2, "customer_revenue_gain": gain, "fallback_vendor": "v",
        }],
        "self_revenue_before": 4_000_000.0,
        "self_revenue_after": 5_000_000.0,
        "expected_revenue_gain": gain,
        "machines_before": {"self-m": 5}, "machines_after": {"self-m": 5},
        "peak_feasibility": {"m": {"peak_demand": 300.0, "self_cap": 500.0, "vendor_cap": 100000.0,
                                   "total_cap": 100500.0, "slack": 100200.0, "feasible": True}},
        "model_rebalance": {
            "moves": [{"from_cluster": "self-A", "to_cluster": "self-m", "model": "m",
                       "machine_count": 1, "from_tpm_per_machine": 100.0, "to_tpm_per_machine": 100.0,
                       "gain": 200_000.0}],
            "self_revenue_before": 4_800_000.0, "self_revenue_after": 5_000_000.0,
            "extra_revenue_gain": 200_000.0,
            "per_model": [{"model": "m", "swm_before": 150.0, "swm_after": 200.0,
                           "shared_cap_before": 400.0, "shared_cap_after": 500.0}],
            "per_cluster": [{"cluster_name": "self-m", "model": "m", "rate": 100.0, "dedicated": False,
                             "machines_before": 4, "machines_after": 5, "delta_machines": 1,
                             "role": "receive",
                             "gainers": [{"customer_code": "C0300", "model": "m",
                                          "watermark_before": 150.0, "watermark_after": 200.0, "delta": 50.0}],
                             "losers": []}],
            "customer_watermark_delta": [],
        },
    }
    run = PolicyRun(run_no="PRTEST", algorithm="time_period", input_snapshot_json=snapshot)
    db.session.add(run)
    db.session.flush()
    policy = Policy(policy_run_id=run.id, policy_no="PTEST", algorithm="time_period",
                    summary_json=summary, expected_revenue_gain=gain)
    db.session.add(policy)
    db.session.flush()
    return policy


def test_report_kpis_and_reconciliation(app):
    policy = _seed_policy(app)
    rep = PolicyReportService().build(policy.id)
    # KPI 元/天
    assert abs(rep["kpis"]["expected_revenue_gain_yuan_day"] - 1_000_000.0 * Y) < 1e-6
    assert abs(rep["kpis"]["self_revenue_before_yuan_day"] - 4_000_000.0 * Y) < 1e-6
    # 逐调整收益对账：Σattribution 收益 ≈ KPI 提升
    total = sum(a["gain_yuan_day"] for a in rep["attributions"])
    assert abs(total - rep["kpis"]["expected_revenue_gain_yuan_day"]) < 1e-6


def test_report_attribution_and_unit_example(app):
    policy = _seed_policy(app)
    rep = PolicyReportService().build(policy.id)
    assert len(rep["attributions"]) == 1
    a = rep["attributions"][0]
    assert a["customer"] == "报告客户"          # code→name 映射
    assert a["model"] == "m"
    assert a["unit_self_revenue"] > 0            # 单TPM收入(元/百万token)
    assert abs(a["gain_yuan_day"] - 1_000_000.0 * Y) < 1e-6
    # 单TPM收入示例：公式代入自洽，且与 attribution 的 unit 一致
    ex = rep["unit_example"]
    assert ex is not None
    assert abs(ex["term_hit"] + ex["term_miss"] + ex["term_out"] - ex["weighted_list_price"]) < 1e-9
    assert abs(ex["weighted_list_price"] * ex["discount_rate"] - ex["unit_self_revenue"]) < 1e-9
    assert abs(ex["unit_self_revenue"] - a["unit_self_revenue"]) < 1e-6


def test_report_cluster_utilization_and_rebalance(app):
    policy = _seed_policy(app)
    rep = PolicyReportService().build(policy.id)
    cu = {r["model"]: r for r in rep["cluster_utilization"]}
    assert "m" in cu
    assert cu["m"]["capacity_after"] == 500.0            # 5 台 × 100
    assert cu["m"]["shared_occupancy"] == 200.0 / 500.0  # Σ水位线 / 共享容量
    # 模型级再平衡：元/天 折算 + 客户名 + 流向聚合
    rb = rep["model_rebalance"]
    assert abs(rb["extra_gain_yuan_day"] - 200_000.0 * Y) < 1e-6
    assert rb["flows"] and rb["flows"][0]["from_cluster"] == "self-A"
    assert rb["per_cluster"][0]["gainers"][0]["customer"] == "报告客户"
