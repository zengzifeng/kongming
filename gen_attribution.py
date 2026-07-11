#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐调整收益核算（口径修订版）——把每个「切量水位线调整」的收益拆到可复核的最小公式：

  客户收益 = 单TPM收入 × ( Σ_t 自建_after(t) − Σ_t 自建_before(t) )
      其中  自建_after(t) = min( 需求(t), 水位线 )          （调整后：固定水位线削峰）
           自建_before(t) = 需求(t) × 调整前真自建占比       （调整前：按当前占比）
           单TPM收入(旧称密度) = 售卖折扣 × 列表价(按 输入:输出 比 + 缓存命中率 加权)

机器腾挪本身不直接产币，它通过「抬高某客户可用自建容量→抬高其水位线」间接兑现，
故收益全部归集在水位线调整上；机器腾挪与水位线一一对应（见 reason 里的承接客户）。

依赖 run_time_period_corrected.py 已写出的 _corrected_result.json / _corrected_demands.json，
但单价(单TPM收入)需重新按求解器同一公式算，故这里也直接连库取 discount/price/io/cache。
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

# 复用修订版取数（含白名单 + 剔除逻辑）与求解器
crun = importlib.util.spec_from_file_location('crun', os.path.join(BASE, 'run_time_period_corrected.py'))
_m = importlib.util.module_from_spec(crun); sys.modules['crun'] = _m; crun.loader.exec_module(_m)
tps = sys.modules['app.algorithms.time_period_solver']
_shared = sys.modules['app.algorithms._shared']


