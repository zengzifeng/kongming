#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 2026-07-07 的库内数据跑 time_period（时段）策略。

- 直接加载 backend/app/algorithms 下的**原版**求解器代码（base/_shared/time_period_solver），
  仅为绕开 3.9 不兼容的包 __init__，用 sys.modules 桩接管相对导入；求解逻辑一字未改。
- 输入严格复刻生产链路 policy_service.submit_run(algorithm='time_period')：
    demand_items = build_usage_demand_items()            # 默认 default_discount=1.0 等
    snapshot     = build_snapshot(..., enrich_cluster_redundancy=True)
  其中 usage_demand_source / cluster_redundancy 的取数口径在此按 SQL 复刻。
"""
import importlib.util
import os
import sqlite3
import sys
import types
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
ALGO = os.path.join(BASE, 'backend', 'app', 'algorithms')
DB = os.path.join(BASE, 'backend', 'instance', 'kongming.db')
SELF_SOURCE = '自建'

# ---------- 1. 桩接管，加载原版求解器（不触发 app 包 __init__） ----------
for name in ('app', 'app.utils'):
    m = types.ModuleType(name); m.__path__ = []; sys.modules[name] = m
_err = types.ModuleType('app.utils.errors')
class AlgorithmError(Exception):
    def __init__(self, msg, code=None, **k):
        super().__init__(msg); self.code = code
_err.AlgorithmError = AlgorithmError
sys.modules['app.utils.errors'] = _err
_alg = types.ModuleType('app.algorithms'); _alg.__path__ = [ALGO]
sys.modules['app.algorithms'] = _alg

def _load(mod, fn):
    spec = importlib.util.spec_from_file_location(mod, os.path.join(ALGO, fn))
    m = importlib.util.module_from_spec(spec); sys.modules[mod] = m
    spec.loader.exec_module(m); return m

base = _load('app.algorithms.base', 'base.py')
_load('app.algorithms._shared', '_shared.py')
tps = _load('app.algorithms.time_period_solver', 'time_period_solver.py')
DemandSnapshotItem = base.DemandSnapshotItem
PolicyInputSnapshot = base.PolicyInputSnapshot


# ---------- 2. 从库构建输入（复刻 usage_demand_source + cluster_redundancy + client 形状） ----------
def build_demand_items(conn, default_discount=1.0, default_input_ratio=1.0, default_cache_hit_rate=0.0):
    code_by_id = {i: c for i, c in conn.execute("SELECT id, customer_code FROM customers")}
    name_by_id = {i: n for i, n in conn.execute("SELECT id, name FROM customers")}
    disc = {(cid, m): float(sd or 0) for cid, m, sd in
            conn.execute("SELECT customer_id, model_name, sell_discount FROM customer_sell_discounts")}

    hourly = defaultdict(lambda: defaultdict(float))
    ti = defaultdict(float); to = defaultdict(float); tc = defaultdict(float)
    tcm = defaultdict(float); tio = defaultdict(float); sio = defaultdict(float)
    vio = defaultdict(lambda: defaultdict(float))
    for cid, model, dt, io, tin, ot, ct, cmt, src, prov in conn.execute(
        "SELECT customer_id, model, data_time, input_output, total_input, output_token, "
        "cache_token, cache_miss_token, model_source, provider FROM customer_usage_hourly"):
        pair = (cid, model); io = float(io or 0)
        hourly[pair][dt] += io
        ti[pair] += float(tin or 0); to[pair] += float(ot or 0)
        tc[pair] += float(ct or 0); tcm[pair] += float(cmt or 0); tio[pair] += io
        if src == SELF_SOURCE:
            sio[pair] += io
        else:
            vio[pair][prov] += io

    items = []
    for pair in sorted(hourly):
        cid, model = pair
        sm = hourly[pair]
        series = [(ts, sm[ts] / 60.0) for ts in sorted(sm)]
        expected_tpm = series[-1][1] if series else 0.0
        io_sum = tio[pair]
        items.append(DemandSnapshotItem(
            report_id=f"USG-{code_by_id.get(cid, cid)}-{model}",
            customer_code=code_by_id.get(cid, str(cid)),
            model_name=model,
            expected_tpm=expected_tpm,
            expected_rpm=0.0,
            discount_rate=disc.get(pair, default_discount),
            input_ratio=(ti[pair] / to[pair]) if to[pair] > 0 else default_input_ratio,
            cache_hit_rate=(tc[pair] / (tc[pair] + tcm[pair])) if (tc[pair] + tcm[pair]) > 0 else default_cache_hit_rate,
            current_self_ratio=(sio[pair] / io_sum) if io_sum > 0 else 0.0,
            current_vendor_ratios={p: v / io_sum for p, v in vio[pair].items()} if io_sum > 0 else {},
            quality_score=0.0,
            tpm_series=series,
        ))
    return items, name_by_id


def build_clusters(conn):
    import json
    fields = ("cluster_name deployed_model primary_customer machine_count tpm_per_machine "
              "total_capacity_tpm peak_tpm_d1_23_24 peak_tpm_d2_23_24 peak_tpm_d3_23_24 peak_tpm_idle "
              "idle_redundant_tpm idle_redundant_machines peak_tpm_busy busy_redundant_tpm "
              "busy_redundant_machines current_tpm current_redundant_tpm current_redundant_machines").split()
    clusters, prov_by_cluster = [], {}
    for row in conn.execute(f"SELECT {','.join(fields)}, raw_json FROM cluster_resources "
                            "WHERE snapshot_date=(SELECT MAX(snapshot_date) FROM cluster_resources)"):
        d = {f: row[i] for i, f in enumerate(fields)}
        for k in ("machine_count", "idle_redundant_machines", "busy_redundant_machines", "current_redundant_machines"):
            d[k] = int(d[k] or 0)
        for k in fields:
            if k not in ("cluster_name", "deployed_model", "primary_customer") and not isinstance(d[k], int):
                d[k] = float(d[k] or 0)
        prov_by_cluster[d["cluster_name"]] = (json.loads(row[-1]) or {}).get("provider")
        clusters.append(d)
    return clusters, prov_by_cluster


def apply_current_redundancy(conn, clusters, prov_by_cluster):
    """复刻 cluster_redundancy.apply_current_redundancy：按最新整点自建负载算当前冗余。"""
    latest = conn.execute("SELECT MAX(data_time) FROM customer_usage_hourly").fetchone()[0]
    load = {}
    if latest is not None:
        for prov, io in conn.execute(
            "SELECT provider, SUM(input_output) FROM customer_usage_hourly "
            "WHERE model_source=? AND data_time=? GROUP BY provider", (SELF_SOURCE, latest)):
            load[prov] = float(io or 0) / 60.0
    for c in clusters:
        prov = prov_by_cluster.get(c["cluster_name"])
        cur = load.get(prov, 0.0) if prov else 0.0
        rate = float(c.get("tpm_per_machine", 0) or 0)
        red = max(float(c.get("total_capacity_tpm", 0) or 0) - cur, 0.0)
        c["current_tpm"] = cur
        c["current_redundant_tpm"] = red
        c["current_redundant_machines"] = int(red // rate) if rate > 0 else 0
    return latest


def build_vendors(conn):
    vs = []
    for vendor, model, quota, uc, up, at, art, pd in conn.execute(
        "SELECT vendor, model, quota_tpm, unit_cost, unit_price, actual_tpm, "
        "actual_redundant_tpm, purchase_discount FROM vendor_quotas WHERE status='active'"):
        vs.append(dict(vendor=vendor, model=model, quota_tpm=float(quota or 0),
                       unit_cost=float(uc or 0), unit_price=float(up or 0),
                       actual_tpm=float(at or 0), actual_redundant_tpm=float(art or 0),
                       purchase_discount=float(pd or 0)))
    return vs


def build_model_prices(conn):
    return {m: {"input_cache_hit_price": float(a or 0), "input_cache_miss_price": float(b or 0),
                "output_price": float(c or 0)}
            for m, a, b, c in conn.execute(
                "SELECT model_name, input_cache_hit_price, input_cache_miss_price, output_price "
                "FROM model_list_prices")}


def w(x):  # 万
    return f"{x/1e4:,.1f}w"


def main():
    conn = sqlite3.connect(DB)
    demands, name_by_id = build_demand_items(conn)
    clusters, prov_by_cluster = build_clusters(conn)
    latest = apply_current_redundancy(conn, clusters, prov_by_cluster)
    vendors = build_vendors(conn)
    model_prices = build_model_prices(conn)
    conn.close()

    machines_before = {c["cluster_name"]: c["machine_count"] for c in clusters}

    from datetime import datetime
    snapshot = PolicyInputSnapshot(
        captured_at=datetime(2026, 7, 7, 23, 0, 0),
        algorithm="time_period",
        demands=demands,
        resources={"clusters": clusters},
        monitoring={},
        vendors=vendors,
        params={"model_prices": model_prices},
    )

    print("=" * 96)
    print(f"time_period 策略  |  数据快照最新整点: {latest}  |  需求(客户×模型)组合: {len(demands)}  |  集群: {len(clusters)}")
    print("=" * 96)

    # ---------- 调整前：集群机器数 + 负载/冗余 ----------
    print("\n【调整前 · 各集群机器数与负载】(承接能力单位 万TPM)")
    print(f"{'集群':<26}{'部署模型':<14}{'机器数':>6}{'单台能力':>11}{'总能力':>12}{'当前负载':>12}{'当前冗余':>12}{'冗余台数':>8}")
    for c in sorted(clusters, key=lambda x: x["deployed_model"]):
        print(f"{c['cluster_name']:<26}{c['deployed_model']:<14}{c['machine_count']:>6}"
              f"{w(c['tpm_per_machine']):>11}{w(c['total_capacity_tpm']):>12}"
              f"{w(c['current_tpm']):>12}{w(c['current_redundant_tpm']):>12}{c['current_redundant_machines']:>8}")
    print(f"{'合计':<40}{sum(machines_before.values()):>6}台")

    # ---------- 调整前：各需求自建/三方占比 ----------
    print("\n【调整前 · 各(客户×模型)当前负载与自建/三方占比】(取最新整点 TPM)")
    print(f"{'客户':<20}{'模型':<15}{'当前TPM':>11}{'自建占比':>9}{'三方占比':>9}  三方provider明细")
    def cn(code):
        for i, c in name_by_id.items():
            pass
        return code
    id_by_code = {}
    conn2 = sqlite3.connect(DB)
    id_by_code = {code: name for code, name in conn2.execute("SELECT customer_code, name FROM customers")}
    conn2.close()
    for d in sorted(demands, key=lambda x: -x.expected_tpm):
        vend = ", ".join(f"{k.split('-')[-1] if '-' in k else k}:{v:.0%}" for k, v in
                         sorted(d.current_vendor_ratios.items(), key=lambda kv: -kv[1]))
        nm = id_by_code.get(d.customer_code, d.customer_code)
        print(f"{nm[:19]:<20}{d.model_name:<15}{d.expected_tpm:>11,.0f}"
              f"{d.current_self_ratio:>8.0%}{max(1-d.current_self_ratio,0):>9.0%}  {vend}")

    # ---------- 跑策略 ----------
    result = tps.TimePeriodSolver().solve(snapshot)
    diag, summ = result.diagnostics, result.summary
    mb, ma = diag["machines_before"], diag["machines_after"]

    # ---------- 集群调整方案 ----------
    print("\n" + "=" * 96)
    print("【策略产出 · 集群调整方案（机器腾挪）】")
    moves = summ["node_moves"]
    if not moves:
        print("  无机器腾挪：现有各集群满容量已足够承接（或无可行/有益的跨集群搬迁）。")
    else:
        for m in moves:
            print(f"  {m['from_cluster']} → {m['to_cluster']}  搬 {m['machine_count']} 台  "
                  f"(源{w(m['from_tpm_per_machine'])}/台 → 目标{w(m['to_tpm_per_machine'])}/台，"
                  f"目标新增 {w(m['added_tpm'])})")
            print(f"      理由: {m['reason']}")

    print("\n【各集群机器数 调整前 → 调整后】")
    changed = 0
    for name in sorted(mb):
        b, a = mb[name], ma[name]
        flag = "" if b == a else f"   <== {'+' if a>b else ''}{a-b}"
        if b != a:
            changed += 1
        print(f"  {name:<28}{b:>3} → {a:<3}{flag}")
    print(f"  机器总量: {summ['machines_total_before']} → {summ['machines_total_after']} "
          f"({'守恒' if summ['machines_total_before']==summ['machines_total_after'] else '不守恒!'})，变更集群 {changed} 个")

    # ---------- 水位线 ----------
    print("\n【策略产出 · 切量水位线（每客户自建TPM上限，调整后固定）】")
    wms = summ["watermark_changes"]
    if not wms:
        print("  无水位线产出。")
    else:
        print(f"{'客户':<20}{'模型':<15}{'调整前自建占比':>13}{'水位线(自建TPM)':>16}{'兜底三方':>22}{'客户收益':>12}")
        for x in sorted(wms, key=lambda z: -z.get("customer_revenue_gain", 0)):
            nm = id_by_code.get(x["customer_code"], x["customer_code"])
            print(f"{nm[:19]:<20}{x['model']:<15}{x['current_self_ratio']:>12.0%}"
                  f"{x['watermark_self_tpm']:>16,.0f}{str(x['fallback_vendor'])[:20]:>22}"
                  f"{x['customer_revenue_gain']:>12,.0f}")

    # ---------- 汇总 & 约束 ----------
    print("\n【收益汇总】(收入为整段时序积分口径)")
    print(f"  调整前自建收入积分: {summ['self_revenue_before']:,.0f}")
    print(f"  调整后自建收入积分: {summ['self_revenue_after']:,.0f}")
    print(f"  预期收益提升      : {summ['expected_revenue_gain']:,.0f}")
    print(f"  接纳客户(拿到自建): {len(summ['accepted_customers'])}   被拒: {len(diag['rejected'])}")
    if diag["rejected"]:
        from collections import Counter
        rc = Counter(r["reason"] for r in diag["rejected"])
        print("  被拒原因分布: " + ", ".join(f"{k}×{v}" for k, v in rc.most_common()))
    print("\n【约束体检】")
    for con in result.constraints:
        print(f"  [{'PASS' if con.hit else 'FAIL'}] {con.name:<32} {con.description}")

    # ---------- 峰值可行性硬约束验证 ----------
    feas = diag.get("peak_feasibility", {})
    print("\n【逐模型峰值可行性验证】(客户按波形跑,自建调整后+三方 需 ≥ 峰值,单位万TPM)")
    print(f"{'模型':<15}{'客户峰值':>10}{'自建(后)':>10}{'三方额度':>10}{'总承接':>10}{'余量':>10}  判定")
    for m in sorted(feas):
        f = feas[m]
        ok = 'OK' if f['feasible'] else 'X 会掉量!'
        print(f"{m:<15}{f['peak_demand']/1e4:>9,.0f}w{f['self_cap']/1e4:>9,.0f}w"
              f"{f['vendor_cap']/1e4:>9,.0f}w{f['total_cap']/1e4:>9,.0f}w{f['slack']/1e4:>9,.0f}w  {ok}")


if __name__ == "__main__":
    main()
