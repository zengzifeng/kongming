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


def test_time_period_cross_model_move_and_conservation():
    # 跨模型搬运：modelB 目标满容量 0（真缺）→ 从空闲的 modelC 集群搬机器重部署为 modelB。
    # 机器总量守恒；modelB 客户被接纳。
    clusters = [
        _tp_cl("clB", "modelB", 50_000, 0, 0, machine_count=0),   # 目标：满容量 0
        _tp_cl("clC", "modelC", 50_000, 100_000, 2),              # 空闲 modelC，可跨模型供出
    ]
    result = TimePeriodSolver().solve(_multi_snapshot(
        [_tp_dem("hd_B", "modelB", 80_000, 0.9)], clusters, ["modelB", "modelC"]))
    moves = result.summary["node_moves"]
    accepted = {a["report_id"] for a in result.summary["accepted_customers"]}
    assert any(m["from_cluster"] == "clC" and m["to_cluster"] == "clB" for m in moves)  # 跨模型搬运
    assert "hd_B" in accepted
    assert result.summary["machines_total_before"] == result.summary["machines_total_after"]


def test_time_period_no_same_model_rate_arbitrage():
    # 禁同模型 rate 套利：低速率同模型源必须是"对本客户不可服务"（专属簇）才会成为候选源，
    # 再被套利护栏挡掉（同模型 + src_rate<target_rate）。同时给一个跨模型源证明它可被正常选用。
    clusters = [
        # 目标 hi：共享 glm、高速率、满容量小 → 触发搬运
        {"cluster_name": "hi", "deployed_model": "glm", "machine_count": 1, "tpm_per_machine": 80_000,
         "current_redundant_tpm": 80_000, "current_redundant_machines": 0},
        # lo-KSCC：同模型 glm、低速率、专属 kscc-cust（对 c 不可服务）、有空闲 → 若无护栏会被套利搬来
        {"cluster_name": "lo-KSCC", "deployed_model": "glm", "machine_count": 4, "tpm_per_machine": 50_000,
         "current_redundant_tpm": 150_000, "current_redundant_machines": 3, "primary_customer": "kscc-cust"},
        # kimi-idle：跨模型空闲源（应被正常选用）
        {"cluster_name": "kimi-idle", "deployed_model": "kimi", "machine_count": 3, "tpm_per_machine": 50_000,
         "current_redundant_tpm": 150_000, "current_redundant_machines": 3},
    ]
    result = TimePeriodSolver().solve(_multi_snapshot(
        [_tp_dem("c", "glm", 200_000, 0.9)], clusters, ["glm", "kimi"]))
    froms = {m["from_cluster"] for m in result.summary["node_moves"]}
    assert "lo-KSCC" not in froms   # 同模型低速率专属源：套利被禁
    assert "kimi-idle" in froms     # 跨模型源：正常选用


def test_time_period_no_net_zero_same_model_churn():
    # 净零 churn：同模型同速率共享双簇 + 需求 > 合计容量。两簇都是本客户可服务集群、已计入 free，
    # 在其间搬机器对本客户净零无益 → 不应产生该搬运。
    clusters = [
        _tp_cl("a", "m", 50_000, 100_000, 2),   # 4×50k=200k
        _tp_cl("b", "m", 50_000, 100_000, 2),   # 4×50k=200k
    ]
    result = TimePeriodSolver().solve(_multi_snapshot(
        [_tp_dem("big", "m", 500_000, 0.9)], clusters, ["m"]))  # 500k > 合计 400k
    moves = result.summary["node_moves"]
    # 不含同模型同速率簇之间的互搬（a<->b），实际应为空
    assert all(not (m["from_cluster"] in ("a", "b") and m["to_cluster"] in ("a", "b")) for m in moves)



