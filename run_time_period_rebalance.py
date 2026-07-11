#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""time_period「模型级供需再平衡」实验版 —— 在原求解器产出之上，补一层跨模型抢机器逻辑。

原 solver 的机器腾挪是「逐客户、需求驱动」：只有某单一客户 peak_vendor_gap > 其可服务集群空闲
时才触发。于是 kimi-k2.5 这种「多客户峰值叠加过订、但没有单客户暴露大缺口」的模型永远抢不到机器，
而 glm-5.2 这种「容量≫峰值需求」的富余模型的空转机器也永远挪不走。

本脚本在**不改核心水位线逻辑**前提下，加一个模型级贪心再平衡（steepest-ascent 单台腾挪）：

  目标：最大化全体自建收入积分（= Σ 客户 _integrate.self_revenue）。
  每一步：枚举所有 (源集群→目标集群) 单台腾挪，用求解器自己的 _compute_watermarks + _integrate
          在**新机器配置**下重算总收入；取「净增最大且为正」的一台挪动落地；重复至无正收益挪动。
  约束（全部复用求解器口径）：
    1) 峰值可承接硬闸门：_check_peak_feasibility 逐模型 自建(挪后)+三方 ≥ 峰值，否则该挪动非法。
    2) 正收益：仅当两模型总收入净增 > 0 才接受（边际递减无所谓，看整体）。
    3) 源集群更激进削峰：机器变少后水位线从 0 重注 → 源客户水位线自动降低（削峰更狠），
       其损失已计入总收入 delta，净正才接受 —— 天然满足「削峰引入正收益才挪」。
    4) 物理规则：最小保留台数(KSCC/XISHANJU≥2)、禁同模型 rate 套利(低→高速率同模型不搬)。

