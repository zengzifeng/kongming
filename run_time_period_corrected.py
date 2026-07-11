#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""time_period 策略「口径修订版」——在 run_time_period.py 基础上做两处**取数口径**修订，
求解器代码(time_period_solver.py)一字未改，仅修正喂给它的 demand 输入。

修订 1（自建provider白名单）：
    原 build_demand_items 把 model_source='自建' 的一切 provider 都当作自建承接。
    但库里存在「挂着自建标记、却经非本模型自建集群 provider 承接」的量，典型：
      · 北京金山云网络 glm-5.1 走 ksyun-glm47-qy-12003（GLM-4.7 集群，不在 glm-5.1 白名单）15,382w
      · 北京金山云网络 glm-5.2 走 ksyun-glm5.1-qy-12004（glm-5.1 集群，跨模型）      11,271w
      · 北京金山数字娱乐 glm-5.1 同样走 ksyun-glm47-qy-12003                          66k
    这些不是「我方该模型自建集群」提供的产能，不应计入自建占比、更不应纳入切量收益考量。
    白名单 = cluster_resources.raw_json.provider 按 deployed_model 分组的集合。
    只有 provider ∈ 该模型白名单，才算真自建；否则并入三方(vendor)。

修订 2（剔除金山云网络客户）：
    金山云网络(C0005)是转售/网络客户，其「量」不计入我方切量考量（用户明确要求）。
    默认整户剔除；--keep-ksyun 可保留以对照。

用法：
    python3 run_time_period_corrected.py            # 修订版（剔除金山云网络 + provider白名单）
    python3 run_time_period_corrected.py --keep-ksyun   # 只做白名单修订，保留金山云网络
    产物：控制台报告 + _corrected_result.json + _corrected_demands.json（供 HTML 用）
