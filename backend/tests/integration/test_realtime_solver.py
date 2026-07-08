from datetime import datetime, timezone

from app.algorithms.base import DemandSnapshotItem, PolicyInputSnapshot
from app.algorithms.realtime_solver import RealtimeSolver, _Candidate


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
        input_ratio=1.5,
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


# ---- 统一单趟 + 原生/接收冗余分账 的回归用例 ----
# 同价三方 + 同价列表价，密度只由 discount 决定，便于构造严格密度序。

def _multi_snapshot(demands, clusters, models, vendor_quota=10_000_000):
    vendors = [{"vendor": "tp", "model": m, "quota_tpm": vendor_quota,
                "unit_cost": 0.0002, "unit_price": 0.0010} for m in models]
    prices = {m: {"input_cache_hit_price": 0.0002, "input_cache_miss_price": 0.0010,
                  "output_price": 0.0010} for m in models}
    return PolicyInputSnapshot(
        captured_at=datetime.now(timezone.utc), algorithm="realtime",
        demands=demands, resources={"clusters": clusters}, monitoring={},
        vendors=vendors, params={"model_prices": prices},
    )


def _dem(report_id, model, tpm, discount, self_ratio=0.0):
    return DemandSnapshotItem(
        report_id=report_id, customer_code=report_id, model_name=model,
        expected_tpm=tpm, expected_rpm=0, discount_rate=discount,
        input_ratio=1.0, cache_hit_rate=0.0, current_self_ratio=self_ratio,
        current_vendor_ratios={"tp": max(1 - self_ratio, 0.0)},
    )


def _cl(name, model, rate, redundant_tpm, redundant_machines, machine_count=10):
    return {"cluster_name": name, "deployed_model": model, "machine_count": machine_count,
            "tpm_per_machine": rate, "current_redundant_tpm": redundant_tpm,
            "current_redundant_machines": redundant_machines}


def test_realtime_partial_then_node_move_fills_gap():
    # 问题1：高密度客户被现有冗余“部分承接”(30k)后，应继续腾挪补齐到全量(100k)，
    # 而非停在 30k partial（旧两趟逻辑会立即定稿 30k、残缺口丢给三方）。
    clusters = [
        _cl("self-M", "modelM", 50_000, 30_000, 0),    # 只有 30k 冗余、无可供机器
        _cl("donor-N", "modelN", 50_000, 100_000, 2),  # 可供 2 台
    ]
    result = RealtimeSolver().solve(_multi_snapshot(
        [_dem("hd", "modelM", 100_000, 0.9)], clusters, ["modelM", "modelN"]))
    acc = {a["report_id"]: a for a in result.summary["accepted_customers"]}
    assert acc["hd"]["incremental_tpm_self"] == 100_000
    assert any(a.action_type == "node_move" for a in result.actions)


def test_realtime_density_priority_across_clusters_via_node_move():
    # 问题2：低密度同模型客户 vs 高密度跨模型客户争 clA 的空闲机器。
    # 统一密度序下高密度客户先占用（含腾挪），低密度客户被挤出。
    clusters = [
        _cl("clA", "modelM", 50_000, 100_000, 2),  # 2 台空闲
        _cl("self-N", "modelN", 50_000, 0, 0),     # 高密度客户本模型集群无冗余
    ]
    result = RealtimeSolver().solve(_multi_snapshot([
        _dem("low_same_model", "modelM", 100_000, 0.3),
        _dem("high_cross_model", "modelN", 100_000, 0.9),
    ], clusters, ["modelM", "modelN"]))
    acc = {a["report_id"]: a for a in result.summary["accepted_customers"]}
    rej = {r["report_id"] for r in result.diagnostics["rejected"]}
    assert acc.get("high_cross_model", {}).get("incremental_tpm_self") == 100_000
    assert "low_same_model" in rej


def test_realtime_allows_donor_to_also_receive():
    # 倒手放开：clA 先把唯一空闲机器供给高密度 modelB 客户(A→B)，
    # 随后 clA 自己的 modelA 客户靠 clC→A 承接。旧互斥约束会因 clA∈donors_used 拒掉 own_A。
    clusters = [
        _cl("clA", "modelA", 50_000, 50_000, 1),  # 1 台空闲
        _cl("clB", "modelB", 50_000, 0, 0),       # 需接收
        _cl("clC", "modelC", 50_000, 50_000, 1),  # 1 台空闲
    ]
    result = RealtimeSolver().solve(_multi_snapshot([
        _dem("hd_B", "modelB", 50_000, 0.9),
        _dem("own_A", "modelA", 50_000, 0.5),
    ], clusters, ["modelA", "modelB", "modelC"]))
    acc = {a["report_id"]: a for a in result.summary["accepted_customers"]}
    moves = result.summary["node_moves"]
    froms = {m["from_cluster"] for m in moves}
    tos = {m["to_cluster"] for m in moves}
    assert acc.get("hd_B", {}).get("incremental_tpm_self") == 50_000
    assert acc.get("own_A", {}).get("incremental_tpm_self") == 50_000
    assert "clA" in froms and "clA" in tos  # clA 既供出又接收