def test_time_period_donation_bounded_by_physical_idle():
    # 物理供出护栏：源簇 donatable=2 台，但 current_redundant_tpm 只有 1 台份 → 只能供 1 台。
    clusters = [
        _tp_cl("clT", "modelT", 50_000, 0, 0, machine_count=0),   # 目标：满容量 0
        # clS：4 台，2 台标记空闲，但原生空闲 TPM 只有 50k（=1 台份）→ movable=min(2, 50k//50k)=1
        _tp_cl("clS", "modelS", 50_000, 50_000, 2),
    ]
    result = TimePeriodSolver().solve(_multi_snapshot(
        [_tp_dem("c", "modelT", 200_000, 0.9)], clusters, ["modelT", "modelS"]))
    moved = sum(m["machine_count"] for m in result.summary["node_moves"] if m["from_cluster"] == "clS")
    assert moved <= 1  # 受物理原生空闲 TPM（1 台份）限制，最多搬 1 台



def test_time_period_opportunity_cost_prefers_idle_source():
    # 机会成本选源：hd_B 的目标 clB 满容量为 0（真缺），需从别处搬机器。
    # clA 有自己的高价值 modelA 客户（机会成本高），clC 完全空闲（机会成本=0）→ 应从 clC 供出、放过 clA。
    clusters = [
        _tp_cl("clB", "modelB", 50_000, 0, 0, machine_count=0),   # 目标：满容量 0 → 触发搬运
        _tp_cl("clA", "modelA", 50_000, 50_000, 1),   # 1 台空闲，但有 own_A 争抢（机会成本高）
        _tp_cl("clC", "modelC", 50_000, 50_000, 1),   # 1 台空闲，无客户（机会成本 0）
    ]
    result = TimePeriodSolver().solve(_multi_snapshot([
        _tp_dem("hd_B", "modelB", 50_000, 0.9),
        _tp_dem("own_A", "modelA", 50_000, 0.9),       # 高价值，占住 clA 的机会成本
    ], clusters, ["modelA", "modelB", "modelC"]))
    froms = {m["from_cluster"] for m in result.summary["node_moves"]}
    assert "clC" in froms and "clA" not in froms  # 优先空闲源，放过有价值需求的 clA



def test_time_period_commit_then_donate_blocked():
    # 已删除：旧“commit 吃 native_free 后不得供出”前提在满容量口径下不复存在
    # （commit 已改为 reserve、不碰 native_free）。物理供出护栏改由
    # test_time_period_donation_bounded_by_physical_idle 覆盖。
    pass


# ---- Q1：边际面积注水（削峰承接更多常态面积）----

def _cl_single(cap_machines=2, rate=50_000, redundant=100_000):
    return {"cluster_name": "c", "deployed_model": "m", "machine_count": cap_machines,
            "tpm_per_machine": rate, "current_redundant_tpm": redundant, "current_redundant_machines": 0}


def _dem_series(rid, vals, discount=0.9):
    return DemandSnapshotItem(
        report_id=rid, customer_code=rid, model_name="m", expected_tpm=max(vals), expected_rpm=0,
        discount_rate=discount, input_ratio=1.0, cache_hit_rate=0.0, current_self_ratio=0.0,
        current_vendor_ratios={"tp": 1.0}, tpm_series=_series24(vals),
    )


def _series24(vals):
    base = datetime(2026, 7, 1, tzinfo=timezone.utc)
    return [(base.replace(hour=h).isoformat(), v) for h, v in enumerate(vals)]


def _mk(demands):
    vendors = [{"vendor": "tp", "model": "m", "quota_tpm": 9_000_000, "unit_cost": 0.0002, "unit_price": 0.0010}]
    prices = {"m": {"input_cache_hit_price": 0.0002, "input_cache_miss_price": 0.0010, "output_price": 0.0010}}
    return PolicyInputSnapshot(
        captured_at=datetime.now(timezone.utc), algorithm="time_period", demands=demands,
        resources={"clusters": [_cl_single()]}, monitoring={}, vendors=vendors, params={"model_prices": prices})


def _area(wm_map, series_map):
    return sum(sum(min(v, wm_map.get(rid, 0)) for v in vals) for rid, vals in series_map.items())


