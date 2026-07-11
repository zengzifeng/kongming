#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""口径修订版一体化产物：读 _corrected_result.json + _corrected_demands.json，输出
   切量策略报告.html —— 含三块：
     ① 逐调整收益核算（含核算逻辑公式，任务②）
     ② 客户实跑波形 + 切量水位线（任务③）
     ③ 切量前/后集群利用率（任务③）
   单TPM收入(旧称密度)由 result 里的 customer_revenue_gain 反解：
     单TPM收入 = gain / (Σ自建_after − Σ自建_before)，与求解器口径自洽；示例走真值明细。
用法： python3 gen_corrected_html.py   （默认剔除金山云网络；--keep-ksyun 读 _keepksyun 后缀）
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
SUFFIX = "_keepksyun" if "--keep-ksyun" in sys.argv else ""

result = json.load(open(os.path.join(BASE, f"_corrected_result{SUFFIX}.json"), encoding="utf-8"))
demands = json.load(open(os.path.join(BASE, f"_corrected_demands{SUFFIX}.json"), encoding="utf-8"))

TIMELINE = [f"2026-07-07 {h:02d}:00:00" for h in range(24)]
HOURS = list(range(24))


def series_by_hour(series):
    m = {s["ts"]: s["tpm"] for s in series}
    return [m.get(ts, 0.0) for ts in TIMELINE]


# ---- 反解单TPM收入 + 逐调整收益核算（任务②）----
wm_by_key = {(w["customer_code"], w["model"]): w for w in result["watermark_changes"]}
dem_by_key = {(d["customer_code"], d["model"]): d for d in demands}

attributions = []
for w in result["watermark_changes"]:
    key = (w["customer_code"], w["model"])
    d = dem_by_key.get(key)
    if not d:
        continue
    ser = series_by_hour(d["series"])
    wm = w["watermark_self_tpm"]
    s0 = w["current_self_ratio"]
    sum_after = sum(min(t, wm) for t in ser)
    sum_before = sum(t * s0 for t in ser)
    delta = sum_after - sum_before
    gain = w["customer_revenue_gain"]
    density = gain / delta if abs(delta) > 1e-9 else 0.0
    peak = max(ser) if ser else 0.0
    # 客户全名
    name = next((x["customer"] for x in demands
                 if x["customer_code"] == w["customer_code"] and x["model"] == w["model"]), w["customer_code"])
    attributions.append(dict(
        name=name, code=w["customer_code"], model=w["model"], density=density,
        wm=wm, s0=s0, peak=peak, sum_before=sum_before, sum_after=sum_after,
        delta=delta, gain=gain, fallback=w["fallback_vendor"], series=ser,
    ))
attributions.sort(key=lambda a: -a["gain"])

# ---- 集群利用率 切量前/后（任务③）----
# 口径统一：以 24 整点真实波形的「峰值自建负载」为基准，切量前/后同一时序口径对比（不再混用 23:00 瞬时）。
#   before_self(t) = Σ_i 需求_i(t) × 调整前真自建占比_i        （按当前占比分发）
#   after_self(t)  = Σ_i min(需求_i(t), 水位线_i)              （削峰水位线；无水位线的沿用调整前占比）
#   模型峰值自建负载 = max_t Σ_i self(t)；利用率 = 峰值自建负载 / 自建容量。
#   同一模型的多个自建集群共享同一负载池，故按模型汇总利用率、逐集群展示（含容量/机器数变化）。
clusters = result["clusters"]
mb, ma = result["machines_before"], result["machines_after"]
rate_by = {c["cluster_name"]: c["tpm_per_machine"] for c in clusters}
model_by = {c["cluster_name"]: c["deployed_model"] for c in clusters}
curtpm_by = {c["cluster_name"]: c["current_tpm"] for c in clusters}

