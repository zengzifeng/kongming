# -*- coding: utf-8 -*-
"""生成两个算法的分步动画轨迹（_algo_trace.json）。
做法：用小而清晰的隔离场景，逐步复现算法决策并记录轨迹；同时用真实求解器跑同一场景，
断言复现的最终态（水位线 / 接纳 / 腾挪）与求解器一致，确保动画忠实。"""
from __future__ import annotations
import sys, json, io
from math import ceil
from pathlib import Path
from datetime import datetime, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "backend"))
from app.algorithms.base import DemandSnapshotItem, PolicyInputSnapshot  # noqa: E402
from app.algorithms.time_period_solver import TimePeriodSolver, EPS  # noqa: E402
from app.algorithms.realtime_solver import RealtimeSolver  # noqa: E402

H = 24


def tsser(vals):
    base = datetime(2026, 7, 1, tzinfo=timezone.utc)
    return [(base.replace(hour=h).isoformat(), float(v)) for h, v in enumerate(vals)]


def prices_for(models):
    return {m: {"input_cache_hit_price": 0.0002, "input_cache_miss_price": 0.0010, "output_price": 0.0010} for m in models}


def vendors_for(models):
    return [{"vendor": "tp", "model": m, "quota_tpm": 9_000_000, "unit_cost": 0.0002, "unit_price": 0.0010} for m in models]


