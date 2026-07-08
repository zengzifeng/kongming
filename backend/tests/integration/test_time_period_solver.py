from datetime import datetime, timezone

from app.algorithms.base import DemandSnapshotItem, PolicyInputSnapshot
from app.algorithms.time_period_solver import TimePeriodSolver


def _series(peak, low_factor=0.3):
    """3 点时序：低谷 / 峰值 / 低谷。"""
    return [
        ("2026-07-01T02:00:00+00:00", peak * low_factor),
        ("2026-07-01T14:00:00+00:00", peak),
        ("2026-07-01T22:00:00+00:00", peak * low_factor),
    ]


def _snapshot(demands, clusters=None, vendors=None, params=None):
    return PolicyInputSnapshot(
        captured_at=datetime.now(timezone.utc),
        algorithm="time_period",
        demands=demands,
        resources={"clusters": clusters or [
            {"cluster_name": "self-qwen", "deployed_model": "qwen2.5-72b", "machine_count": 4,
             "tpm_per_machine": 50_000, "current_redundant_tpm": 100_000, "current_redundant_machines": 2},
            {"cluster_name": "self-deepseek", "deployed_model": "deepseek-v3", "machine_count": 4,
             "tpm_per_machine": 40_000, "current_redundant_tpm": 100_000, "current_redundant_machines": 2},
        ]},
        monitoring={},
        vendors=vendors or [
            {"vendor": "aliyun", "model": "qwen2.5-72b", "quota_tpm": 500_000, "unit_cost": 0.0003, "unit_price": 0.0010},
            {"vendor": "volc", "model": "deepseek-v3", "quota_tpm": 500_000, "unit_cost": 0.0002, "unit_price": 0.0009},
        ],
        params=params or {"model_prices": {
            "qwen2.5-72b": {"input_cache_hit_price": 0.0002, "input_cache_miss_price": 0.0010, "output_price": 0.0015},
            "deepseek-v3": {"input_cache_hit_price": 0.0002, "input_cache_miss_price": 0.0009, "output_price": 0.0012},
        }},
    )


def _demand(report_id, customer, model="qwen2.5-72b", peak=100_000, discount=0.8, self_ratio=0.2):
    return DemandSnapshotItem(
        report_id=report_id, customer_code=customer, model_name=model,
        expected_tpm=peak, expected_rpm=100, discount_rate=discount,
        input_ratio=1.5, cache_hit_rate=0.3,
        current_self_ratio=self_ratio, current_vendor_ratios={"aliyun": 1 - self_ratio},
        tpm_series=_series(peak),
    )


def test_time_period_gain_positive_and_machines_conserved():
    snap = _snapshot([_demand("d1", "c1", peak=150_000, self_ratio=0.2)])
    result = TimePeriodSolver().solve(snap)
    s = result.summary
    assert s["expected_revenue_gain"] > 0
    assert s["self_revenue_after"] > s["self_revenue_before"]
    # 机器总量守恒
    assert s["machines_total_before"] == s["machines_total_after"]


def test_time_period_watermark_is_time_varying():
    # 峰值 400k 超过自建容量(4×50k=200k)，低谷 120k 在容量内 -> 低谷 self 占比应更高
    snap = _snapshot([_demand("peaky", "c1", peak=400_000, self_ratio=0.1)])
    result = TimePeriodSolver().solve(snap)
    wm = result.summary["watermark_changes"][0]
    ratios = [slot["self_ratio"] for slot in wm["slots"]]
    peak_slot = max(wm["slots"], key=lambda x: x["tpm"])
    trough_slot = min(wm["slots"], key=lambda x: x["tpm"])
    assert trough_slot["self_ratio"] > peak_slot["self_ratio"]  # 低谷自建占比更高
    assert peak_slot["vendor_tpm"] > 0                          # 峰值溢出到三方
    assert len(ratios) == 3