def test_time_period_watermark_shaves_narrow_peak_for_wide_baseline():
    # Q1 核心：容量紧张(100k)。narrow=高窄尖峰(1点100k,其余10k)；wide=矮宽常态(全天60k)，同密度。
    # 边际面积注水应把容量优先给 wide(时点多、面积大)，削 narrow 的尖峰 → 总自建面积 > 旧峰值贪心。
    narrow = [100_000] + [10_000] * 23
    wide = [60_000] * 24
    result = TimePeriodSolver().solve(_mk([_dem_series("narrow", narrow), _dem_series("wide", wide)]))
    wm = {w["report_id"]: w["watermark_self_tpm"] for w in result.summary["watermark_changes"]}
    series_map = {"narrow": narrow, "wide": wide}
    new_area = _area(wm, series_map)
    old_area = _area({"narrow": 100_000, "wide": 0}, series_map)  # 旧：narrow 占满容量、wide 饿死
    assert wm.get("wide", 0) >= wm.get("narrow", 0)   # 常态水位 ≥ 尖峰水位（尖峰被削）
    assert new_area > old_area                         # 总自建面积严格增大


def test_time_period_low_density_not_starved():
    # Q1：容量紧张下低密度常态客户不再被整个饿死（旧密度贪心会给它 0 水位）。
    hi = [70_000] * 24     # 高密度常态
    lo = [70_000] * 24     # 低密度常态
    result = TimePeriodSolver().solve(_mk([
        _dem_series("hi", hi, discount=0.9), _dem_series("lo", lo, discount=0.5)]))
    wm = {w["report_id"]: w["watermark_self_tpm"] for w in result.summary["watermark_changes"]}
    assert wm.get("lo", 0) > 0    # 低密度客户拿到部分水位，非 0


def test_time_period_ample_capacity_no_regression():
    # Q1：容量充裕(Σpeak ≤ cap)时，各客户都注到各自峰值，与旧结果一致（无退化）。
    a = [40_000] * 24
    b = [50_000] * 24     # 合计峰值 90k < 容量 100k
    result = TimePeriodSolver().solve(_mk([_dem_series("a", a), _dem_series("b", b)]))
    wm = {w["report_id"]: w["watermark_self_tpm"] for w in result.summary["watermark_changes"]}
    assert abs(wm.get("a", 0) - 40_000) < 1e-6
    assert abs(wm.get("b", 0) - 50_000) < 1e-6


def test_time_period_spiky_current_self_is_shaved():
    # 削峰优先（无保底）：当前自建本身是突刺时，其突刺部分会被削峰、挖回三方，
    # 把容量让给能产出更多收入面积的宽常态客户。
    # spiky：当前自建比 0.5、需求是尖峰(400k@h0-1, 40k其余)→ 当前自建峰值=200k；密度较低。
    # wide：全天 150k 常态、密度更高。容量 200k 紧张。
    spiky = [400_000, 400_000] + [40_000] * 22
    wide = [150_000] * 24
    clusters = [{"cluster_name": "c", "deployed_model": "m", "machine_count": 4,
                 "tpm_per_machine": 50_000, "current_redundant_tpm": 200_000, "current_redundant_machines": 0}]
    vendors = [{"vendor": "tp", "model": "m", "quota_tpm": 9_000_000, "unit_cost": 0.0002, "unit_price": 0.0010}]
    prices = {"m": {"input_cache_hit_price": 0.0002, "input_cache_miss_price": 0.0010, "output_price": 0.0010}}

    def dem(rid, vals, disc, sr):
        return DemandSnapshotItem(report_id=rid, customer_code=rid, model_name="m", expected_tpm=max(vals),
                                  expected_rpm=0, discount_rate=disc, input_ratio=1.0, cache_hit_rate=0.0,
                                  current_self_ratio=sr, current_vendor_ratios={"tp": max(1 - sr, 0)},
                                  tpm_series=_series24(vals))
    snap = PolicyInputSnapshot(captured_at=datetime.now(timezone.utc), algorithm="time_period",
                               demands=[dem("spiky", spiky, 0.6, 0.5), dem("wide", wide, 0.95, 0.0)],
                               resources={"clusters": clusters}, monitoring={}, vendors=vendors,
                               params={"model_prices": prices})
    result = TimePeriodSolver().solve(snap)
    wm = {w["report_id"]: w["watermark_self_tpm"] for w in result.summary["watermark_changes"]}
    # spiky 当前自建峰值 = 400k×0.5 = 200k；削峰优先下其水位被削到远低于 200k（突刺挖回三方）
    assert wm.get("spiky", 1e9) < 200_000 - 1e-6
    # wide（高密度宽常态）保住其常态水位
    assert wm.get("wide", 0) >= 150_000 - 1e-6
    # 不过订：任一时点自建合计 ≤ 物理容量 200k
    wms = result.summary["watermark_changes"]
    for ti in range(len(wms[0]["slots"])):
        assert sum(w["slots"][ti]["self_tpm"] for w in wms) <= 200_000 + 1e-3