# ============================================================================
# 1) TIME_PERIOD —— 完整流程：初始态 → Step C 机器重分配 → Step D 边际收入注水 → 最终态
# ============================================================================
def build_tp():
    # 跨模型机器重分配（共享池）：glm 满容量偏小、承接不下 glm 客户；kimi 集群产能有余（只有一个
    # 小客户 kimi-low）→ 把 kimi 的空闲机器**重部署为 glm** 给 glm 增容。各模型的客户各自在**本模型**
    # 容量里注水。
    clusters = [
        {"cluster_name": "glm-main", "deployed_model": "glm", "machine_count": 2, "tpm_per_machine": 50_000,
         "current_redundant_tpm": 100_000, "current_redundant_machines": 0},   # 2×50k=100k（glm 承接方，偏小）
        {"cluster_name": "kimi-c", "deployed_model": "kimi", "machine_count": 4, "tpm_per_machine": 50_000,
         "current_redundant_tpm": 150_000, "current_redundant_machines": 3},   # 4×50k=200k，只服务小客户、3 台空闲
    ]

    def flat(v): return [v] * H
    def spike(base, pk, hrs): return [pk if h in hrs else base for h in range(H)]
    custs = [
        ("spike-co", "glm", 0.95, 0.0, spike(40_000, 300_000, {13, 14})),   # glm · 高价值窄尖峰
        ("flat-co", "glm", 0.70, 0.3, flat(120_000)),                        # glm · 宽常态、当前自建 0.3
        ("kimi-low", "kimi", 0.50, 0.0, flat(40_000)),                       # kimi · 低价值小客户
    ]
    demands = [DemandSnapshotItem(report_id=rid, customer_code=rid, model_name=mdl, expected_tpm=max(v),
                                  expected_rpm=0, discount_rate=disc, input_ratio=1.0, cache_hit_rate=0.0,
                                  current_self_ratio=sr, current_vendor_ratios={"tp": max(1 - sr, 0)},
                                  tpm_series=tsser(v))
               for (rid, mdl, disc, sr, v) in custs]
    snap = PolicyInputSnapshot(captured_at=datetime.now(timezone.utc), algorithm="time_period",
                               demands=demands, resources={"clusters": [dict(c) for c in clusters]}, monitoring={},
                               vendors=vendors_for(["glm", "kimi"]), params={"model_prices": prices_for(["glm", "kimi"])})
    machines_before = {c["cluster_name"]: c["machine_count"] for c in clusters}
    result = TimePeriodSolver().solve(snap)
    solver_wm = {w["report_id"]: w["watermark_self_tpm"] for w in result.summary["watermark_changes"]}
    machines_after = result.diagnostics["machines_after"]
    node_moves = result.summary["node_moves"]

    sol = TimePeriodSolver()
    series = {rid: [v for _, v in tsser(vals)] for (rid, _, _, _, vals) in custs}
    unit = {d.report_id: sol._unit_self_revenue(d, prices_for(["glm", "kimi"]), vendors_for(["glm", "kimi"])) for d in demands}
    peak = {rid: max(series[rid]) for rid in series}
    model_of = {rid: mdl for (rid, mdl, *_ ) in custs}
    sr_of = {rid: sr for (rid, mdl, disc, sr, vals) in custs}

    trace = []
    # ---- Step C：机器搬运步骤（取求解器真实 node_moves）----
    for mv in node_moves:
        trace.append({"phase": "move", "from": mv["from_cluster"], "to": mv["to_cluster"],
                      "machines": mv["machine_count"], "from_rate": mv["from_tpm_per_machine"],
                      "to_rate": mv["to_tpm_per_machine"], "added": mv["added_tpm"], "removed": mv["removed_tpm"],
                      "reason": mv["reason"]})

    # ---- Step D：**按模型分组**，各模型客户在本模型腾挪后总容量上纯边际收入注水 ----
    models = ["glm", "kimi"]
    model_caps = {m: sum(machines_after[c["cluster_name"]] * c["tpm_per_machine"]
                         for c in clusters if c["deployed_model"] == m) for m in models}
    level = {rid: 0.0 for rid in series}   # 全局水位（跨模型），fill 步逐一抬升

    def time_above(rid, lv):
        return sum(1 for v in series[rid] if v > lv + EPS)

    for m in models:
        ids = [rid for rid in series if model_of[rid] == m]
        if not ids:
            continue
        cap_left = model_caps[m]
        breakpoints = {rid: sorted(set(series[rid])) for rid in ids}
        capped = set()

        def next_bp(rid, lv):
            for bp in breakpoints[rid]:
                if bp > lv + EPS:
                    return min(bp, peak[rid])
            return peak[rid]

        while True:
            best, bm = None, 0.0
            marg = {}
            for rid in ids:
                if rid in capped or level[rid] >= peak[rid] - EPS:
                    marg[rid] = 0.0
                    continue
                mv = unit[rid] * time_above(rid, level[rid])
                marg[rid] = mv
                if mv > bm + EPS:
                    bm, best = mv, rid
            if best is None:
                break
            tgt = next_bp(best, level[best])
            want = tgt - level[best]
            got = min(want, cap_left)
            frm = level[best]
            level[best] += got
            cap_left -= got
            capped_now = got < want - EPS or level[best] >= peak[best] - EPS
            if capped_now:
                capped.add(best)
            trace.append({"phase": "fill", "model": m, "cand": best, "marg": marg,
                          "time_above": time_above(best, frm), "from": frm, "to": level[best],
                          "want": want, "got": got, "cap_left": cap_left, "model_cap": model_caps[m],
                          "capped": capped_now, "level": dict(level)})

    # 交叉校验：复现最终水位 == 求解器（全部客户）
    for rid in series:
        assert abs(level[rid] - solver_wm.get(rid, 0.0)) < 1.0, (rid, level[rid], solver_wm.get(rid))
    print(f"[time_period] 复现最终水位与求解器一致 ✓  moves={len(node_moves)}  "
          f"wm={[(r, round(level[r]/1e3)) for r in series]}k")

    return {
        "clusters": [{"id": c["cluster_name"], "model": c["deployed_model"], "rate": c["tpm_per_machine"],
                      "machines0": machines_before[c["cluster_name"]],
                      "machines1": machines_after[c["cluster_name"]]} for c in clusters],
        "models": models,
        "model_caps": model_caps,
        "customers": [{"id": rid, "model": model_of[rid], "density": unit[rid], "peak": peak[rid],
                       "self_ratio": sr_of[rid], "series": series[rid]} for rid in series],
        "trace": trace,
        "final_wm": {r: level[r] for r in series},
    }