# 逐模型、逐整点的自建负载（前/后），基于每个客户的实跑波形
wm_by_key = {(w["customer_code"], w["model"]): w["watermark_self_tpm"] for w in result["watermark_changes"]}
ratio_by_key = {(w["customer_code"], w["model"]): w["current_self_ratio"] for w in result["watermark_changes"]}
before_load_ts = {}   # model -> [24]
after_load_ts = {}
for d in demands:
    model = d["model"]
    ser = series_by_hour(d["series"])
    key = (d["customer_code"], model)
    s0 = ratio_by_key.get(key, d.get("current_self_ratio") or 0.0)
    wm = wm_by_key.get(key)                      # None => 该(客户×模型)无水位线调整，沿用当前占比
    bl = before_load_ts.setdefault(model, [0.0] * 24)
    al = after_load_ts.setdefault(model, [0.0] * 24)
    for h in range(24):
        dem = ser[h]
        bl[h] += dem * s0
        al[h] += (min(dem, wm) if wm is not None else dem * s0)
model_peak_self_before = {m: (max(v) if v else 0.0) for m, v in before_load_ts.items()}
model_peak_self_after = {m: (max(v) if v else 0.0) for m, v in after_load_ts.items()}

# 模型容量 前/后
model_cap_before, model_cap_after = {}, {}
for c in clusters:
    m = c["deployed_model"]
    model_cap_before[m] = model_cap_before.get(m, 0.0) + mb[c["cluster_name"]] * c["tpm_per_machine"]
    model_cap_after[m] = model_cap_after.get(m, 0.0) + ma[c["cluster_name"]] * c["tpm_per_machine"]

def _mutil(model, cap, load):
    return (load / cap) if cap else 0.0

cluster_rows = []
for c in sorted(clusters, key=lambda x: (x["deployed_model"], x["cluster_name"])):
    nm = c["cluster_name"]
    model = c["deployed_model"]
    cap_before = mb[nm] * rate_by[nm]
    cap_after = ma[nm] * rate_by[nm]
    lb = model_peak_self_before.get(model, 0.0)
    la = model_peak_self_after.get(model, 0.0)
    cluster_rows.append(dict(
        name=nm, model=model, mb=mb[nm], ma=ma[nm], rate=rate_by[nm],
        cap_before=cap_before, cap_after=cap_after,
        load_before=curtpm_by[nm],                     # 23:00 实测负载（参考列）
        util_before=_mutil(model, model_cap_before.get(model, 0.0), lb),
        util_after=_mutil(model, model_cap_after.get(model, 0.0), la),
        changed=(mb[nm] != ma[nm]),
    ))

# 模型级 前/后 利用率对比（峰值自建负载 口径统一）
model_util = []
for model in sorted(model_cap_after):
    cap_b = model_cap_before[model]
    cap_a = model_cap_after[model]
    load_b = model_peak_self_before.get(model, 0.0)
    load_a = model_peak_self_after.get(model, 0.0)
    model_util.append(dict(
        model=model, cap_b=cap_b, cap_a=cap_a, load_b=load_b, load_a=load_a,
        util_b=_mutil(model, cap_b, load_b), util_a=_mutil(model, cap_a, load_a),
    ))

total_gain = sum(a["gain"] for a in attributions)

payload = dict(
    mode=result["mode"],
    rev_before=result["self_revenue_before"],
    rev_after=result["self_revenue_after"],
    gain=result["expected_revenue_gain"],
    node_moves=result["node_moves"],
    whitelist=result["whitelist"],
    reclassified=result["reclassified"],
    peak_feasibility=result["peak_feasibility"],
    unit_example=result.get("unit_example"),
    attributions=attributions,
    cluster_rows=cluster_rows,
    model_util=model_util,
    total_gain=total_gain,
    machines_before=mb, machines_after=ma,
)
DATA = json.dumps(payload, ensure_ascii=False)