def test_time_period_shared_capacity_not_exceeded():
    # 两客户共享同一 qwen 集群池(容量 200k)，峰值合计 300k；无其它集群可供出机器
    # -> 自建合计受物理容量 200k 约束，不得超出（低密度客户被限流）
    clusters = [
        {"cluster_name": "self-qwen", "deployed_model": "qwen2.5-72b", "machine_count": 4,
         "tpm_per_machine": 50_000, "current_redundant_tpm": 200_000, "current_redundant_machines": 0},
    ]
    snap = _snapshot([
        _demand("hi", "c-hi", peak=150_000, discount=0.9, self_ratio=0.0),
        _demand("lo", "c-lo", peak=150_000, discount=0.5, self_ratio=0.0),
    ], clusters=clusters)
    result = TimePeriodSolver().solve(snap)
    wms = {w["report_id"]: w for w in result.summary["watermark_changes"]}
    n = len(next(iter(wms.values()))["slots"])
    cap = 4 * 50_000
    for ti in range(n):
        total_self = sum(w["slots"][ti]["self_tpm"] for w in wms.values())
        assert total_self <= cap + 1e-6


def test_time_period_dedicated_cluster_and_reserve_carried_over():
    # KSCC 专属集群只服务 kscc；供出机器时须保留 >=2 台
    clusters = [
        {"cluster_name": "GLM-KSCC", "deployed_model": "glm", "machine_count": 3, "tpm_per_machine": 70_000,
         "current_redundant_tpm": 200_000, "current_redundant_machines": 3, "primary_customer": "kscc"},
        {"cluster_name": "GLM-main", "deployed_model": "glm", "machine_count": 2, "tpm_per_machine": 20_000,
         "current_redundant_tpm": 0, "current_redundant_machines": 0, "primary_customer": "vip"},
    ]
    vendors = [{"vendor": "v", "model": "glm", "quota_tpm": 9_000_000, "unit_cost": 0.0002, "unit_price": 0.0010}]
    params = {"model_prices": {"glm": {"input_cache_hit_price": 0.0002, "input_cache_miss_price": 0.0010, "output_price": 0.0015}}}
    snap = _snapshot([
        DemandSnapshotItem(report_id="vip", customer_code="vip", model_name="glm",
                           expected_tpm=300_000, expected_rpm=0, discount_rate=0.9,
                           input_ratio=1.0, cache_hit_rate=0.3,
                           current_self_ratio=0.0, current_vendor_ratios={"v": 1.0},
                           tpm_series=_series(300_000)),
    ], clusters=clusters, vendors=vendors, params=params)
    result = TimePeriodSolver().solve(snap)
    after = result.diagnostics["machines_after"]
    assert after["GLM-KSCC"] >= 2  # KSCC 至少保留 2 台
    # vip 不能占用 KSCC(专属 kscc) 容量：其 self 完全来自 GLM-main + 腾挪
    assert result.summary["machines_total_before"] == result.summary["machines_total_after"]


# ---- 原生/接收冗余分账 的回归用例 ----

def _multi_snapshot(demands, clusters, models, vendor_quota=9_000_000):
    vendors = [{"vendor": "tp", "model": m, "quota_tpm": vendor_quota,
                "unit_cost": 0.0002, "unit_price": 0.0010} for m in models]
    prices = {m: {"input_cache_hit_price": 0.0002, "input_cache_miss_price": 0.0010,
                  "output_price": 0.0010} for m in models}
    return _snapshot(demands, clusters=clusters, vendors=vendors, params={"model_prices": prices})


def _tp_dem(report_id, model, peak, discount, self_ratio=0.0):
    return DemandSnapshotItem(
        report_id=report_id, customer_code=report_id, model_name=model,
        expected_tpm=peak, expected_rpm=0, discount_rate=discount,
        input_ratio=1.0, cache_hit_rate=0.0, current_self_ratio=self_ratio,
        current_vendor_ratios={"tp": max(1 - self_ratio, 0.0)}, tpm_series=_series(peak),
    )