# ============================================================================
# 2) REALTIME —— 统一单趟：密度序 → 现有冗余分配 → 不足则腾挪（native/received）→ 记账
# ============================================================================
def build_rt():
    # 高密度 A(需大)、中密度 B；glm-main 冗余有限，donor(不同模型) 有空闲机器可腾挪
    clusters = [
        {"cluster_name": "glm-main", "deployed_model": "glm", "machine_count": 4, "tpm_per_machine": 50_000,
         "current_redundant_tpm": 60_000, "current_redundant_machines": 0},   # 只有 60k 冗余
        {"cluster_name": "donor", "deployed_model": "kimi", "machine_count": 3, "tpm_per_machine": 50_000,
         "current_redundant_tpm": 150_000, "current_redundant_machines": 3},  # 3 台空闲，可搬来重部署为 glm
    ]
    def dem(rid, tpm, disc):
        return DemandSnapshotItem(report_id=rid, customer_code=rid, model_name="glm", expected_tpm=tpm,
                                  expected_rpm=0, discount_rate=disc, input_ratio=1.0, cache_hit_rate=0.0,
                                  current_self_ratio=0.0, current_vendor_ratios={"tp": 1.0})
    demands = [dem("A-hi", 120_000, 0.95), dem("B-mid", 80_000, 0.6)]
    snap = PolicyInputSnapshot(captured_at=datetime.now(timezone.utc), algorithm="realtime",
                               demands=demands, resources={"clusters": [dict(c) for c in clusters]}, monitoring={},
                               vendors=vendors_for(["glm", "kimi"]), params={"model_prices": prices_for(["glm", "kimi"])})
    result = RealtimeSolver().solve(snap)
    acc = {a["report_id"]: a for a in result.summary["accepted_customers"]}

    # ---- 复现单趟 ----
    sol = RealtimeSolver()
    unit = {d.report_id: sol._unit_self_revenue(d, prices_for(["glm", "kimi"]), vendors_for(["glm", "kimi"])) for d in demands}
    cands = sorted(demands, key=lambda d: unit[d.report_id], reverse=True)
    native = {c["cluster_name"]: c["current_redundant_tpm"] for c in clusters}
    received = {c["cluster_name"]: 0.0 for c in clusters}
    extra = {c["cluster_name"]: c["current_redundant_machines"] for c in clusters}
    rate = {c["cluster_name"]: c["tpm_per_machine"] for c in clusters}
    trace = []
    for d in cands:
        rid = d.report_id
        gap = d.expected_tpm  # self_ratio 0 -> 缺口 = 全量
        # ① 现有冗余（glm-main 是唯一 glm 集群）
        avail = native["glm-main"] + received["glm-main"]
        take1 = min(gap, avail)
        received["glm-main"] -= min(take1, received["glm-main"])
        native["glm-main"] -= max(0.0, take1 - (min(take1, received["glm-main"] + take1)))  # 先扣received
        # 简化：单 glm 集群，received 起始0 -> 直接扣 native
        native["glm-main"] = max(0.0, avail - take1) - received["glm-main"]
        native["glm-main"] = round(native["glm-main"], 3)
        allocated = take1
        step = {"cand": rid, "density": unit[rid], "gap": gap, "existing": take1,
                "native_after": dict(native), "moves": []}
        # ② 不足则腾挪：target=glm-main（唯一glm），源=donor（有空闲机器）
        if gap - allocated > 1e-6:
            need = gap - allocated
            src = "donor"
            movable = min(extra[src], int(native[src] // rate[src]))
            machines = min(movable, max(1, ceil(need / rate["glm-main"])))
            if machines > 0:
                added = machines * rate["glm-main"]
                removed = machines * rate[src]
                extra[src] -= machines
                native[src] -= removed
                received["glm-main"] += added
                take2 = min(need, received["glm-main"])
                received["glm-main"] -= take2
                allocated += take2
                step["moves"].append({"from": src, "to": "glm-main", "machines": machines,
                                       "added": added, "removed": removed})
        step["allocated"] = allocated
        step["to_self_ratio"] = min(1.0, allocated / d.expected_tpm)
        step["native"] = dict(native); step["received"] = dict(received); step["extra"] = dict(extra)
        trace.append(step)

    # 交叉校验：复现 allocated 与求解器 incremental_tpm_self 一致
    for st in trace:
        exp = acc.get(st["cand"], {}).get("incremental_tpm_self")
        if exp is not None:
            assert abs(st["allocated"] - exp) < 1.0, (st["cand"], st["allocated"], exp)
    print(f"[realtime] 复现分配与求解器一致 ✓  {[(st['cand'], round(st['allocated']/1e3)) for st in trace]}k")

    return {
        "clusters": [{"id": c["cluster_name"], "model": c["deployed_model"], "rate": c["tpm_per_machine"],
                      "native0": c["current_redundant_tpm"], "machines0": c["machine_count"],
                      "idle0": c["current_redundant_machines"]} for c in clusters],
        "candidates": [{"id": d.report_id, "density": unit[d.report_id], "gap": d.expected_tpm} for d in cands],
        "trace": trace,
    }


out = {"time_period": build_tp(), "realtime": build_rt()}
(ROOT / "_algo_trace.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("已导出 -> _algo_trace.json")