def test_time_period_shaved_customer_loss_counted_in_gain():
    # gain 口径（点4）：被完全削光(wm=0)但原本在自建的客户，其损失必须计入 gain（before 含它），不虚高。
    # winner 高密度、victim 低密度且当前自建 0.5；容量 50k 只够 winner。
    victim = [60_000] * 24
    winner = [60_000] * 24
    clusters = [{"cluster_name": "c", "deployed_model": "m", "machine_count": 1,
                 "tpm_per_machine": 50_000, "current_redundant_tpm": 50_000, "current_redundant_machines": 0}]
    vendors = [{"vendor": "tp", "model": "m", "quota_tpm": 9_000_000, "unit_cost": 0.0002, "unit_price": 0.0010}]
    prices = {"m": {"input_cache_hit_price": 0.0002, "input_cache_miss_price": 0.0010, "output_price": 0.0010}}

    def dem(rid, vals, disc, sr):
        return DemandSnapshotItem(report_id=rid, customer_code=rid, model_name="m", expected_tpm=max(vals),
                                  expected_rpm=0, discount_rate=disc, input_ratio=1.0, cache_hit_rate=0.0,
                                  current_self_ratio=sr, current_vendor_ratios={"tp": max(1 - sr, 0)},
                                  tpm_series=_series24(vals))
    snap = PolicyInputSnapshot(captured_at=datetime.now(timezone.utc), algorithm="time_period",
                               demands=[dem("winner", winner, 0.95, 0.0), dem("victim", victim, 0.3, 0.5)],
                               resources={"clusters": clusters}, monitoring={}, vendors=vendors,
                               params={"model_prices": prices})
    result = TimePeriodSolver().solve(snap)
    wm = {w["report_id"]: w for w in result.summary["watermark_changes"]}
    acc = {a["report_id"] for a in result.summary["accepted_customers"]}
    # victim 被削光：不在 accepted，但因原本在自建，仍出现在 watermark_changes（wm=0，负收益）
    assert "victim" not in acc
    assert "victim" in wm and wm["victim"]["watermark_self_tpm"] < 1e-6
    assert wm["victim"]["customer_revenue_gain"] < 0   # 当前自建被挖回三方 = 负贡献，已计入 gain
    # 含被削客户时仍不过订：after 已把 victim 释放，逐时点 Σself ≤ 容量 50k
    wms = result.summary["watermark_changes"]
    for ti in range(len(wms[0]["slots"])):
        assert sum(w["slots"][ti]["self_tpm"] for w in wms) <= 50_000 + 1e-3