def _tp_cl(name, model, rate, redundant_tpm, redundant_machines, machine_count=4):
    return {"cluster_name": name, "deployed_model": model, "machine_count": machine_count,
            "tpm_per_machine": rate, "current_redundant_tpm": redundant_tpm,
            "current_redundant_machines": redundant_machines}


def test_time_period_no_double_count_same_model_donor():
    # 双重计数修复：两个同模型集群都可服务某客户（其冗余已计入 free），其中一个又有可供出机器。
    # 旧代码把该集群冗余既算作 servable free、又算作腾挪新增（free += added）→ 虚增容量。
    # 新代码腾挪后重算 free（native 扣、received 加）得净零，自建合计不得超过真实物理容量。
    clusters = [
        _tp_cl("glm-A", "glm", 50_000, 200_000, 0),  # 全空闲，无可供机器
        _tp_cl("glm-B", "glm", 50_000, 200_000, 4),  # 全空闲，4 台可供
    ]
    # 需求 500k > 真实物理空闲合计 400k
    result = TimePeriodSolver().solve(_multi_snapshot(
        [_tp_dem("big", "glm", 500_000, 0.9)], clusters, ["glm"]))
    wms = result.summary["watermark_changes"]
    cap = 2 * 4 * 50_000  # 两簇满容量合计 = 400k（机器守恒，总容量不变）
    n = len(wms[0]["slots"])
    for ti in range(n):
        total_self = sum(w["slots"][ti]["self_tpm"] for w in wms)
        assert total_self <= cap + 1e-6  # 无虚增：自建合计不超过真实物理容量


def test_time_period_allows_donor_to_also_receive():
    # 倒手放开：glm-A 先把唯一空闲机器供给高密度 modelB 客户(A→B)，
    # 随后 glm-A 自己的 modelA 客户靠 clC→A 承接。旧 donor/receiver 互斥会阻断。
    clusters = [
        _tp_cl("clA", "modelA", 50_000, 50_000, 1),
        _tp_cl("clB", "modelB", 50_000, 0, 0),
        _tp_cl("clC", "modelC", 50_000, 50_000, 1),
    ]
    result = TimePeriodSolver().solve(_multi_snapshot([
        _tp_dem("hd_B", "modelB", 50_000, 0.9),
        _tp_dem("own_A", "modelA", 50_000, 0.5),
    ], clusters, ["modelA", "modelB", "modelC"]))
    accepted = {a["report_id"] for a in result.summary["accepted_customers"]}
    moves = result.summary["node_moves"]
    froms = {m["from_cluster"] for m in moves}
    tos = {m["to_cluster"] for m in moves}
    assert "hd_B" in accepted and "own_A" in accepted
    assert "clA" in froms and "clA" in tos  # clA 既供出又接收


def test_time_period_commit_then_donate_blocked():
    # 分账安全：高密度客户先 commit 吃空 clA 的原生冗余后，clA 虽仍有 donatable 机器，
    # 但 native_free=0 → 不得被当作源供出（movable=min(donatable, native_free//rate)=0）。
    clusters = [
        _tp_cl("clA", "modelA", 50_000, 100_000, 2),  # 2 台原生空闲
        _tp_cl("clC", "modelC", 50_000, 0, 0),         # 跨模型客户本集群无冗余
    ]
    result = TimePeriodSolver().solve(_multi_snapshot([
        _tp_dem("drain_A", "modelA", 100_000, 0.9),   # 高密度，先吃空 clA 原生冗余
        _tp_dem("wants_C", "modelC", 100_000, 0.5),   # 想从 clA 腾挪，但 clA 已被占用
    ], clusters, ["modelA", "modelC"]))
    froms = {m["from_cluster"] for m in result.summary["node_moves"]}
    assert "clA" not in froms  # clA 原生已被 commit 占用，不得再供出