HTML = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>GLM-5.1 路由口径修订 · 切量策略报告</title>
<style>
:root{--bg:#fbfbfa;--card:#fff;--ink:#111;--sub:#5a5a54;--mut:#8f8e84;--line:#e6e5e1;
  --self:#2a78d6;--vendor:#eb6834;--wm:#111;--pos:#1a9e57;--neg:#d64545;--band:#f4f3f0;--accent:#6b4de6;}
@media(prefers-color-scheme:dark){:root{--bg:#161615;--card:#1f1f1d;--ink:#f4f4f0;--sub:#c2c1b6;--mut:#8f8e84;
  --line:#33332f;--self:#3987e5;--vendor:#e06a37;--wm:#fff;--band:#252523;}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
  font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;line-height:1.5}
.wrap{max-width:1160px;margin:0 auto;padding:30px 26px 70px}
h1{font-size:23px;margin:0 0 6px;font-weight:680}
h2{font-size:17px;margin:34px 0 12px;font-weight:660;display:flex;align-items:center;gap:9px}
h2 .n{background:var(--accent);color:#fff;width:23px;height:23px;border-radius:6px;font-size:13px;
  display:inline-flex;align-items:center;justify-content:center;flex:none}
.lead{color:var(--sub);font-size:13.5px;margin:0 0 3px}
.kpis{display:flex;gap:14px;flex-wrap:wrap;margin:18px 0 6px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:11px;padding:13px 17px;min-width:150px}
.kpi .l{font-size:11.5px;color:var(--mut)}
.kpi .v{font-size:21px;font-weight:700;margin-top:3px}
.kpi .v.pos{color:var(--pos)}.kpi .v.self{color:var(--self)}
.kpi .d{font-size:11px;color:var(--sub);margin-top:2px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin:12px 0}
.warn{border-left:3px solid var(--vendor)}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th,td{padding:6px 9px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--mut);font-weight:600;font-size:11px;text-transform:none}
td.l,th.l{text-align:left}
tr.chg td{background:var(--band)}
.mono{font-family:ui-monospace,"SF Mono",monospace;font-size:11.5px}
.pos{color:var(--pos)}.neg{color:var(--neg)}
.pill{display:inline-block;padding:1px 7px;border-radius:20px;font-size:11px;background:var(--band);color:var(--sub)}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:20px 26px;margin-top:8px}
@media(max-width:820px){.grid{grid-template-columns:1fr}}
.cell .hd{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:1px}
.cell .nm{font-size:13.5px;font-weight:620}.cell .md{font-size:10.5px;color:var(--mut);font-family:ui-monospace,monospace}
.cell .wmv{font-size:11px;color:var(--sub)}
svg{display:block;width:100%;overflow:visible}
.ax{font-size:9px;fill:var(--mut)}
.legend{display:flex;gap:18px;align-items:center;margin:6px 0 4px;font-size:12.5px;flex-wrap:wrap;color:var(--sub)}
.legend .it{display:flex;align-items:center;gap:6px}
.sw{width:13px;height:10px;border-radius:2px}.swl{width:15px;border-top:2px dashed var(--wm)}
.formula{background:var(--band);border-radius:8px;padding:11px 14px;font-size:12.5px;color:var(--sub);
  margin:8px 0;line-height:1.75}
.formula code{font-family:ui-monospace,monospace;color:var(--ink);background:transparent}
details.calc{margin:5px 0}
details.calc summary{cursor:pointer;font-size:12px;color:var(--accent);padding:3px 0}
.calcbox{font-family:ui-monospace,monospace;font-size:11.5px;color:var(--sub);background:var(--band);
  border-radius:7px;padding:9px 12px;margin-top:5px;line-height:1.85;white-space:pre-wrap}