def test_plan_node_move_skips_drained_native_source():
    # 分账安全（白盒）：某集群 native_idle=0（原生冗余已被分配吃空）但 extra_machines>0 时，
    # 不得被选为供出源——movable=min(extra, native_idle//rate) 用 native_idle 而非总量。
    solver = RealtimeSolver()
    clusters = [
        _cl("target", "modelM", 50_000, 0, 0),
        _cl("drained", "modelX", 50_000, 0, 2),
        _cl("healthy", "modelY", 50_000, 100_000, 1),
    ]
    cand = _Candidate(
        demand=_dem("z", "modelM", 50_000, 0.9), unit_self_revenue=0.001,
        best_vendor={"vendor": "tp", "model": "modelM", "unit_cost": 0.0002},
        vendor_purchase_discount=0.2, vendor_margin_per_tpm=0.0008,
        score=0.001, vendor_gap_tpm=50_000,
    )
    extra = {"target": 0, "drained": 2, "healthy": 1}
    native = {"target": 0.0, "drained": 0.0, "healthy": 100_000.0}
    moves = solver._plan_node_move(cand, clusters, extra, native, 50_000)
    froms = {m["from_cluster"] for m in (moves or [])}
    assert "drained" not in froms  # 原生冗余为 0 的集群不供出，即使有 extra_machines
    assert "healthy" in froms


def test_realtime_no_spurious_node_move_when_redundancy_exact():
    # EPS 护栏：多集群冗余求和恰好等于缺口时，不应因浮点残差触发无谓腾挪。
    clusters = [
        _cl("m1", "modelM", 50_000, 60_000, 0),
        _cl("m2", "modelM", 50_000, 40_000, 0),
    ]
    result = RealtimeSolver().solve(_multi_snapshot(
        [_dem("c", "modelM", 100_000, 0.9)], clusters, ["modelM"]))
    acc = {a["report_id"]: a for a in result.summary["accepted_customers"]}
    assert acc["c"]["incremental_tpm_self"] == 100_000
    assert result.summary["node_moves"] == []


# ---- 单台产能修正：整机腾挪按“单台收益=密度×单台产能”而非纯密度 ----

def test_realtime_prefers_higher_single_machine_revenue_over_pure_density():
    # H 密度高(0.9)但目标集群单台仅 0.5M；L 密度略低(0.8)但单台 7M。两者争 donor 仅有的 1 台机器：
    # 按“单台收益 = 密度 × 目标单台产能”应给 L（7M×0.8 > 0.5M×0.9，回收 7M），而非纯密度给 H（只回收 0.5M）。
    clusters = [
        _cl("donor", "modelD", 1_000_000, 1_000_000, 1, machine_count=2),  # 1 台可供机器
        _cl("clH", "modelH", 500_000, 0, 0),    # 高密度客户集群，单台产能低
        _cl("clL", "modelL", 7_000_000, 0, 0),  # 低密度客户集群，单台产能极高
    ]
    result = RealtimeSolver().solve(_multi_snapshot([
        _dem("H", "modelH", 2_000_000, 0.9),
        _dem("L", "modelL", 20_000_000, 0.8),
    ], clusters, ["modelH", "modelL"]))
    acc = {a["report_id"]: a for a in result.summary["accepted_customers"]}
    rej = {r["report_id"] for r in result.diagnostics["rejected"]}
    assert acc.get("L", {}).get("incremental_tpm_self") == 7_000_000
    assert "H" in rej


def test_plan_node_move_prefers_low_rate_source_to_minimize_destruction():
    # 供出源偏好（白盒）：两个都能满足需求的源，优先搬【单台产能低】的，减少源侧产能损毁
    # （removed_tpm = 台数 × 源单台产能；目标新增恒为 台数 × 目标单台产能，与源无关）。
    solver = RealtimeSolver()
    clusters = [
        _cl("target", "modelM", 2_000_000, 0, 0),
        _cl("cheap", "modelX", 2_000_000, 4_000_000, 2),    # 低产能源：搬 1 台只毁 2M
        _cl("pricey", "modelY", 7_000_000, 14_000_000, 2),  # 高产能源：搬 1 台白毁 7M
    ]
    cand = _Candidate(
        demand=_dem("z", "modelM", 2_000_000, 0.9), unit_self_revenue=0.001,
        best_vendor={"vendor": "tp", "model": "modelM", "unit_cost": 0.0002},
        vendor_purchase_discount=0.2, vendor_margin_per_tpm=0.0008,
        score=0.001, vendor_gap_tpm=2_000_000,
    )
    extra = {"target": 0, "cheap": 2, "pricey": 2}
    native = {"target": 0.0, "cheap": 4_000_000.0, "pricey": 14_000_000.0}
    moves = solver._plan_node_move(cand, clusters, extra, native, 2_000_000)
    froms = {m["from_cluster"] for m in (moves or [])}
    assert "cheap" in froms and "pricey" not in froms