"""
import importlib.util
import json
import os
import sqlite3
import sys
import types
from collections import defaultdict
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
ALGO = os.path.join(BASE, 'backend', 'app', 'algorithms')
DB = os.path.join(BASE, 'backend', 'instance', 'kongming.db')
SELF_SOURCE = '自建'
EXCLUDE_CUSTOMER_NAMES = {'北京金山云网络技术有限公司'}   # 转售客户，量不计入考量

# ---------- 桩接管，加载原版求解器（与 run_time_period.py 完全一致） ----------
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


# ---------- 自建provider白名单：按 deployed_model 聚合 cluster_resources.raw_json.provider ----------
def build_self_provider_whitelist(conn):
    wl = defaultdict(set)
    for model, raw in conn.execute(
        "SELECT deployed_model, raw_json FROM cluster_resources "
        "WHERE snapshot_date=(SELECT MAX(snapshot_date) FROM cluster_resources)"):
        prov = (json.loads(raw) or {}).get('provider') if raw else None
        if prov:
            wl[model].add(prov)
    return dict(wl)


# ---------- 从库构建输入（复刻 run_time_period.build_demand_items，加两处修订） ----------
def build_demand_items(conn, whitelist, exclude_customer_ids,
                       default_discount=1.0, default_input_ratio=1.0, default_cache_hit_rate=0.0):
    code_by_id = {i: c for i, c in conn.execute("SELECT id, customer_code FROM customers")}
    disc = {(cid, m): float(sd or 0) for cid, m, sd in
            conn.execute("SELECT customer_id, model_name, sell_discount FROM customer_sell_discounts")}

    hourly = defaultdict(lambda: defaultdict(float))
    ti = defaultdict(float); to = defaultdict(float); tc = defaultdict(float)
    tcm = defaultdict(float); tio = defaultdict(float); sio = defaultdict(float)
    vio = defaultdict(lambda: defaultdict(float))
    # 诊断：被白名单剔除、由自建改判三方的量（provider→io 汇总）
    reclassified = defaultdict(lambda: defaultdict(float))
    for cid, model, dt, io, tin, ot, ct, cmt, src, prov in conn.execute(
        "SELECT customer_id, model, data_time, input_output, total_input, output_token, "
        "cache_token, cache_miss_token, model_source, provider FROM customer_usage_hourly"):
        if cid in exclude_customer_ids:
            continue
        pair = (cid, model); io = float(io or 0)
        hourly[pair][dt] += io
        ti[pair] += float(tin or 0); to[pair] += float(ot or 0)
        tc[pair] += float(ct or 0); tcm[pair] += float(cmt or 0); tio[pair] += io
        # === 修订 1：自建 provider 必须在「该模型」白名单内，才算真自建 ===
        is_true_self = (src == SELF_SOURCE) and (prov in whitelist.get(model, set()))
        if is_true_self:
            sio[pair] += io
        else:
            # 挂自建标记但 provider 不在白名单 → 计诊断，并入三方
            if src == SELF_SOURCE:
                reclassified[pair][prov] += io
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
    return items, reclassified


def build_clusters(conn):
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


def apply_current_redundancy(conn, clusters, prov_by_cluster, exclude_customer_ids):
    """按最新整点自建负载算当前冗余。负载只统计**真自建**（provider==集群自身 provider）
    且排除被剔除客户，与 demand 口径一致。"""
    latest = conn.execute("SELECT MAX(data_time) FROM customer_usage_hourly").fetchone()[0]
    load = defaultdict(float)
    if latest is not None:
        ex = ",".join("?" * len(exclude_customer_ids)) if exclude_customer_ids else "NULL"
        q = ("SELECT provider, SUM(input_output) FROM customer_usage_hourly "
             f"WHERE model_source=? AND data_time=? AND customer_id NOT IN ({ex}) GROUP BY provider")
        params = [SELF_SOURCE, latest] + list(exclude_customer_ids)
        for prov, io in conn.execute(q, params):
            load[prov] += float(io or 0) / 60.0
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


def unit_breakdown(demand, model_prices, vendors):
    """逐项复算「单TPM收入」(旧称密度)，口径与求解器 _unit_self_revenue 完全一致，
    额外返回每个中间量(份额/三档价/三项乘积)，供 HTML 展示公式代入过程。"""
    price = model_prices.get(demand.model_name, {})
    fallback = next((float(v.get("unit_price", 0) or 0) for v in vendors
                     if v.get("model") == demand.model_name and v.get("unit_price")), 0.0014)
    input_hit = float(price.get("input_cache_hit_price", fallback * 0.2) or 0)
    input_miss = float(price.get("input_cache_miss_price", fallback) or 0)
    output_p = float(price.get("output_price", fallback) or 0)
    io = max(demand.input_ratio, 0)
    if io <= 0:
        io = 1.0
    denom = io + 1.0
    input_share = io / denom
    output_share = 1.0 / denom
    chr_ = min(max(demand.cache_hit_rate, 0), 1)
    term_hit = input_share * chr_ * input_hit
    term_miss = input_share * (1 - chr_) * input_miss
    term_out = output_share * output_p
    weighted = term_hit + term_miss + term_out
    unit = weighted * max(demand.discount_rate, 0)
    return dict(discount_rate=demand.discount_rate, input_ratio=io,
                input_share=input_share, output_share=output_share, cache_hit_rate=chr_,
                input_hit_price=input_hit, input_miss_price=input_miss, output_price=output_p,
                term_hit=term_hit, term_miss=term_miss, term_out=term_out,
                weighted_list_price=weighted, unit_self_revenue=unit)


def w(x):
    return f"{x/1e4:,.1f}w"


def main():
    keep_ksyun = "--keep-ksyun" in sys.argv
    conn = sqlite3.connect(DB)

    whitelist = build_self_provider_whitelist(conn)
    id_by_name = {name: i for i, name in conn.execute("SELECT id, name FROM customers")}
    name_by_code = {code: name for code, name in conn.execute("SELECT customer_code, name FROM customers")}
    exclude_ids = set() if keep_ksyun else {id_by_name[n] for n in EXCLUDE_CUSTOMER_NAMES if n in id_by_name}

    demands, reclassified = build_demand_items(conn, whitelist, exclude_ids)
    clusters, prov_by_cluster = build_clusters(conn)
    latest = apply_current_redundancy(conn, clusters, prov_by_cluster, exclude_ids)
    vendors = build_vendors(conn)
    model_prices = build_model_prices(conn)

    machines_before = {c["cluster_name"]: c["machine_count"] for c in clusters}

    snapshot = PolicyInputSnapshot(
        captured_at=datetime(2026, 7, 7, 23, 0, 0), algorithm="time_period",
        demands=demands, resources={"clusters": clusters}, monitoring={},
        vendors=vendors, params={"model_prices": model_prices})

    mode = "保留金山云网络" if keep_ksyun else "剔除金山云网络"
    print("=" * 96)
    print(f"time_period 策略【口径修订版：自建provider白名单 + {mode}】")
    print(f"数据快照最新整点: {latest}  |  需求(客户×模型)组合: {len(demands)}  |  集群: {len(clusters)}")
    print("=" * 96)

    print("\n【自建provider白名单】(按模型；只有此集合内的 provider 才算真自建)")
    for model in sorted(whitelist):
        print(f"  {model:<15} {', '.join(sorted(whitelist[model]))}")

    print("\n【口径修订影响 · 被从「自建」改判为「三方」的量】(挂自建标记但 provider 不在该模型白名单)")
    if not reclassified:
        print("  无")
    else:
        print(f"{'客户':<20}{'模型':<12}{'错挂provider':<26}{'日均TPM':>12}")
        for (cid, model), provs in sorted(reclassified.items(), key=lambda kv: -sum(kv[1].values())):
            nm = next((n for n, i in id_by_name.items() if i == cid), str(cid))
            for prov, io in sorted(provs.items(), key=lambda kv: -kv[1]):
                print(f"{nm[:19]:<20}{model:<12}{str(prov)[:25]:<26}{io/60.0/24:>12,.0f}")

    # ---------- 调整前：集群机器数 + 负载/冗余 ----------
    print("\n【调整前 · 各集群机器数与负载】(承接能力单位 万TPM；负载=真自建口径)")
    print(f"{'集群':<26}{'部署模型':<14}{'机器数':>6}{'单台能力':>11}{'总能力':>12}{'当前负载':>12}{'当前冗余':>12}{'冗余台数':>8}")
    for c in sorted(clusters, key=lambda x: x["deployed_model"]):
        print(f"{c['cluster_name']:<26}{c['deployed_model']:<14}{c['machine_count']:>6}"
              f"{w(c['tpm_per_machine']):>11}{w(c['total_capacity_tpm']):>12}"
              f"{w(c['current_tpm']):>12}{w(c['current_redundant_tpm']):>12}{c['current_redundant_machines']:>8}")
    print(f"{'合计':<40}{sum(machines_before.values()):>6}台")

    # ---------- 调整前：各需求自建/三方占比 ----------
    print("\n【调整前 · 各(客户×模型)当前负载与自建/三方占比】(取最新整点 TPM；自建=白名单口径)")
    print(f"{'客户':<20}{'模型':<15}{'当前TPM':>11}{'自建占比':>9}{'三方占比':>9}  三方provider明细")
    for d in sorted(demands, key=lambda x: -x.expected_tpm):
        vend = ", ".join(f"{k.split('-')[-1] if '-' in k else k}:{v:.0%}" for k, v in
                         sorted(d.current_vendor_ratios.items(), key=lambda kv: -kv[1])[:4])
        nm = name_by_code.get(d.customer_code, d.customer_code)
        print(f"{nm[:19]:<20}{d.model_name:<15}{d.expected_tpm:>11,.0f}"
              f"{d.current_self_ratio:>8.0%}{max(1-d.current_self_ratio,0):>9.0%}  {vend}")

    # ---------- 跑策略 ----------
    solver = tps.TimePeriodSolver()
    result = solver.solve(snapshot)
    diag, summ = result.diagnostics, result.summary
    mb, ma = diag["machines_before"], diag["machines_after"]

    print("\n" + "=" * 96)
    print("【策略产出 · 集群调整方案（机器腾挪）】")
    moves = summ["node_moves"]
    if not moves:
        print("  无机器腾挪。")
    for m in moves:
        cust = name_by_code.get(m['reason'].split()[-1].split('（')[0], '')
        print(f"  {m['from_cluster']} → {m['to_cluster']}  搬 {m['machine_count']} 台  "
              f"(源{w(m['from_tpm_per_machine'])}/台 → 目标{w(m['to_tpm_per_machine'])}/台，目标新增 {w(m['added_tpm'])})")
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

    print("\n【策略产出 · 切量水位线（每客户自建TPM上限，调整后固定）】")
    wms = summ["watermark_changes"]
    Y = 60 / 1e6   # TPM·整点积分 × 60min ÷ 1e6(列表价元/百万token) → 元/天
    print(f"{'客户':<20}{'模型':<15}{'调整前自建占比':>13}{'水位线(自建TPM)':>16}{'兜底三方':>22}{'客户收益(元/天)':>16}")
    for x in sorted(wms, key=lambda z: -z.get("customer_revenue_gain", 0)):
        nm = name_by_code.get(x["customer_code"], x["customer_code"])
        print(f"{nm[:19]:<20}{x['model']:<15}{x['current_self_ratio']:>12.0%}"
              f"{x['watermark_self_tpm']:>16,.0f}{str(x['fallback_vendor'])[:20]:>22}"
              f"{x['customer_revenue_gain']*Y:>16,.0f}")

    print("\n【收益汇总】(单位=元/天，按当日24整点波形折算)")
    print(f"  调整前自建收入: {summ['self_revenue_before']*Y:,.0f} 元/天")
    print(f"  调整后自建收入: {summ['self_revenue_after']*Y:,.0f} 元/天")
    print(f"  预期收益提升  : {summ['expected_revenue_gain']*Y:,.0f} 元/天  "
          f"(≈ {summ['expected_revenue_gain']*Y*30/1e4:,.0f} 万元/月 · {summ['expected_revenue_gain']*Y*365/1e8:,.2f} 亿元/年)")
    print(f"  接纳客户(拿到自建): {len(summ['accepted_customers'])}   被拒: {len(diag['rejected'])}")
    if diag["rejected"]:
        from collections import Counter
        rc = Counter(r["reason"] for r in diag["rejected"])
        print("  被拒原因分布: " + ", ".join(f"{k}×{v}" for k, v in rc.most_common()))

    print("\n【约束体检】")
    for con in result.constraints:
        print(f"  [{'PASS' if con.hit else 'FAIL'}] {con.name:<32} {con.description}")

    feas = diag.get("peak_feasibility", {})
    print("\n【逐模型峰值可行性验证】(客户按波形跑,自建调整后+三方 需 ≥ 峰值,单位万TPM)")
    print(f"{'模型':<15}{'客户峰值':>10}{'自建(后)':>10}{'三方额度':>10}{'总承接':>10}{'余量':>10}  判定")
    for m in sorted(feas):
        f = feas[m]
        ok = 'OK' if f['feasible'] else 'X 会掉量!'
        print(f"{m:<15}{f['peak_demand']/1e4:>9,.0f}w{f['self_cap']/1e4:>9,.0f}w"
              f"{f['vendor_cap']/1e4:>9,.0f}w{f['total_cap']/1e4:>9,.0f}w{f['slack']/1e4:>9,.0f}w  {ok}")

    # ---------- 落盘：结果 + demand 波形（供 HTML / 收益核算用） ----------
    suffix = "_keepksyun" if keep_ksyun else ""
    # 逐 demand 复算「单TPM收入」明细；取头号收益客户做公式代入示例
    ub_of = {(d.customer_code, d.model_name): unit_breakdown(d, model_prices, vendors) for d in demands}
    unit_example = None
    if wms:
        top = max(wms, key=lambda x: x.get("customer_revenue_gain", 0))
        d0 = next((dd for dd in demands if dd.customer_code == top["customer_code"]
                   and dd.model_name == top["model"]), None)
        if d0 is not None:
            unit_example = dict(ub_of[(d0.customer_code, d0.model_name)])
            unit_example["customer"] = name_by_code.get(d0.customer_code, d0.customer_code)
            unit_example["model"] = d0.model_name
    out_result = {
        "mode": mode, "latest": latest, "whitelist": {k: sorted(v) for k, v in whitelist.items()},
        "machines_before": mb, "machines_after": ma,
        "node_moves": moves, "watermark_changes": wms,
        "self_revenue_before": summ["self_revenue_before"],
        "self_revenue_after": summ["self_revenue_after"],
        "expected_revenue_gain": summ["expected_revenue_gain"],
        "peak_feasibility": feas,
        "model_prices": model_prices,
        "unit_example": unit_example,
        "clusters": [{k: c[k] for k in ("cluster_name", "deployed_model", "machine_count",
                                        "tpm_per_machine", "total_capacity_tpm", "current_tpm")}
                     for c in clusters],
        "reclassified": [
            {"customer": next((n for n, i in id_by_name.items() if i == cid), str(cid)),
             "model": model, "provider": prov, "avg_tpm": io / 60.0 / 24}
            for (cid, model), provs in reclassified.items() for prov, io in provs.items()
        ],
    }
    with open(os.path.join(BASE, f"_corrected_result{suffix}.json"), "w", encoding="utf-8") as f:
        json.dump(out_result, f, ensure_ascii=False, indent=2)

    demands_out = [{
        "customer": name_by_code.get(d.customer_code, d.customer_code),
        "customer_code": d.customer_code, "model": d.model_name,
        "current_self_ratio": d.current_self_ratio,
        "unit_self_revenue": ub_of[(d.customer_code, d.model_name)]["unit_self_revenue"],
        "series": [{"ts": ts, "tpm": tpm} for ts, tpm in d.tpm_series],
    } for d in demands]
    with open(os.path.join(BASE, f"_corrected_demands{suffix}.json"), "w", encoding="utf-8") as f:
        json.dump(demands_out, f, ensure_ascii=False, indent=2)
    conn.close()
    print(f"\n[written] _corrected_result{suffix}.json / _corrected_demands{suffix}.json")


if __name__ == "__main__":
    main()