起点 = 原 solver 跑完后的机器配置（machines_after），故本脚本产出是**在现有策略之上的增量**。
用法：python3 run_time_period_rebalance.py [--keep-ksyun]
"""
import importlib.util
import json
import os
import sys
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('crun', os.path.join(BASE, 'run_time_period_corrected.py'))
crun = importlib.util.module_from_spec(spec); sys.modules['crun'] = crun; spec.loader.exec_module(crun)
tps = sys.modules['app.algorithms.time_period_solver']
EPS = tps.EPS
Y = 60 / 1e6   # TPM·整点积分 → 元/天

import sqlite3


def w(x):
    return f"{x/1e4:,.1f}w"


def yuan(x):
    return f"{x*Y:,.0f}"


def main():
    keep = "--keep-ksyun" in sys.argv
    global RATE_SAFE, CARRY_RATE
    RATE_SAFE = "--rate-safe" in sys.argv
    # 物理正确：机器换模型时带着自己的硬件吞吐(源rate)走，目标模型容量只 +源rate（非目标rate）。
    # 用分数机器实现：目标 += 源rate/目标rate 台，使 目标容量增量 = (源rate/目标rate)×目标rate = 源rate。
    CARRY_RATE = "--carry-rate" in sys.argv
    conn = sqlite3.connect(crun.DB)
    whitelist = crun.build_self_provider_whitelist(conn)
    id_by_name = {n: i for i, n in conn.execute("SELECT id, name FROM customers")}
    name_by_code = {c: n for c, n in conn.execute("SELECT customer_code, name FROM customers")}
    exclude = set() if keep else {id_by_name[n] for n in crun.EXCLUDE_CUSTOMER_NAMES if n in id_by_name}
    demands, _ = crun.build_demand_items(conn, whitelist, exclude)
    clusters, prov = crun.build_clusters(conn)
    crun.apply_current_redundancy(conn, clusters, prov, exclude)
    vendors = crun.build_vendors(conn)
    model_prices = crun.build_model_prices(conn)
    conn.close()

    solver = tps.TimePeriodSolver()
    snapshot = crun.PolicyInputSnapshot(
        captured_at=datetime(2026, 7, 7, 23, 0, 0), algorithm="time_period",
        demands=demands, resources={"clusters": clusters}, monitoring={},
        vendors=vendors, params={"model_prices": model_prices})

    # ---- 起点：先跑原 solver（会就地把 machine_count 更新为其 realloc 后配置）----
    base_result = solver.solve(snapshot)
    machines_solver = {c["cluster_name"]: int(c["machine_count"]) for c in clusters}

    timeline = solver._timeline(demands)
    candidates, _rej = solver._build_candidates(demands, vendors, model_prices, timeline)
    peak_demand = solver._peak_demand_by_model(demands, timeline)
    vendor_cap = solver._vendor_cap_by_model(vendors)
    rate_of = {c["cluster_name"]: float(c.get("tpm_per_machine", 0) or 0) for c in clusters}
    model_of = {c["cluster_name"]: c["deployed_model"] for c in clusters}
    by_name = {c["cluster_name"]: c for c in clusters}

    def total_self_revenue():
        wm, _kept = solver._compute_watermarks(candidates, clusters, timeline)
        after = solver._integrate(candidates, wm, timeline, adjust=True)
        return after["self_revenue"], wm

    def peak_feasible_all():
        feas = solver._check_peak_feasibility(clusters, peak_demand, vendor_cap)
        return all(f["feasible"] for f in feas.values()), feas

    def donatable(name):
        return int(by_name[name]["machine_count"]) - solver._min_reserve_machines(by_name[name])

    # 反「洗产能」：一台机器只能搬一次，禁止集群既当供出方又当接收方。
    # 否则 GLM-5.2(200w)→FP8(260w)→TENCENT(220w) 这种两跳，会把被 legal_pair 直接拦下的
    # 「同模型 200w→220w rate 套利」经第三个模型(glm-5.1)中转洗过来，凭空给 glm-5.2 抬容量。
    donated, received = set(), set()

    def legal_pair(src, tgt):
        if src == tgt:
            return False
        if donatable(src) < 1:
            return False
        # 禁同模型 rate 套利：同模型内低速率→高速率会凭空抬容量
        if model_of[src] == model_of[tgt] and rate_of[src] < rate_of[tgt] - EPS:
            return False
        # 反洗产能：源不能是曾经的接收方，目标不能是曾经的供出方（杜绝两跳中转套利）
        if src in received or tgt in donated:
            return False
        # --rate-safe：跨模型也禁止「搬到更高 rate 集群」——机器随身带自己的硬件吞吐，
        # 不因换集群变快，杜绝 tpm_per_machine 幻影容量（+目标rate−源rate）。
        if RATE_SAFE and rate_of[tgt] > rate_of[src] + EPS:
            return False
        return True

    def model_util_snapshot():
        # 每模型：峰值自建负载(削峰后 Σ_t min) / 自建容量
        wm, _ = total_self_revenue()
        wm_by_rid = {x["report_id"]: x["watermark_self_tpm"] for x in _[1] if False} if False else None
        wmmap, _kept = solver._compute_watermarks(candidates, clusters, timeline)
        # 峰值自建负载 = max_t Σ_i min(需求_i(t), wm_i)
        load = {}
        for c in candidates:
            rid = c.demand.report_id; mdl = c.demand.model_name
            ser = solver._series_of(c.demand, timeline)
            lv = wmmap.get(rid, 0.0)
            arr = load.setdefault(mdl, [0.0] * len(timeline))
            for i, (_, tpm) in enumerate(ser):
                arr[i] += min(tpm, lv)
        cap = solver._self_cap_by_model(clusters)
        return {m: (max(v) if v else 0.0, cap.get(m, 0.0)) for m, v in load.items()}, cap

    def model_swm_shared():
        # 每模型：Σ水位线(已承诺自建) 与 共享容量(非专属集群)。共享池占用率 = Σwm / 共享容量。
        wmmap, _kept = solver._compute_watermarks(candidates, clusters, timeline)
        swm, shared = {}, {}
        for c in candidates:
            swm[c.demand.model_name] = swm.get(c.demand.model_name, 0.0) + wmmap.get(c.demand.report_id, 0.0)
        for cc in clusters:
            if not solver._is_dedicated(cc):
                shared[cc["deployed_model"]] = shared.get(cc["deployed_model"], 0.0) + \
                    float(cc.get("machine_count", 0) or 0) * float(cc.get("tpm_per_machine", 0) or 0)
        return swm, shared

    base_rev, _ = total_self_revenue()
    util_before, _ = model_util_snapshot()
    swm_before, shared_before = model_swm_shared()

    print("=" * 104)
    print(f"time_period 模型级供需再平衡【{'保留' if keep else '剔除'}金山云网络】  收益单位=元/天")
    print("  起点 = 原 solver 腾挪后配置；再平衡目标 = 最大化全体自建收入积分（跨模型单台贪心，正收益即挪）")
    print("=" * 104)

    print(f"\n【再平衡前 · 模型级利用率(削峰后峰值自建负载/自建容量)】  起点自建收入 = {yuan(base_rev)} 元/天")
    for m in sorted(util_before):
        ld, cap = util_before[m]
        print(f"  {m:<14} 容量 {w(cap):>9}  峰值自建负载 {w(ld):>9}  利用率 {ld/cap*100 if cap else 0:>5.1f}%")

    # ---- 贪心：最陡上升单台腾挪 ----
    def add_amt(s, t):
        # carry-rate: 目标只按「源rate÷目标rate」台入账 → 目标容量增量恰为源rate（机器带自己吞吐走）
        return (rate_of[s] / rate_of[t]) if CARRY_RATE else 1.0

    moves = []
    step = 0
    while True:
        cur_rev, _ = total_self_revenue()
        best = None
        for src in clusters:
            sname = src["cluster_name"]
            if donatable(sname) < 1:
                continue
            for tgt in clusters:
                tname = tgt["cluster_name"]
                if not legal_pair(sname, tname):
                    continue
                aa = add_amt(sname, tname)
                by_name[sname]["machine_count"] -= 1
                by_name[tname]["machine_count"] += aa
                ok, _feas = peak_feasible_all()
                rev = total_self_revenue()[0] if ok else float("-inf")
                by_name[sname]["machine_count"] += 1
                by_name[tname]["machine_count"] -= aa
                if ok and rev - cur_rev > EPS and (best is None or rev > best[2]):
                    best = (sname, tname, rev)
        if best is None or best[2] - cur_rev <= EPS:
            break
        sname, tname, rev = best
        by_name[sname]["machine_count"] -= 1
        by_name[tname]["machine_count"] += add_amt(sname, tname)
        donated.add(sname); received.add(tname)
        step += 1
        gain = rev - cur_rev
        tgt_add_cap = rate_of[sname] if CARRY_RATE else rate_of[tname]
        moves.append(dict(step=step, src=sname, tgt=tname, src_model=model_of[sname], tgt_model=model_of[tname],
                          src_rate=rate_of[sname], tgt_rate=rate_of[tname], added_tpm=tgt_add_cap,
                          removed_tpm=rate_of[sname], gain=gain, cum_rev=rev))
        print(f"\n  [挪动{step}] {sname}({model_of[sname]},{w(rate_of[sname])}/台) → "
              f"{tname}({model_of[tname]},{w(rate_of[tname])}/台)")
        print(f"           目标模型容量 +{w(tgt_add_cap)}，源模型容量 −{w(rate_of[sname])}（源客户水位线自动更激进削峰）")
        print(f"           本步净增自建收入 = +{yuan(gain)} 元/天（已扣源集群削峰损失，净正才落地）")

    final_rev, _ = total_self_revenue()
    machines_final = {c["cluster_name"]: round(float(c["machine_count"]), 2) for c in clusters}
    util_after, _ = model_util_snapshot()
    swm_after, shared_after = model_swm_shared()
    ok, feas = peak_feasible_all()

    print("\n" + "=" * 104)
    print("【各集群机器数：原solver配置 → 再平衡后】" + ("（carry-rate：目标按分数台入账=源机器带自身吞吐）" if CARRY_RATE else ""))
    for name in sorted(machines_solver):
        b, a = machines_solver[name], machines_final[name]
        flag = "" if abs(b - a) < 1e-6 else f"   <== {'+' if a > b else ''}{round(a-b,2)}"
        print(f"  {name:<26}{model_of[name]:<14}{b:>5} → {a:<6}{flag}")
    tb = sum(machines_solver.values()); ta = sum(machines_final.values())
    cap_b = sum(v[1] for v in util_before.values()); cap_a = sum(v[1] for v in util_after.values())
    print(f"  物理机器搬动: {len(moves)} 台；名义机器数 {tb} → {ta:.2f}")
    print(f"  自建总容量: {w(cap_b)} → {w(cap_a)}  ({'守恒' if abs(cap_a-cap_b) < 1 else f'{(cap_a-cap_b)/1e4:+.0f}w 幻影!'})")

    print("\n【再平衡后 · 模型级利用率】")
    for m in sorted(util_after):
        ld, cap = util_after[m]
        lb, cb = util_before[m]
        du = (ld/cap if cap else 0) - (lb/cb if cb else 0)
        print(f"  {m:<14} 容量 {w(cap):>9}  峰值自建负载 {w(ld):>9}  利用率 {ld/cap*100 if cap else 0:>5.1f}%  "
              f"({'+' if du >= 0 else ''}{du*100:.1f}pt)")

    print("\n【收益】(元/天)")
    print(f"  原 solver 自建收入(本脚本口径) : {yuan(base_rev)}")
    print(f"  再平衡后自建收入               : {yuan(final_rev)}")
    print(f"  模型级再平衡**额外**收益       : +{yuan(final_rev - base_rev)}  "
          f"(≈ {(final_rev-base_rev)*Y*30/1e4:,.1f} 万元/月 · {(final_rev-base_rev)*Y*365/1e8:,.2f} 亿元/年)")
    print(f"  腾挪机器 {len(moves)} 台；峰值可行性 {'全部 OK' if ok else '存在掉量!'}")

    print("\n【再平衡后逐模型峰值可行性】(自建挪后+三方 ≥ 峰值)")
    print(f"  {'模型':<14}{'客户峰值':>9}{'自建(后)':>9}{'三方额度':>9}{'总承接':>9}{'余量':>9}  判定")
    for m in sorted(feas):
        f = feas[m]
        print(f"  {m:<14}{w(f['peak_demand']):>9}{w(f['self_cap']):>9}{w(f['vendor_cap']):>9}"
              f"{w(f['total_cap']):>9}{w(f['slack']):>9}  {'OK' if f['feasible'] else 'X掉量'}")

    # ---- 逐集群腾挪影响归因：谁受益(水位线↑)、谁能供出(过剩/闲置) ----
    def _wm_under(mc_map):
        for c in clusters:
            c["machine_count"] = mc_map[c["cluster_name"]]
        return solver._compute_watermarks(candidates, clusters, timeline)[0]
    wm_base = dict(_wm_under(machines_solver))
    wm_final = dict(_wm_under(machines_final))   # 恢复到 final 配置
    rid2 = {c.demand.report_id: (c.demand.customer_code, c.demand.model_name) for c in candidates}
    model_deltas = {}
    for rid in set(wm_base) | set(wm_final):
        code, mdl = rid2.get(rid, (None, None))
        if mdl is None:
            continue
        b = wm_base.get(rid, 0.0); a = wm_final.get(rid, 0.0)
        if abs(a - b) < 1e3:
            continue
        model_deltas.setdefault(mdl, []).append(
            {"cust": name_by_code.get(code, code), "wm_b": b, "wm_a": a, "d": a - b})
    for mdl in model_deltas:
        model_deltas[mdl].sort(key=lambda x: -x["d"])
    occ_b = {m: (swm_before.get(m, 0) / shared_before[m] if shared_before.get(m) else None) for m in shared_before}
    occ_a = {m: (swm_after.get(m, 0) / shared_after[m] if shared_after.get(m) else None) for m in shared_after}
    cluster_impact = []
    for c in sorted(clusters, key=lambda x: (x["deployed_model"], x["cluster_name"])):
        nm = c["cluster_name"]; mdl = c["deployed_model"]
        mb_ = machines_solver[nm]; ma_ = machines_final[nm]; dm = ma_ - mb_
        ded = solver._is_dedicated(c)
        role = "receive" if dm > 1e-6 else ("donate" if dm < -1e-6 else "none")
        gainers = [g for g in model_deltas.get(mdl, []) if g["d"] > 0][:4]
        losers = [g for g in model_deltas.get(mdl, []) if g["d"] < 0][:3]
        cluster_impact.append({
            "name": nm, "model": mdl, "mb": mb_, "ma": ma_, "dm": dm, "rate": rate_of[nm],
            "dedicated": ded, "role": role, "gainers": gainers, "losers": losers,
            "occ_b": occ_b.get(mdl), "occ_a": occ_a.get(mdl),
            "participates": mdl in shared_after,
        })

    out = {
        "mode": ("保留" if keep else "剔除") + "金山云网络",
        "rate_mode": "carry-rate" if CARRY_RATE else ("rate-safe" if RATE_SAFE else "target-rate"),
        "base_rev_yuan": base_rev * Y, "final_rev_yuan": final_rev * Y,
        "extra_gain_yuan": (final_rev - base_rev) * Y,
        "machines_solver": machines_solver, "machines_final": machines_final,
        "cluster_impact": cluster_impact,
        "clusters": [{"name": c["cluster_name"], "model": model_of[c["cluster_name"]],
                      "rate": rate_of[c["cluster_name"]],
                      "mb": machines_solver[c["cluster_name"]], "ma": machines_final[c["cluster_name"]]}
                     for c in sorted(clusters, key=lambda x: (x["deployed_model"], x["cluster_name"]))],
        "moves": [dict(mv, gain_yuan=mv["gain"] * Y) for mv in moves],
        "util_before": {m: {"load": util_before[m][0], "cap": util_before[m][1],
                            "swm": swm_before.get(m, 0.0), "shared_cap": shared_before.get(m, 0.0)} for m in util_before},
        "util_after": {m: {"load": util_after[m][0], "cap": util_after[m][1],
                           "swm": swm_after.get(m, 0.0), "shared_cap": shared_after.get(m, 0.0)} for m in util_after},
        "feasibility": feas,
    }
    with open(os.path.join(BASE, "_rebalance_result.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\n[written] _rebalance_result.json")


if __name__ == "__main__":
    main()
