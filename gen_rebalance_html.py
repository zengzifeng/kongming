#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模型级供需再平衡 · 效果报告 HTML —— 读 _rebalance_result.json，产出「再平衡前/后」对比页：
   ① 关键收益（额外 元/天，含月/年折算）与腾挪概览
   ② 集群机器数 原solver配置 → 再平衡后（含流向）
   ③ 模型级利用率 前/后 对比（含自建承接量变化）
   ④ 再平衡后逐模型峰值可行性
口径：单机吞吐按**目标集群速率**（模型/客户行为决定承载力）；收益单位=元/天。
用法：python3 run_time_period_rebalance.py → python3 gen_rebalance_html.py
"""
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
R = json.load(open(os.path.join(BASE, "_rebalance_result.json"), encoding="utf-8"))

# 模型级容量/利用率（前/后）合并
# 容量按集群配置权威计算(机器数×单台承载)；承接量来自削峰后峰值自建负载。
# 无三方额度的模型(如 deepseek，vendor_cap=0)没有切量候选，不参与再平衡 → 标记 participates=False。
cap_b_by, cap_a_by = {}, {}
for c in R["clusters"]:
    cap_b_by[c["model"]] = cap_b_by.get(c["model"], 0.0) + c["mb"] * c["rate"]
    cap_a_by[c["model"]] = cap_a_by.get(c["model"], 0.0) + c["ma"] * c["rate"]

models = sorted(set(list(cap_b_by) + [c["model"] for c in R["clusters"]]))
model_rows = []
for m in models:
    ub = R["util_before"].get(m)
    ua = R["util_after"].get(m)
    fb = R["feasibility"].get(m, {})
    participates = (ub is not None) or (ua is not None)
    load_b = ub["load"] if ub else None
    load_a = ua["load"] if ua else None
    cap_b = cap_b_by.get(m, 0.0)
    cap_a = cap_a_by.get(m, 0.0)
    model_rows.append(dict(
        model=m, participates=participates, cap_b=cap_b, cap_a=cap_a,
        load_b=load_b, load_a=load_a,
        util_b=(load_b / cap_b if (load_b is not None and cap_b) else None),
        util_a=(load_a / cap_a if (load_a is not None and cap_a) else None),
        swm_b=(ub["swm"] if ub else None), shared_b=(ub["shared_cap"] if ub else None),
        swm_a=(ua["swm"] if ua else None), shared_a=(ua["shared_cap"] if ua else None),
        occ_b=(ub["swm"] / ub["shared_cap"] if (ub and ub["shared_cap"]) else None),
        occ_a=(ua["swm"] / ua["shared_cap"] if (ua and ua["shared_cap"]) else None),
        peak=fb.get("peak_demand", 0), vendor_cap=fb.get("vendor_cap", 0),
    ))

# 腾挪流向聚合（源→目标：台数、累计收益）
flow = {}
for mv in R["moves"]:
    k = (mv["src"], mv["tgt"], mv["src_model"], mv["tgt_model"], mv["src_rate"], mv["tgt_rate"])
    f = flow.setdefault(k, {"n": 0, "gain": 0.0})
    f["n"] += 1
    f["gain"] += mv["gain_yuan"]
flows = [dict(src=k[0], tgt=k[1], src_model=k[2], tgt_model=k[3], src_rate=k[4], tgt_rate=k[5],
              n=v["n"], gain=v["gain"]) for k, v in
         sorted(flow.items(), key=lambda kv: -kv[1]["gain"])]

# 累计收益曲线（逐步）
curve = [{"step": mv["step"], "gain": mv["gain_yuan"], "cum": (R["base_rev_yuan"] +
          sum(x["gain_yuan"] for x in R["moves"][:i + 1]))} for i, mv in enumerate(R["moves"])]

payload = dict(
    mode=R["mode"], rate_mode=R.get("rate_mode", "target-rate"),
    base=R["base_rev_yuan"], final=R["final_rev_yuan"], extra=R["extra_gain_yuan"],
    n_moves=len(R["moves"]),
    clusters=R["clusters"], model_rows=model_rows, flows=flows, curve=curve,
    cluster_impact=R["cluster_impact"],
    feasibility=R["feasibility"],
)
DATA = json.dumps(payload, ensure_ascii=False)

HTML = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>模型级供需再平衡 · 效果报告</title>
<style>
:root{--bg:#fbfbfa;--card:#fff;--ink:#111;--sub:#5a5a54;--mut:#8f8e84;--line:#e6e5e1;
  --b:#8f8e84;--a:#2a78d6;--pos:#1a9e57;--neg:#d64545;--band:#f4f3f0;--accent:#6b4de6;--warn:#eb6834;}
@media(prefers-color-scheme:dark){:root{--bg:#161615;--card:#1f1f1d;--ink:#f4f4f0;--sub:#c2c1b6;--mut:#8f8e84;
  --line:#33332f;--a:#3987e5;--band:#252523;}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
  font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;line-height:1.5}
.wrap{max-width:1080px;margin:0 auto;padding:30px 26px 70px}
h1{font-size:23px;margin:0 0 6px;font-weight:680}
h2{font-size:17px;margin:34px 0 12px;font-weight:660;display:flex;align-items:center;gap:9px}
h2 .n{background:var(--accent);color:#fff;width:23px;height:23px;border-radius:6px;font-size:13px;
  display:inline-flex;align-items:center;justify-content:center;flex:none}
.lead{color:var(--sub);font-size:13.5px;margin:0 0 3px}
.kpis{display:flex;gap:14px;flex-wrap:wrap;margin:18px 0 6px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:11px;padding:13px 17px;min-width:160px}
.kpi .l{font-size:11.5px;color:var(--mut)}
.kpi .v{font-size:22px;font-weight:700;margin-top:3px}
.kpi .v.pos{color:var(--pos)}.kpi .v.a{color:var(--a)}
.kpi .d{font-size:11px;color:var(--sub);margin-top:2px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin:12px 0}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th,td{padding:6px 9px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--mut);font-weight:600;font-size:11px}
td.l,th.l{text-align:left}
tr.chg td{background:var(--band)}
.mono{font-family:ui-monospace,"SF Mono",monospace;font-size:11.5px}
.pos{color:var(--pos)}.neg{color:var(--neg)}
.tag{font-size:10.5px;padding:1px 6px;border-radius:5px}
.tag.up{background:#1a9e5722;color:var(--pos)}.tag.dn{background:#d6454522;color:var(--neg)}
.bar{position:relative;height:15px;background:var(--band);border-radius:4px;overflow:hidden;min-width:120px}
.bar>span{position:absolute;left:0;top:0;height:100%;border-radius:4px}
.util-b{background:var(--b)}.util-a{background:var(--a)}
.dual{display:flex;flex-direction:column;gap:3px}
.dual .row{display:flex;align-items:center;gap:7px;font-size:11px}
.dual .row .k{width:26px;color:var(--mut)}
.flowline{display:flex;align-items:center;gap:8px;font-size:12.5px;padding:5px 0;border-bottom:1px solid var(--line)}
.arrow{color:var(--warn);font-weight:700}
.legend{display:flex;gap:16px;font-size:12px;color:var(--sub);margin:6px 0}
.legend .it{display:flex;align-items:center;gap:6px}.sw{width:13px;height:10px;border-radius:2px}
svg{display:block;width:100%;overflow:visible}.ax{font-size:9px;fill:var(--mut)}
.foot{color:var(--mut);font-size:11.5px;margin-top:30px;border-top:1px solid var(--line);padding-top:12px}
.note{background:var(--band);border-radius:8px;padding:10px 13px;font-size:12px;color:var(--sub);margin:8px 0;line-height:1.7}
.imp{padding:9px 0;border-bottom:1px solid var(--line);font-size:13px}
.imp:last-child{border-bottom:none}
.impbody{color:var(--sub);font-size:12.5px;margin-top:3px;line-height:1.6}
.badge{display:inline-block;padding:1px 8px;border-radius:5px;font-size:11px;font-weight:600;margin-right:6px}
.b-recv{background:#1a9e5722;color:var(--pos)}.b-don{background:#eb683422;color:var(--warn)}.b-none{background:var(--band);color:var(--mut)}
.mut{color:var(--mut)}
ul.ben{margin:4px 0 0;padding-left:18px}ul.ben li{margin:1px 0}
</style></head>
<body><div class="wrap" id="root"></div>
<script>
const D=__DATA__;
const W=(x)=> (x/1e4).toLocaleString('en',{maximumFractionDigits:1})+'w';
const RMB=(x)=> '¥'+Math.round(x).toLocaleString('en');
const RMBw=(x)=> (x/1e4).toLocaleString('en',{maximumFractionDigits:2})+'万';
const P=(x)=> (x*100).toFixed(0)+'%';
const root=document.getElementById('root');
function el(h){const t=document.createElement('template');t.innerHTML=h.trim();return t.content.firstChild;}

root.appendChild(el(`<div>
 <h1>模型级供需再平衡 · 效果报告</h1>
 <p class="lead">在原 time_period 策略之上，补一层<b>跨模型抢机器</b>：把「容量≫需求」的富余模型机器，挪给「需求&gt;容量、量堆在三方」的紧缺模型。
 口径：单机吞吐按<b>目标集群速率</b>；仅当<b>峰值可承接 + 整体收入净增</b>才挪（源集群同步更激进削峰）。${D.mode}。收益=元/天。</p>
</div>`));

/* KPI */
const kp=el(`<div class="kpis"></div>`);
[['原策略自建收入',RMBw(D.base)+'元/天','a','原 solver 腾挪+削峰后'],
 ['再平衡后自建收入',RMBw(D.final)+'元/天','a','跨模型抢机器后'],
 ['再平衡额外收益','+'+RMBw(D.extra)+'元/天','pos','≈ '+Math.round(D.extra*30/1e4)+'万元/月 · '+(D.extra*365/1e8).toFixed(2)+'亿元/年'],
 ['腾挪机器',D.n_moves+' 台','a','机器总量守恒(仅跨集群重分配)'],
].forEach(([l,v,c,d])=>kp.appendChild(el(`<div class="kpi"><div class="l">${l}</div><div class="v ${c}">${v}</div><div class="d">${d}</div></div>`)));
root.appendChild(kp);

/* ① 腾挪流向 */
root.appendChild(el(`<h2><span class="n">1</span>机器腾挪流向（源模型富余 → 目标模型紧缺）</h2>`));
const fc=el(`<div class="card"></div>`);
D.flows.forEach(f=>{
  fc.appendChild(el(`<div class="flowline">
   <span style="min-width:210px" class="l"><b>${f.src}</b> <span class="mono" style="color:var(--mut)">${f.src_model} ${W(f.src_rate)}/台</span></span>
   <span class="arrow">→ ${f.n}台 →</span>
   <span style="flex:1" class="l"><b>${f.tgt}</b> <span class="mono" style="color:var(--mut)">${f.tgt_model} ${W(f.tgt_rate)}/台</span></span>
   <span class="pos"><b>+${RMB(f.gain)}</b>/天</span>
  </div>`));
});
root.appendChild(fc);

/* ② 集群机器数 前→后 */
root.appendChild(el(`<h2><span class="n">2</span>各集群机器数：原策略 → 再平衡后</h2>`));
const ct=el(`<div class="card" style="overflow-x:auto"><table>
 <thead><tr><th class="l">集群</th><th class="l">模型</th><th>单台承载</th><th>机器数 前→后</th><th>自建容量 前→后</th></tr></thead>
 <tbody id="cb"></tbody></table></div>`);
root.appendChild(ct);
const cb=ct.querySelector('#cb');
D.clusters.forEach(c=>{
  const chg=Math.abs(c.mb-c.ma)>1e-6;
  const d=c.ma-c.mb;
  const tag=chg?`<span class="tag ${d>0?'up':'dn'}">${d>0?'+':''}${(+d.toFixed(2))}</span>`:'';
  cb.appendChild(el(`<tr class="${chg?'chg':''}">
   <td class="l">${c.name}</td><td class="l mono">${c.model}</td><td>${W(c.rate)}</td>
   <td>${(+c.mb.toFixed(2))} → ${(+c.ma.toFixed(2))} ${tag}</td>
   <td class="mono">${W(c.mb*c.rate)} → ${W(c.ma*c.rate)}</td>
  </tr>`));
});

/* ③ 逐集群腾挪影响 */
root.appendChild(el(`<h2><span class="n">3</span>逐集群腾挪影响（谁受益 / 谁能供出）</h2>`));
const ic=el(`<div class="card"></div>`);
D.cluster_impact.forEach(c=>{
  const d=c.ma-c.mb;
  if(c.role==='none'){
    const why = !c.participates ? '无三方额度，不参与切量再平衡' : (c.dedicated ? '专属集群，最小保留台数锁定，不参与共享池' : '容量与需求匹配，无需变动');
    ic.appendChild(el(`<div class="imp"><span class="badge b-none">不变</span><b>${c.name}</b> <span class="mono mut">${c.model} · ${(+c.mb.toFixed(2))}台 · ${W(c.rate)}/台</span><div class="impbody">${why}</div></div>`));
    return;
  }
  if(c.role==='receive'){
    let body;
    if(c.gainers && c.gainers.length){
      body = `<b>为承接 ${c.model} 客户抬高水位线</b>（少削峰、把三方的量切回自建）：<ul class="ben">`+
        c.gainers.map(g=>`<li>${g.cust} <span class="mono">${W(g.wm_b)}→${W(g.wm_a)}</span> <span class="pos">+${W(g.d)}</span></li>`).join('')+`</ul>`;
    } else {
      body = `<b>${c.model} 产能向本集群（${W(c.rate)}/台，较高速率）集中</b>，替换同模型低速率集群的产能（该模型总容量随之缩减，属内部再分布）。`;
    }
    ic.appendChild(el(`<div class="imp"><span class="badge b-recv">接收 +${(+d.toFixed(2))}台</span><b>${c.name}</b> <span class="mono mut">${c.model} · ${W(c.rate)}/台</span><div class="impbody">${body}</div></div>`));
  } else {
    const why = c.dedicated
      ? `<b>专属集群、当前无主客户闲置</b>：挪走超出最小保留(2台)的机器，机会成本≈0（把搁置的专属机变现给紧缺模型）。`
      : `<b>共享池占用率仅 ${c.occ_b!=null?P(c.occ_b):'—'}、容量过剩</b>：挪走机器后本模型客户仍可承接`+
        (c.losers && c.losers.length?`（个别小幅削峰，如 ${c.losers[0].cust} <span class="mono">${W(c.losers[0].wm_b)}→${W(c.losers[0].wm_a)}</span>）`:'')+`。`;
    ic.appendChild(el(`<div class="imp"><span class="badge b-don">供出 ${(+d.toFixed(2))}台</span><b>${c.name}</b> <span class="mono mut">${c.model} · ${W(c.rate)}/台</span><div class="impbody">${why}</div></div>`));
  }
});
root.appendChild(ic);

/* ④ 模型级利用率 前/后 */
root.appendChild(el(`<h2><span class="n">4</span>模型级利用率 & 自建承接量：再平衡前 / 后</h2>`));
root.appendChild(el(`<div class="legend">
 <span class="it"><span class="sw util-b"></span>再平衡前</span>
 <span class="it"><span class="sw util-a"></span>再平衡后</span>
 <span style="color:var(--mut)">利用率 = 峰值自建负载 / 自建容量</span></div>`));
const mt=el(`<div class="card" style="overflow-x:auto"><table>
 <thead><tr><th class="l">模型</th><th>客户峰值需求</th><th>自建容量 前→后</th>
   <th>峰值自建承接 前→后</th><th style="min-width:150px">利用率 前/后<div style="font-weight:400;color:var(--mut)">峰值负载/总容量</div></th>
   <th>共享池占用率 前→后<div style="font-weight:400;color:var(--mut)">Σ水位线/共享容量</div></th></tr></thead>
 <tbody id="mb"></tbody></table></div>`);
root.appendChild(mt);
const mb=mt.querySelector('#mb');
D.model_rows.forEach(m=>{
  if(!m.participates){
    mb.appendChild(el(`<tr style="opacity:.6">
     <td class="l mono">${m.model}</td>
     <td class="mono">${W(m.peak)}</td>
     <td class="mono">${W(m.cap_b)} → ${W(m.cap_a)}</td>
     <td class="l" colspan="3" style="color:var(--mut)">无三方额度，不参与切量再平衡（机器数不变）</td>
    </tr>`));
    return;
  }
  const up=m.util_a>=m.util_b;
  const dl=(m.load_a-m.load_b);
  const occB=m.occ_b!=null?P(m.occ_b):'—', occA=m.occ_a!=null?P(m.occ_a):'—';
  const occFull=(m.occ_a!=null&&m.occ_a>=0.999);
  mb.appendChild(el(`<tr>
   <td class="l mono">${m.model}</td>
   <td class="mono">${W(m.peak)}</td>
   <td class="mono">${W(m.cap_b)} → ${W(m.cap_a)}</td>
   <td class="mono">${W(m.load_b)} → ${W(m.load_a)} <span class="${dl>=0?'pos':'neg'}" style="font-size:10px">${dl>=0?'+':''}${W(dl)}</span></td>
   <td><div class="dual">
     <div class="row"><span class="k">前</span><span class="bar"><span class="util-b" style="width:${Math.min(m.util_b*100,100)}%"></span></span><span>${P(m.util_b)}</span></div>
     <div class="row"><span class="k">后</span><span class="bar"><span class="util-a" style="width:${Math.min(m.util_a*100,100)}%"></span></span><span>${P(m.util_a)}</span></div>
   </div></td>
   <td class="mono">${occB} → <b class="${occFull?'pos':''}">${occA}</b>
     <div style="font-size:10px;color:var(--mut)">${W(m.swm_a)}/${W(m.shared_a)}</div></td>
  </tr>`));
});
root.appendChild(el(`<div class="note">两个「利用率」口径的区别很关键：<br>
 · <b>利用率(峰值负载/总容量)</b>：偏保守——既吃了「各客户波峰不同时发生」的亏，又把<b>专属集群闲置产能</b>算进分母（如 glm-5.1 的 KSCC/XISHANJU 2000w 无主客户、普通客户够不到）。<br>
 · <b>共享池占用率(Σ水位线/共享容量)</b>：真实反映自建被承诺了多少。<b>=100% 即共享池已吃满、还在削峰</b>（想接更多得加容量）；&lt;100% 才是真有余量。<br>
 关键读法：<b>glm-5.2</b> 再平衡前共享池占用仅 53%（容量过剩、真浪费）→ 机器抽走后升到 100%；<b>kimi-k2.5</b> 始终 100%（紧缺，扩容后自建承接 3500w→6000w，把三方的量切回来）；
 <b>kimi-k2.6</b> 前 100% 且在削峰 → 加 1 台后降到 87%、不再削峰（见下方说明）。</div>`));

root.appendChild(el(`<div class="card" style="border-left:3px solid var(--warn)">
 <b>为什么给 kimi-k2.6 加机器？（容量看着够，其实在削峰）</b>
 <div class="note" style="margin:6px 0 0">
 它的<b>峰值需求 922w</b> 是「各客户波峰叠加后的峰」，确实 &lt; 原容量 1200w。但水位线是<b>每客户一条平的上限</b>，要不削峰就得让预算盖住<b>各客户峰值之和 = 1310w</b>（客户波峰并不同时发生）。1200w &lt; 1310w，所以原本 BODHIMIND(756→750w)、珠海办公(516→435w) 等都被削峰、量外溢三方。<br>
 那台机器来自 <b>GLM-5.1-KSCC 闲置的第 3 台专属机（无主客户，机会成本≈0）</b>，挪到 kimi-k2.6 后容量 1200w→1500w、Σ水位线达到 1310w → 所有客户拿到全峰、不再削峰，净增 <b>+683 元/天</b>。等于把一台搁置的专属机变现。</div>
</div>`));

/* 累计收益曲线 */
root.appendChild(el(`<h2><span class="n">5</span>逐台腾挪的累计自建收入（边际递减，正收益即止）</h2>`));
(function(){
  const SW=1000,SH=200,ML=70,MR=16,MT=14,MB=28,pw=SW-ML-MR,ph=SH-MT-MB;
  const c=D.curve; if(!c.length){return;}
  const xs=[D.base,...c.map(p=>p.cum)];
  const y0=Math.min(...xs), y1=Math.max(...xs);
  const pad=(y1-y0)*0.08||1;
  const X=i=>ML+(i/(c.length))*pw, Y=v=>MT+ph-((v-(y0-pad))/((y1+pad)-(y0-pad)))*ph;
  const pts=[{i:0,cum:D.base},...c.map((p,i)=>({i:i+1,cum:p.cum}))];
  const path=pts.map((p,i)=>`${i?'L':'M'}${X(p.i)},${Y(p.cum)}`).join('');
  const yt=[y0,(y0+y1)/2,y1];
  const svg=el(`<div class="card"><svg viewBox="0 0 ${SW} ${SH}">
   ${yt.map(v=>`<line x1="${ML}" y1="${Y(v)}" x2="${SW-MR}" y2="${Y(v)}" stroke="var(--line)"/>
     <text class="ax" x="${ML-6}" y="${Y(v)+3}" text-anchor="end">${RMBw(v)}</text>`).join('')}
   <path d="${path}" fill="none" stroke="var(--a)" stroke-width="2"/>
   ${pts.filter((p,i)=>i%2===0||i===pts.length-1).map(p=>`<circle cx="${X(p.i)}" cy="${Y(p.cum)}" r="2.2" fill="var(--a)"/>`).join('')}
   <text class="ax" x="${ML}" y="${SH-8}" text-anchor="start">起点(原策略)</text>
   <text class="ax" x="${X(c.length)}" y="${SH-8}" text-anchor="end">第${c.length}台</text>
   </svg>
   <div class="note" style="margin:8px 0 0">纵轴=全模型自建总收入(元/天)。每加一台机器的边际收益递减，直到无正收益挪动（末步 +${RMB(c[c.length-1].gain)}/天）为止；全程每步都满足峰值可承接。</div>
  </div>`);
  root.appendChild(svg);
})();

/* ⑤ 峰值可行性 */
root.appendChild(el(`<h2><span class="n">6</span>再平衡后逐模型峰值可行性（硬约束：自建+三方 ≥ 客户峰值）</h2>`));
const pf=D.feasibility;
let rows=Object.keys(pf).sort().map(m=>{const f=pf[m];
  return `<tr><td class="l mono">${m}</td><td class="mono">${W(f.peak_demand)}</td><td class="mono">${W(f.self_cap)}</td>
   <td class="mono">${W(f.vendor_cap)}</td><td class="mono">${W(f.total_cap)}</td>
   <td class="mono ${f.slack>=0?'pos':'neg'}">${W(f.slack)}</td>
   <td><span class="tag ${f.feasible?'up':'dn'}">${f.feasible?'OK':'掉量'}</span></td></tr>`;}).join('');
root.appendChild(el(`<div class="card" style="overflow-x:auto"><table>
 <thead><tr><th class="l">模型</th><th>客户峰值</th><th>自建(后)</th><th>三方额度</th><th>总承接</th><th>余量</th><th>判定</th></tr></thead>
 <tbody>${rows}</tbody></table></div>`));

root.appendChild(el(`<div class="foot">
 实验版 · <span class="mono">run_time_period_rebalance.py</span>（target-rate）→ <span class="mono">gen_rebalance_html.py</span>。
 单机吞吐按目标集群速率；机器总量守恒；每步腾挪均满足峰值可承接且整体收入净增；源集群机器减少后水位线自动更激进削峰（损失已计入净收益）。收益=元/天，按 2026-07-07 当日波形折算。
</div>`));
</script></body></html>"""

out = os.path.join(BASE, "再平衡效果报告.html")
open(out, "w", encoding="utf-8").write(HTML.replace("__DATA__", DATA))
print("[written]", os.path.basename(out))
print(f"  额外收益 = {R['extra_gain_yuan']:,.0f} 元/天  腾挪 {len(R['moves'])} 台  流向 {len(flows)} 类")