def main():
    keep = "--keep-ksyun" in sys.argv
    conn = sqlite3.connect(DB)
    whitelist = _m.build_self_provider_whitelist(conn)
    id_by_name = {name: i for i, name in conn.execute("SELECT id, name FROM customers")}
    name_by_code = {code: name for code, name in conn.execute("SELECT customer_code, name FROM customers")}
    exclude_ids = set() if keep else {id_by_name[n] for n in _m.EXCLUDE_CUSTOMER_NAMES if n in id_by_name}
    demands, _ = _m.build_demand_items(conn, whitelist, exclude_ids)
    clusters, prov_by_cluster = _m.build_clusters(conn)
    _m.apply_current_redundancy(conn, clusters, prov_by_cluster, exclude_ids)
    vendors = _m.build_vendors(conn)
    model_prices = _m.build_model_prices(conn)
    conn.close()

    snapshot = _m.PolicyInputSnapshot(
        captured_at=datetime(2026, 7, 7, 23, 0, 0), algorithm="time_period",
        demands=demands, resources={"clusters": clusters}, monitoring={},
        vendors=vendors, params={"model_prices": model_prices})

    solver = tps.TimePeriodSolver()
    # 复算每个客户单TPM收入（旧称密度），口径与求解器 _unit_self_revenue 完全一致
    unit_of = {}
    for d in demands:
        unit_of[(d.customer_code, d.model_name)] = solver._unit_self_revenue(d, model_prices, vendors)
    demand_of = {(d.customer_code, d.model_name): d for d in demands}

    result = solver.solve(snapshot)
    summ = result.summary
    wms = summ["watermark_changes"]
    moves = summ["node_moves"]
    timeline = solver._timeline(demands)

    # 机器腾挪：按 reason 里的承接客户 code 关联到其水位线调整
    move_for_code = defaultdict(list)
    for mv in moves:
        toks = mv["reason"].replace("（", " ").split()
        code = next((t for t in toks if t.startswith("C") and t[1:].isdigit()), None)
        if code:
            move_for_code[code].append(mv)

    def w(x):
        return f"{x/1e4:,.1f}w"

    Y = 60 / 1e6              # TPM·整点积分 × 60min ÷ 1e6(列表价元/百万token) → 元/天 或 百万token/天
    def yuan(x):             # 元/天
        return f"{x*Y:,.0f}"
    def mt(x):               # 百万token/天
        return f"{x*Y:,.1f}"

    mode = "保留金山云网络" if keep else "剔除金山云网络"
    print("=" * 100)
    print(f"逐调整收益核算【口径修订版 · {mode}】  收益单位=元/天")
    print(f"公式: 收益(元/天) = 单TPM收入(元/百万token) × 自建体量(百万token/天)；体量=Σ24整点TPM×60min÷1e6")
    print("=" * 100)

    rows = []
    total = 0.0
    for x in sorted(wms, key=lambda z: -z.get("customer_revenue_gain", 0)):
        code, model = x["customer_code"], x["model"]
        nm = name_by_code.get(code, code)
        d = demand_of[(code, model)]
        unit = unit_of[(code, model)]
        wm = x["watermark_self_tpm"]
        s0 = d.current_self_ratio
        series = solver._series_of(d, timeline)
        sum_after = sum(min(tpm, wm) for _, tpm in series)
        sum_before = sum(tpm * s0 for _, tpm in series)
        delta = sum_after - sum_before
        gain = unit * delta
        total += gain
        peak = max((tpm for _, tpm in series), default=0.0)
        rows.append(dict(nm=nm, code=code, model=model, unit=unit, wm=wm, s0=s0,
                         peak=peak, sum_before=sum_before, sum_after=sum_after,
                         delta=delta, gain=gain, moves=move_for_code.get(code, [])))

    for r in rows:
        tag = "＋抬升" if r["delta"] > 0 else "－削峰回收"
        print(f"\n● {r['nm']} · {r['model']}  [{tag} {r['gain']*Y:+,.0f} 元/天]")
        print(f"    单TPM收入(旧称密度)     = {r['unit']:.6f}  元/百万token (= 售卖折扣 × 列表价加权)")
        print(f"    调整前真自建占比        = {r['s0']:.0%}   峰值需求 = {w(r['peak'])}")
        print(f"    切量水位线(自建TPM上限) = {r['wm']:,.0f}  ({w(r['wm'])})")
        print(f"    Σ自建_before (占比口径) = {mt(r['sum_before'])} 百万token/天")
        print(f"    Σ自建_after  (削峰口径) = {mt(r['sum_after'])} 百万token/天")
        print(f"    ΔΣ自建                  = {mt(r['delta'])} 百万token/天")
        print(f"    收益 = {r['unit']:.6f} × {mt(r['delta'])} = {yuan(r['gain'])} 元/天")
        for mv in r["moves"]:
            print(f"    ├─关联机器腾挪: {mv['from_cluster']}→{mv['to_cluster']} ×{mv['machine_count']} "
                  f"(目标+{w(mv['added_tpm'])}，为承接本客户抬高可用自建容量)")

    print("\n" + "=" * 100)
    print(f"逐调整收益合计 = {yuan(total)} 元/天  (≈ {total*Y*30/1e4:,.0f} 万元/月 · {total*Y*365/1e8:,.2f} 亿元/年)")
    print(f"求解器汇总收益 = {yuan(summ['expected_revenue_gain'])} 元/天  (对账差 {(total-summ['expected_revenue_gain'])*Y:+,.2f} 元/天)")
    print(f"  调整前自建收入: {yuan(summ['self_revenue_before'])} 元/天")
    print(f"  调整后自建收入: {yuan(summ['self_revenue_after'])} 元/天")

    # 落盘供 HTML
    suffix = "_keepksyun" if keep else ""
    with open(os.path.join(BASE, f"_corrected_attribution{suffix}.json"), "w", encoding="utf-8") as f:
        json.dump({"mode": mode, "total": total,
                   "solver_gain": summ["expected_revenue_gain"],
                   "self_revenue_before": summ["self_revenue_before"],
                   "self_revenue_after": summ["self_revenue_after"],
                   "rows": rows}, f, ensure_ascii=False, indent=2)
    print(f"[written] _corrected_attribution{suffix}.json")


if __name__ == "__main__":
    main()
