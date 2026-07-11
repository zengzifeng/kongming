#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证实验:单独放开 deepseek 候选过滤(视作可承接),其余一切不变(含 23:00 供出硬门),
看 DeepSeek-V3.2 的 5 台是否还会被搬走。

手法:deepseek 三方额度=0 导致 _best_vendor 返回 None → 需求在 _build_candidates 被拒。
   最小干预 = 把 deepseek 的 vendor_quotas.quota_tpm 置为 >0(purchase_discount 等其它字段不变),
   使候选存活、进入 servable_by_cluster → DeepSeek 集群的 opportunity() 变为非零。
   machine_area/opportunity 只用自建收入(列表价×售卖折扣),与三方额度无关,故此改动干净地
   只翻转"拒收"这一个因素。
"""
import run_time_period as R   # 复用同一套桩加载的原版求解器与构建函数
import sqlite3

DB = R.DB


def build_inputs(deepseek_unreject: bool):
    conn = sqlite3.connect(DB)
    demands, name_by_id = R.build_demand_items(conn)
    clusters, prov = R.build_clusters(conn)
    latest = R.apply_current_redundancy(conn, clusters, prov)
    vendors = R.build_vendors(conn)
    model_prices = R.build_model_prices(conn)
    conn.close()
    if deepseek_unreject:
        # 仅把 deepseek 供应商额度置正,令候选不被拒(视作可自建承接);其余字段不动
        for v in vendors:
            if v["model"] == "deepseek-v3.2" and v["quota_tpm"] <= 0:
                v["quota_tpm"] = 1e12   # 哨兵:仅用于通过 _best_vendor 的 quota>0 判定
    return demands, clusters, vendors, model_prices, name_by_id


def run(deepseek_unreject: bool):
    from datetime import datetime
    demands, clusters, vendors, model_prices, name_by_id = build_inputs(deepseek_unreject)
    snap = R.PolicyInputSnapshot(
        captured_at=datetime(2026, 7, 7, 23, 0, 0), algorithm="time_period",
        demands=demands, resources={"clusters": clusters}, monitoring={},
        vendors=vendors, params={"model_prices": model_prices})
    res = R.tps.TimePeriodSolver().solve(snap)
    return res, demands, vendors, model_prices


def machine_area_of(solver, demand, rate, timeline, model_prices, vendors):
    """复算 _machine_area = 单位自建收入 × Σ_t min(rate, 需求(t)),用于解释机会成本。"""
    unit = solver._unit_self_revenue(demand, model_prices, vendors)
    m = {ts: tpm for ts, tpm in demand.tpm_series}
    return unit * sum(min(rate, max(m.get(ts, 0.0), 0.0)) for ts in timeline)


def summarize(tag, res):
    diag, summ = res.diagnostics, res.summary
    mb, ma = diag["machines_before"], diag["machines_after"]
    ds = ("DeepSeek-V3.2", mb["DeepSeek-V3.2"], ma["DeepSeek-V3.2"])
    ds_moves = [m for m in summ["node_moves"] if m["from_cluster"] == "DeepSeek-V3.2"]
    print(f"\n===== {tag} =====")
    print(f"  被拒需求: {len(diag['rejected'])}  "
          f"({', '.join(sorted({r['reason'] for r in diag['rejected']})) or '无'})")
    print(f"  DeepSeek-V3.2 机器: {ds[1]} → {ds[2]}  (供出 {ds[1]-ds[2]} 台)")
    if ds_moves:
        for m in ds_moves:
            print(f"    搬出: → {m['to_cluster']} {m['machine_count']}台")
    else:
        print("    搬出: 无")
    allm = ", ".join(f"{m['from_cluster']}→{m['to_cluster']}×{m['machine_count']}"
                     for m in summ['node_moves']) or "无"
    print(f"  全部腾挪: {allm}")
    print(f"  收益提升: {summ['expected_revenue_gain']:,.0f}")


def main():
    base, _, _, _ = run(False)
    exp, demands, vendors, model_prices = run(True)

    print("=" * 78)
    print("验证:放开 deepseek 拒收 → DeepSeek 集群机会成本从 0 变正,5 台是否还被搬?")
    print("=" * 78)
    summarize("A. 现状(deepseek 被拒)", base)
    summarize("B. 实验(deepseek 视作可自建,其余不变)", exp)

    # 解释:算出 目标端每机器增益 vs DeepSeek 源机会成本(均在源单台 260w 口径)
    solver = R.tps.TimePeriodSolver()
    timeline = sorted({ts for d in demands for ts, _ in d.tpm_series})
    ds_rate = 2_600_000
    # 目标端:科大讯飞 glm-5.1 在 GLM-5.1-FP8(260w) 的每机器面积
    kd = next(d for d in demands if d.customer_code == "C0009" and d.model_name == "glm-5.1")
    target_gain = machine_area_of(solver, kd, 2_600_000, timeline, model_prices, vendors)
    # 源机会成本:DeepSeek 可服务(deepseek-v3.2)客户里,在源 260w 的最高每机器面积
    ds_cands = [d for d in demands if d.model_name == "deepseek-v3.2"]
    opps = [(d.customer_code, machine_area_of(solver, d, ds_rate, timeline, model_prices, vendors))
            for d in ds_cands]
    opps.sort(key=lambda x: -x[1])
    print("\n" + "=" * 78)
    print("机会成本对比(单台 260w 口径,machine_area = 单位自建收入 × Σ min(260w, 需求(t))):")
    print(f"  目标端 target_gain = 科大讯飞 glm-5.1 @FP8   = {target_gain:>18,.0f}")
    print(f"  源机会成本 opportunity(DeepSeek) 现状(被拒)  = {0:>18,.0f}  → 搬(gain>0)")
    print(f"  源机会成本 opportunity(DeepSeek) 放开后最高   = {opps[0][1]:>18,.0f}  (客户 {opps[0][0]})")
    verdict = "仍搬(目标增益更高)" if target_gain - opps[0][1] > 1e-6 else "不再搬(源机会成本反超)"
    print(f"  判据 target_gain - opportunity = {target_gain - opps[0][1]:,.0f} → {verdict}")
    print("\n  DeepSeek 各 deepseek 客户机会成本(前5):")
    for code, a in opps[:5]:
        print(f"    {code:<8} {a:>18,.0f}")


if __name__ == "__main__":
    main()