.bar{position:relative;height:15px;background:var(--band);border-radius:4px;overflow:hidden;min-width:90px}
.bar>span{position:absolute;left:0;top:0;height:100%;border-radius:4px}
.util-b{background:var(--mut)}.util-a{background:var(--self)}
.tag{font-size:10.5px;padding:1px 6px;border-radius:5px}
.tag.up{background:#1a9e5722;color:var(--pos)}.tag.dn{background:#d6454522;color:var(--neg)}
.foot{color:var(--mut);font-size:11.5px;margin-top:30px;border-top:1px solid var(--line);padding-top:12px}
.tt{position:fixed;pointer-events:none;background:var(--card);border:1px solid var(--line);border-radius:8px;
  padding:7px 10px;font-size:12px;box-shadow:0 4px 16px rgba(0,0,0,.18);opacity:0;transition:opacity .08s;z-index:20;line-height:1.5}
</style></head>
<body><div class="wrap" id="root"></div><div class="tt" id="tt"></div>
<script>
const D=__DATA__;
const W=(x)=> (x/1e4).toLocaleString('en',{maximumFractionDigits:1})+'w';
const N=(x)=> Math.round(x).toLocaleString('en');
// 单位换算：收入/收益为「TPM·整点」积分口径。× 60min ÷ 1e6(列表价元/百万token) = 元/天。
// 同一因子把 TPM 积分体量换成「百万token/天」，故 收益(元/天)=单TPM收入(元/百万token)×体量(百万token/天) 恒成立。
const Y=60/1e6;
const RMB=(x)=> '¥'+Math.round(x*Y).toLocaleString('en');                 // 元/天(整数)
const RMBw=(x)=> (x*Y/1e4).toLocaleString('en',{maximumFractionDigits:2})+'万'; // 万元/天
const VOL=(x)=> (x*Y).toLocaleString('en',{maximumFractionDigits:1});     // 百万token/天
const root=document.getElementById('root'), tt=document.getElementById('tt');
function el(html){const t=document.createElement('template');t.innerHTML=html.trim();return t.content.firstChild;}

/* ---------- 头部 ---------- */
root.appendChild(el(`<div>
 <h1>GLM-5.1 路由口径修订 · 切量策略报告</h1>
 <p class="lead">口径：<b>自建仅计「本模型自建集群 provider」提供的量</b>；${D.mode}。数据日期 2026-07-07（24 整点波形）。<b>收益均为元/天</b>（按当日波形折算，列表价 元/百万token × 60min ÷ 1e6）。</p>
</div>`));

const kp=el(`<div class="kpis"></div>`);
[['调整前自建收入',RMBw(D.rev_before)+'元/天','self','按修订后真自建口径'],
 ['调整后自建收入',RMBw(D.rev_after)+'元/天','self','削峰水位线 + 机器腾挪后'],
 ['预期收益提升','+'+RMBw(D.gain)+'元/天','pos','≈ '+(D.gain*Y*30/1e4).toLocaleString('en',{maximumFractionDigits:0})+'万元/月 · '+(D.gain*Y*365/1e8).toLocaleString('en',{maximumFractionDigits:2})+'亿元/年'],
 ['逐调整收益合计','+'+RMBw(D.total_gain)+'元/天','pos','对账（应≈上格）'],
].forEach(([l,v,c,d])=>kp.appendChild(el(`<div class="kpi"><div class="l">${l}</div><div class="v ${c}">${v}</div><div class="d">${d}</div></div>`)));
root.appendChild(kp);

/* ---------- 口径修订说明 ---------- */
let wlHtml=Object.entries(D.whitelist).map(([m,ps])=>`<div class="mono">${m}: ${ps.join(', ')}</div>`).join('');
let rcHtml=D.reclassified.map(r=>`<tr><td class="l">${r.customer}</td><td class="l">${r.model}</td><td class="l mono">${r.provider}</td><td>${N(r.avg_tpm)}</td></tr>`).join('');
root.appendChild(el(`<div class="card warn">
 <b>口径修订：自建 provider 白名单</b>
 <div style="font-size:12.5px;color:var(--sub);margin:6px 0">自建承接白名单 = 各自建集群 <code>cluster_resources.raw_json.provider</code> 按模型聚合。挂着「自建」标记、却经<b>非本模型自建集群 provider</b> 承接的量，不算我方该模型自建产能，改判三方，不纳入切量收益考量：</div>
 ${wlHtml}
 <table style="margin-top:10px"><thead><tr><th class="l">客户</th><th class="l">模型</th><th class="l">错挂的非白名单provider</th><th>日均TPM</th></tr></thead><tbody>${rcHtml||'<tr><td class="l" colspan=4>无</td></tr>'}</tbody></table>
 <div style="font-size:12px;color:var(--mut);margin-top:8px">注：金山云网络（转售/网络客户）整户已按要求剔除，其 glm-5.1 经 <code>ksyun-glm47-qy-12003</code>（GLM-4.7 集群）承接的 1.5 亿+ TPM 本就不应计入 glm-5.1 自建，是本次口径修订的最大来源。</div>
</div>`));

/* ---------- ① 逐调整收益核算 ---------- */
root.appendChild(el(`<h2><span class="n">1</span>逐调整收益核算（含核算逻辑）</h2>`));
root.appendChild(el(`<div class="formula">
 <b>核算公式：</b> <code>客户收益 = 单TPM收入 × ( Σ自建_after − Σ自建_before )</code><br>
 · <code>单TPM收入</code>（旧称密度）= 售卖折扣 × 加权列表价（按 输入:输出 token 比 与 缓存命中率 加权），是「每一单位自建 TPM·分钟」的收入密度<br>
 · <code>自建_after(t) = min( 需求(t), 水位线 )</code> —— 切量后固定水位线削峰；<code>自建_before(t) = 需求(t) × 调整前真自建占比</code><br>
 · <code>Σ</code> 为 24 整点积分；机器腾挪不直接产币，通过抬高客户可用自建容量→抬高水位线间接兑现，故收益全部归集到水位线。
</div>`));

/* ---------- 单TPM收入 计算示例（公式代入）---------- */
if(D.unit_example){const u=D.unit_example;
  const f2=x=>Number(x).toLocaleString('en',{minimumFractionDigits:2,maximumFractionDigits:2});
  const f4=x=>Number(x).toLocaleString('en',{minimumFractionDigits:4,maximumFractionDigits:4});
  root.appendChild(el(`<div class="card">
   <b>「单TPM收入」计算示例</b> —— 以 <b>${u.customer}</b> · <span class="mono">${u.model}</span> 为例（口径同求解器 <code>_unit_self_revenue</code>）：
   <div class="calcbox">输入:输出 token 比 io = ${f2(u.input_ratio)}
  → 输入份额 = io/(io+1) = ${f4(u.input_share)} ，  输出份额 = 1/(io+1) = ${f4(u.output_share)}
缓存命中率 = ${(u.cache_hit_rate*100).toFixed(2)}%
三档列表价：命中价 ${f2(u.input_hit_price)} ，未命中价 ${f2(u.input_miss_price)} ，输出价 ${f2(u.output_price)}

加权列表价 = 输入份额×命中率×命中价 + 输入份额×(1−命中率)×未命中价 + 输出份额×输出价
         = ${f4(u.input_share)}×${(u.cache_hit_rate*100).toFixed(2)}%×${f2(u.input_hit_price)} + ${f4(u.input_share)}×${((1-u.cache_hit_rate)*100).toFixed(2)}%×${f2(u.input_miss_price)} + ${f4(u.output_share)}×${f2(u.output_price)}
         = ${f4(u.term_hit)} + ${f4(u.term_miss)} + ${f4(u.term_out)}
         = ${f4(u.weighted_list_price)}

单TPM收入 = 加权列表价 × 售卖折扣 = ${f4(u.weighted_list_price)} × ${f2(u.discount_rate)} = <b>${f4(u.unit_self_revenue)}</b>  元/百万token</div>
   <div style="font-size:11.5px;color:var(--mut);margin-top:6px">注：单位为<b>元/百万token</b>（列表价即元/百万token）。io 比越高（输入占比大）→ 越贴近输入档价；缓存命中率越高 → 输入侧越多走更低的命中价，单TPM收入越低。该值即上表「单TPM收入」列。乘以自建体量（百万token/天）即得收益（元/天）。</div>
  </div>`));
}

const nm_moves={};
D.node_moves.forEach(m=>{const c=(m.reason.match(/C\d+/)||[])[0]; if(c){(nm_moves[c]=nm_moves[c]||[]).push(m);}});

const tbl=el(`<div class="card" style="overflow-x:auto"><table>
 <thead><tr>
  <th class="l">客户</th><th class="l">模型</th><th>单TPM收入<div style="font-weight:400;color:var(--mut)">元/百万tok</div></th><th>前自建占比</th>
  <th>水位线(自建上限)</th><th>Σ自建_before<div style="font-weight:400;color:var(--mut)">百万tok/日</div></th><th>Σ自建_after<div style="font-weight:400;color:var(--mut)">百万tok/日</div></th><th>ΔΣ自建<div style="font-weight:400;color:var(--mut)">百万tok/日</div></th><th>收益<div style="font-weight:400;color:var(--mut)">元/天</div></th>
 </tr></thead><tbody id="attb"></tbody>
 <tfoot><tr><td class="l" colspan=8 style="text-align:right"><b>合计</b></td><td><b class="pos">+${RMB(D.total_gain)}</b></td></tr></tfoot>
</table></div>`);
root.appendChild(tbl);
const tb=tbl.querySelector('#attb');
D.attributions.forEach(a=>{
  const g=a.gain>=0?'pos':'neg';
  const dl=a.delta>=0?'pos':'neg';
  tb.appendChild(el(`<tr>
    <td class="l">${a.name}</td><td class="l mono">${a.model}</td>
    <td class="mono">${a.density.toFixed(4)}</td>
    <td>${(a.s0*100).toFixed(0)}%</td>
    <td>${N(a.wm)}<div class="mono" style="color:var(--mut);font-size:10px">${W(a.wm)}</div></td>
    <td class="mono">${VOL(a.sum_before)}</td>
    <td class="mono">${VOL(a.sum_after)}</td>
    <td class="mono ${dl}">${a.delta>=0?'+':''}${VOL(a.delta)}</td>
    <td class="${g}"><b>${a.gain>=0?'+':''}${RMB(a.gain)}</b>${(nm_moves[a.code]?' <span class="pill">含腾挪</span>':'')}</td>
  </tr>`));
  // 展开：逐项核算
  const mv=(nm_moves[a.code]||[]).map(m=>`  └ 关联机器腾挪：${m.from_cluster}→${m.to_cluster} ×${m.machine_count}台（目标+${W(m.added_tpm)}，为承接本客户抬高可用自建容量）`).join('\n');
  tb.appendChild(el(`<tr><td class="l" colspan=9 style="padding:0 9px 8px">
    <details class="calc"><summary>核算过程</summary>
     <div class="calcbox">单TPM收入 = ${a.density.toFixed(4)} 元/百万token  （售卖折扣 × 加权列表价）
Σ自建_before = Σ 需求(t)×${(a.s0*100).toFixed(1)}% ×60min÷1e6 = ${VOL(a.sum_before)} 百万token/天
Σ自建_after  = Σ min(需求(t), 水位线${W(a.wm)}) ×60min÷1e6 = ${VOL(a.sum_after)} 百万token/天
ΔΣ自建 = ${VOL(a.sum_after)} − ${VOL(a.sum_before)} = ${a.delta>=0?'+':''}${VOL(a.delta)} 百万token/天
收益 = 单TPM收入 × ΔΣ自建 = ${a.density.toFixed(4)} × (${a.delta>=0?'+':''}${VOL(a.delta)}) = ${a.gain>=0?'+':''}${RMB(a.gain)}/天
兜底三方 = ${a.fallback}${mv?'\n'+mv:''}</div>
    </details></td></tr>`));
});

/* ---------- ② 客户实跑波形 + 切量水位线 ---------- */
root.appendChild(el(`<h2><span class="n">2</span>客户实跑波形 × 切量水位线</h2>`));
root.appendChild(el(`<div class="legend">
 <span class="it"><span class="sw" style="background:var(--self)"></span>自建承接（水位线下）</span>
 <span class="it"><span class="sw" style="background:var(--vendor)"></span>三方溢出（水位线上）</span>
 <span class="it"><span class="swl"></span>切量水位线（固定）</span>
 <span class="it" style="color:var(--mut)">— 实跑需求曲线</span>
</div>`));
const grid=el(`<div class="grid" id="grid"></div>`);root.appendChild(grid);
const SW=320,SH=140,ML=38,MR=10,MT=12,MB=20,pw=SW-ML-MR,ph=SH-MT-MB;
// 只画有量的（按收益绝对值排序，取前 12）
const drawList=D.attributions.filter(a=>a.peak>0).slice().sort((x,y)=>Math.abs(y.gain)-Math.abs(x.gain)).slice(0,12);
drawList.forEach(a=>{
  const pts=a.series.map((t,h)=>({h,d:t,s:Math.min(t,a.wm),v:Math.max(t-a.wm,0)}));
  const maxY=Math.max(a.wm,...pts.map(p=>p.d))*1.08||1;
  const X=h=>ML+(h/23)*pw, Y=v=>MT+ph-(v/maxY)*ph;
  const selfArea=pts.map(p=>`${X(p.h)},${Y(p.s)}`).join(' ')+' '+pts.slice().reverse().map(p=>`${X(p.h)},${Y(0)}`).join(' ');
  const vendArea=pts.map(p=>`${X(p.h)},${Y(p.d)}`).join(' ')+' '+pts.slice().reverse().map(p=>`${X(p.h)},${Y(p.s)}`).join(' ');
  const demLine=pts.map((p,i)=>`${i?'L':'M'}${X(p.h)},${Y(p.d)}`).join('');
  const yT=[0,Math.round(maxY/2),Math.round(maxY)];
  const cell=el(`<div class="cell">
   <div class="hd"><span><span class="nm">${a.name}</span> <span class="md">${a.model}</span></span>
     <span class="wmv">水位线 ${W(a.wm)} · 前自建 ${(a.s0*100).toFixed(0)}%</span></div>
   <svg viewBox="0 0 ${SW} ${SH}">
    ${yT.map(t=>`<line x1="${ML}" y1="${Y(t)}" x2="${SW-MR}" y2="${Y(t)}" stroke="var(--line)"/>
      <text class="ax" x="${ML-4}" y="${Y(t)+3}" text-anchor="end">${W(t)}</text>`).join('')}
    <polygon points="${selfArea}" fill="var(--self)" opacity=".22"/>
    <polygon points="${vendArea}" fill="var(--vendor)" opacity=".22"/>
    <path d="${demLine}" fill="none" stroke="var(--mut)" stroke-width="1.4"/>
    <polyline points="${pts.map(p=>`${X(p.h)},${Y(p.s)}`).join(' ')}" fill="none" stroke="var(--self)" stroke-width="1.9"/>
    <line x1="${ML}" y1="${Y(a.wm)}" x2="${SW-MR}" y2="${Y(a.wm)}" stroke="var(--wm)" stroke-width="1.4" stroke-dasharray="5 3"/>
    ${[0,6,12,18,23].map(h=>`<text class="ax" x="${X(h)}" y="${SH-6}" text-anchor="middle">${h}${h===23?'h':''}</text>`).join('')}
    ${pts.map(p=>`<rect x="${X(p.h)-pw/46}" y="${MT}" width="${pw/23}" height="${ph}" fill="transparent"
       data-h="${p.h}" data-d="${p.d.toFixed(0)}" data-s="${p.s.toFixed(0)}" data-v="${p.v.toFixed(0)}" data-c="${a.name}"/>`).join('')}
   </svg></div>`);
  cell.querySelectorAll('rect').forEach(r=>{
    r.addEventListener('mousemove',e=>{
      const d=+r.dataset.d,s=+r.dataset.s,v=+r.dataset.v;
      tt.innerHTML=`<b>${r.dataset.c} · ${r.dataset.h}:00</b><br>需求 ${N(d)}<br>
        <span style="color:var(--self)">自建 ${N(s)}</span> (${d?Math.round(s/d*100):0}%)<br>
        <span style="color:var(--vendor)">三方 ${N(v)}</span> (${d?Math.round(v/d*100):0}%)`;
      tt.style.opacity=1;tt.style.left=Math.min(e.clientX+14,innerWidth-190)+'px';tt.style.top=(e.clientY+14)+'px';});
    r.addEventListener('mouseleave',()=>tt.style.opacity=0);
  });
  grid.appendChild(cell);
});

/* ---------- ③ 切量前/后集群利用率 ---------- */
root.appendChild(el(`<h2><span class="n">3</span>切量前 / 后 集群利用率</h2>`));
root.appendChild(el(`<p class="lead">机器总量守恒（仅集群间腾挪）。利用率口径统一为「24 整点波形的<b>峰值自建负载 / 自建容量</b>」：切量前按当前占比分发，切量后按削峰水位线。同一模型的多个自建集群共享负载池，故利用率按模型汇总、逐集群展示。灰条=切量前，蓝条=切量后。行底色=本次有机器增减的集群。</p>`));

// 集群级机器数变化表（含前/后利用率）
const ctab=el(`<div class="card" style="overflow-x:auto"><table>
 <thead><tr><th class="l">集群</th><th class="l">模型</th><th>单台能力</th><th>机器数 前→后</th>
   <th>满容量 前→后</th><th>23:00实测负载</th><th>切量前利用率</th><th>切量后利用率</th></tr></thead>
 <tbody id="cbody"></tbody></table></div>`);
root.appendChild(ctab);
const cb=ctab.querySelector('#cbody');
D.cluster_rows.forEach(c=>{
  const chg=c.mb!==c.ma;
  const tag=chg?(c.ma>c.mb?`<span class="tag up">+${c.ma-c.mb}</span>`:`<span class="tag dn">${c.ma-c.mb}</span>`):'';
  cb.appendChild(el(`<tr class="${chg?'chg':''}">
    <td class="l">${c.name}</td><td class="l mono">${c.model}</td>
    <td>${W(c.rate)}</td>
    <td>${c.mb} → ${c.ma} ${tag}</td>
    <td class="mono">${W(c.cap_before)} → ${W(c.cap_after)}</td>
    <td class="mono">${W(c.load_before)}</td>
    <td>${(c.util_before*100).toFixed(0)}%
      <div class="bar"><span class="util-b" style="width:${Math.min(c.util_before*100,100)}%"></span></div></td>
    <td>${(c.util_after*100).toFixed(0)}%
      <div class="bar"><span class="util-a" style="width:${Math.min(c.util_after*100,100)}%"></span></div></td>
  </tr>`));
});

// 模型级 前/后 利用率对比
const mtab=el(`<div class="card" style="overflow-x:auto"><table>
 <thead><tr><th class="l">模型</th><th>自建容量 前→后</th>
   <th>切量前峰值自建负载</th><th>前利用率</th>
   <th>切量后峰值自建负载</th><th>后利用率</th><th>对比</th></tr></thead>
 <tbody id="mbody"></tbody></table></div>`);
root.appendChild(mtab);
const mbd=mtab.querySelector('#mbody');
D.model_util.forEach(m=>{
  const up=m.util_a>=m.util_b;
  mbd.appendChild(el(`<tr>
    <td class="l mono">${m.model}</td>
    <td class="mono">${W(m.cap_b)} → ${W(m.cap_a)}</td>
    <td class="mono">${W(m.load_b)}</td>
    <td>${(m.util_b*100).toFixed(0)}%<div class="bar"><span class="util-b" style="width:${Math.min(m.util_b*100,100)}%"></span></div></td>
    <td class="mono">${W(m.load_a)}</td>
    <td>${(m.util_a*100).toFixed(0)}%<div class="bar"><span class="util-a" style="width:${Math.min(m.util_a*100,100)}%"></span></div></td>
    <td><span class="tag ${up?'up':'dn'}">${up?'▲':'▼'}${Math.abs((m.util_a-m.util_b)*100).toFixed(0)}pt</span></td>
  </tr>`));
});

/* ---------- 峰值可行性 ---------- */
const pf=D.peak_feasibility;
let pfrows=Object.keys(pf).sort().map(m=>{const f=pf[m];
  return `<tr><td class="l mono">${m}</td><td>${W(f.peak_demand)}</td><td>${W(f.self_cap)}</td>
   <td>${W(f.vendor_cap)}</td><td>${W(f.total_cap)}</td><td class="${f.slack>=0?'pos':'neg'}">${W(f.slack)}</td>
   <td><span class="tag ${f.feasible?'up':'dn'}">${f.feasible?'OK':'掉量'}</span></td></tr>`;}).join('');
root.appendChild(el(`<div class="card"><b>逐模型峰值可行性</b>（客户按波形跑，自建调整后+三方 ≥ 峰值）
 <table style="margin-top:8px"><thead><tr><th class="l">模型</th><th>客户峰值</th><th>自建(后)</th>
   <th>三方额度</th><th>总承接</th><th>余量</th><th>判定</th></tr></thead><tbody>${pfrows}</tbody></table></div>`));

root.appendChild(el(`<div class="foot">
 口径修订版 · 求解器 time_period_solver.py 未改，仅修正喂入 demand 的自建/三方划分（provider 白名单）与客户范围（剔除金山云网络）。<br>
 复现：<span class="mono">python3 run_time_period_corrected.py</span> → <span class="mono">python3 gen_corrected_html.py</span>。收益单位=元/天：自建TPM积分 × 单TPM收入(元/百万token) × 60min ÷ 1e6，按 2026-07-07 当日波形折算。
</div>`));
addEventListener('scroll',()=>tt.style.opacity=0,true);
</script></body></html>"""

out = os.path.join(BASE, f"切量策略报告{SUFFIX}.html")
open(out, "w", encoding="utf-8").write(HTML.replace("__DATA__", DATA))
print("[written]", os.path.basename(out))
print(f"  逐调整收益合计 = {total_gain:,.0f}  (求解器汇总 {result['expected_revenue_gain']:,.0f})")
print(f"  客户波形卡片 = {len([a for a in attributions if a['peak']>0])}  集群 = {len(cluster_rows)}")