# ---------------- C2. 模型级供需再平衡（跨模型抢机器）----------------
def _rebalance_snapshot():
    """富余模型 modelA(容量 100k、单客户峰值仅 20k) + 紧缺模型 modelB(容量 10k、两客户峰值合计 16k，
    但各自单客户 gap<容量 → _plan_reallocation 逐客户触发不了)。modelB 单TPM收入更高。
    期望：再平衡把 modelA 空转机器挪给 modelB，整体自建收入净增。"""
    clusters = [
        {"cluster_name": "self-A", "deployed_model": "modelA", "machine_count": 10,
         "tpm_per_machine": 10_000, "current_redundant_tpm": 100_000, "current_redundant_machines": 8},
        {"cluster_name": "self-B", "deployed_model": "modelB", "machine_count": 1,
         "tpm_per_machine": 10_000, "current_redundant_tpm": 10_000, "current_redundant_machines": 0},
    ]
    vendors = [
        {"vendor": "va", "model": "modelA", "quota_tpm": 500_000, "unit_cost": 0.0002, "unit_price": 0.0008},
        {"vendor": "vb", "model": "modelB", "quota_tpm": 500_000, "unit_cost": 0.0002, "unit_price": 0.0020},
    ]
    prices = {
        "modelA": {"input_cache_hit_price": 0.0002, "input_cache_miss_price": 0.0005, "output_price": 0.0008},
        "modelB": {"input_cache_hit_price": 0.0002, "input_cache_miss_price": 0.0010, "output_price": 0.0020},
    }

    def dem(rid, model, peak, disc, sr):
        return DemandSnapshotItem(
            report_id=rid, customer_code=rid, model_name=model, expected_tpm=peak, expected_rpm=0,
            discount_rate=disc, input_ratio=1.0, cache_hit_rate=0.0,
            current_self_ratio=sr, current_vendor_ratios={"v": max(1 - sr, 0)},
            tpm_series=_series(peak))

    demands = [
        dem("cA", "modelA", 20_000, 0.5, 0.5),   # 富余模型：峰值 20k << 容量 100k
        # 紧缺模型：高自建比 → 单客户 vendor gap 极小(0.8k)，_plan_reallocation 逐客户装得下不触发；
        # 但两客户峰值同刻叠加 16k > 容量 10k → 水位线削峰。唯有模型级再平衡能补容量。
        dem("cB1", "modelB", 8_000, 0.9, 0.9),
        dem("cB2", "modelB", 8_000, 0.9, 0.9),
    ]
    return demands, clusters, vendors, prices


def _solve_rebalance(enable):
    demands, clusters, vendors, prices = _rebalance_snapshot()
    snap = PolicyInputSnapshot(
        captured_at=datetime.now(timezone.utc), algorithm="time_period",
        demands=demands, resources={"clusters": [dict(c) for c in clusters]},
        monitoring={}, vendors=vendors,
        params={"model_prices": prices, "enable_model_rebalance": enable})
    return TimePeriodSolver().solve(snap)


def test_model_rebalance_off_by_default():
    # 不传 enable_model_rebalance → solver 默认关，无再平衡产物
    demands, clusters, vendors, prices = _rebalance_snapshot()
    snap = PolicyInputSnapshot(
        captured_at=datetime.now(timezone.utc), algorithm="time_period",
        demands=demands, resources={"clusters": [dict(c) for c in clusters]},
        monitoring={}, vendors=vendors, params={"model_prices": prices})
    result = TimePeriodSolver().solve(snap)
    assert result.summary["model_rebalance"] == {}


def test_model_rebalance_moves_surplus_to_constrained_and_gains():
    off = _solve_rebalance(False).summary
    on = _solve_rebalance(True).summary
    rb = on["model_rebalance"]
    # 有再平衡腾挪，且方向是 modelA(富余)→modelB(紧缺)
    assert rb["moves"], "应产生跨模型腾挪"
    assert any(m["from_cluster"] == "self-A" and m["to_cluster"] == "self-B" for m in rb["moves"])
    # 整体自建收入净增（再平衡额外收益为正）
    assert rb["extra_revenue_gain"] > 0
    assert on["self_revenue_after"] > off["self_revenue_after"]
    # 机器总量守恒
    assert on["machines_total_after"] == on["machines_total_before"]
    # 峰值可行性全 OK（不掉量）
    assert all(f["feasible"] for f in on["peak_feasibility"].values())
    # 反洗产能：无集群既供出又接收
    donors = {c["cluster_name"] for c in rb["per_cluster"] if c["role"] == "donate"}
    receivers = {c["cluster_name"] for c in rb["per_cluster"] if c["role"] == "receive"}
    assert not (donors & receivers)


def test_model_rebalance_conserves_machines_and_positive_each_move():
    rb = _solve_rebalance(True).summary["model_rebalance"]
    # 每一步腾挪净增为正（贪心只接受正收益）
    assert all(m["gain"] > 0 for m in rb["moves"])
