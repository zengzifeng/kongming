# -*- coding: utf-8 -*-
"""生成时段算法「固定水位线」示意图 HTML（24h 面积图小倍数）。读 _ts_chart_data.json。"""
import json
from pathlib import Path

ROOT = Path(__file__).parent
data = json.loads((ROOT / "_ts_chart_data.json").read_text(encoding="utf-8"))
res = json.loads((ROOT / "_time_period_result.json").read_text(encoding="utf-8"))
s = res["summary"]
gain = s["expected_revenue_gain"]
rb, ra = s["self_revenue_before"], s["self_revenue_after"]

DATA_JS = json.dumps(data, ensure_ascii=False)

html = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>时段调整：固定水位线 × 客户跑量</title>
<style>
  .viz-root{--surface-1:#fcfcfb;--surface-2:#f3f2ef;--text-primary:#0b0b0b;--text-secondary:#52514e;
    --text-muted:#8a8981;--grid:#e6e5e1;--self:#2a78d6;--vendor:#eb6834;--self-fill:#2a78d633;--vendor-fill:#eb683433;--wm:#0b0b0b;}
  @media (prefers-color-scheme:dark){.viz-root{--surface-1:#1a1a19;--surface-2:#242422;--text-primary:#fff;
    --text-secondary:#c3c2b7;--text-muted:#8f8e84;--grid:#333330;--self:#3987e5;--vendor:#d95926;
    --self-fill:#3987e540;--vendor-fill:#d9592640;--wm:#fff;}}
  *{box-sizing:border-box}body{margin:0;background:var(--surface-1)}
  .viz-root{background:var(--surface-1);color:var(--text-primary);font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;padding:26px 30px 40px;max-width:1120px;margin:0 auto}
  h1{font-size:20px;margin:0 0 4px;font-weight:650}
  .sub{color:var(--text-secondary);font-size:13px;margin:0 0 3px}
  .kpi{color:var(--text-secondary);font-size:13px;margin:2px 0 16px}
  .kpi b{color:var(--self);font-weight:650}
  .legend{display:flex;gap:20px;align-items:center;margin:10px 0 20px;font-size:13px;flex-wrap:wrap}
  .legend .item{display:flex;align-items:center;gap:7px;color:var(--text-secondary)}
  .sw{width:14px;height:11px;border-radius:2px}
  .swl{width:16px;height:0;border-top:2px dashed var(--wm)}
  .grid{display:grid;grid-template-columns:repeat(2,1fr);gap:22px 30px}
  @media(max-width:760px){.grid{grid-template-columns:1fr}}
  .cell .hd{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:2px}
  .nm{font-size:14px;font-weight:600}.md{font-size:11px;color:var(--text-muted);font-family:ui-monospace,monospace}
  .wmv{font-size:11px;color:var(--text-secondary)}
  svg{display:block;width:100%;overflow:visible}
  .ax{font-size:9.5px;fill:var(--text-muted)}
  .note{grid-column:1/-1;font-size:12.5px;color:var(--text-secondary);background:var(--surface-2);border-radius:8px;padding:11px 15px;line-height:1.6}
  .note b{color:var(--text-primary)}
  .tt{position:fixed;pointer-events:none;background:var(--surface-2);color:var(--text-primary);border:1px solid var(--grid);
    border-radius:8px;padding:7px 10px;font-size:12px;box-shadow:0 4px 14px rgba(0,0,0,.16);opacity:0;transition:opacity .08s;z-index:9;line-height:1.5}
</style></head>
<body><div class="viz-root">
  <h1>时段调整：固定水位线 × 客户跑量（分时自建/三方分发）</h1>
  <p class="sub">机器一次调整后，每个客户的<b>自建水位线（TPM 上限）固定不变</b>；虚线即水位线。客户跑量（需求）随时段起伏，<b>低于水位线的部分走自建（蓝），高出的部分溢出到三方（橙）</b>——所以分发占比随时间变化，水位线本身不变。</p>
  <p class="kpi">整段自建收入（分时积分，相对值）__RB__ → __RA__，本次调整收益 <b>+__GAIN__</b> · 面积图单位：万 TPM/分钟 · 24 小时</p>
  <div class="legend">
    <span class="item"><span class="sw" style="background:var(--self)"></span>自建承接</span>
    <span class="item"><span class="sw" style="background:var(--vendor)"></span>三方溢出</span>
    <span class="item"><span class="swl"></span>固定水位线</span>
    <span class="item" style="color:var(--text-muted)">— 需求曲线</span>
  </div>
  <div class="grid" id="g"></div>
</div><div class="tt" id="tt"></div>
<script>
const DATA=__DATA__;
const tt=document.getElementById('tt');
const W=300,H=132,ML=34,MR=8,MT=10,MB=18,pw=W-ML-MR,ph=H-MT-MB;
const g=document.getElementById('g');
DATA.forEach(d=>{
  const maxY=Math.max(d.wm,...d.pts.map(p=>p.d))*1.08;
  const X=h=>ML+(h/23)*pw, Y=v=>MT+ph-(v/maxY)*ph;
  const selfArea=d.pts.map(p=>`${X(p.h)},${Y(p.s)}`).join(' ');
  const selfBase=d.pts.slice().reverse().map(p=>`${X(p.h)},${Y(0)}`).join(' ');
  const demTop=d.pts.map(p=>`${X(p.h)},${Y(p.d)}`).join(' ');
  const selfTop=d.pts.slice().reverse().map(p=>`${X(p.h)},${Y(p.s)}`).join(' ');
  const demLine=d.pts.map((p,i)=>`${i?'L':'M'}${X(p.h)},${Y(p.d)}`).join('');
  const yTicks=[0,Math.round(maxY/2),Math.round(maxY)];
  const el=document.createElement('div');el.className='cell';
  el.innerHTML=`<div class="hd"><span><span class="nm">${d.c}</span> <span class="md">${d.m}</span></span>
    <span class="wmv">水位线 ${d.wm}w · 现自建 ${d.self0}%</span></div>
   <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${d.c} 分时自建/三方">
    ${yTicks.map(t=>`<line x1="${ML}" y1="${Y(t)}" x2="${W-MR}" y2="${Y(t)}" stroke="var(--grid)" stroke-width="1"/>
       <text class="ax" x="${ML-4}" y="${Y(t)+3}" text-anchor="end">${t}</text>`).join('')}
    <polygon points="${selfArea} ${selfBase}" fill="var(--self-fill)"/>
    <polygon points="${demTop} ${selfTop}" fill="var(--vendor-fill)"/>
    <path d="${demLine}" fill="none" stroke="var(--text-muted)" stroke-width="1.5"/>
    <polyline points="${d.pts.map(p=>`${X(p.h)},${Y(p.s)}`).join(' ')}" fill="none" stroke="var(--self)" stroke-width="2"/>
    <line x1="${ML}" y1="${Y(d.wm)}" x2="${W-MR}" y2="${Y(d.wm)}" stroke="var(--wm)" stroke-width="1.5" stroke-dasharray="5 3"/>
    ${[0,6,12,18,23].map(h=>`<text class="ax" x="${X(h)}" y="${H-5}" text-anchor="middle">${h}${h===23?'h':''}</text>`).join('')}
    ${d.pts.map(p=>`<rect x="${X(p.h)-pw/46}" y="${MT}" width="${pw/23}" height="${ph}" fill="transparent"
       data-h="${p.h}" data-d="${p.d}" data-s="${p.s}" data-v="${p.v}"/>`).join('')}
   </svg>`;
  el.querySelectorAll('rect').forEach(r=>{
    r.addEventListener('mousemove',e=>{const s=+r.dataset.s,v=+r.dataset.d>0?(+r.dataset.v/+r.dataset.d*100):0;
      tt.innerHTML=`<b>${d.c} · ${r.dataset.h}:00</b><br>需求 ${r.dataset.d}w<br>
        <span style="color:var(--self)">自建 ${r.dataset.s}w</span>（${(s/+r.dataset.d*100||0).toFixed(0)}%）<br>
        <span style="color:var(--vendor)">三方 ${r.dataset.v}w</span>（${v.toFixed(0)}%）`;
      tt.style.opacity=1;tt.style.left=Math.min(e.clientX+14,innerWidth-180)+'px';tt.style.top=(e.clientY+14)+'px';});
    r.addEventListener('mouseleave',()=>tt.style.opacity=0);
  });
  g.appendChild(el);
});
const note=document.createElement('div');note.className='note';
note.innerHTML=`<b>怎么读：</b>虚线是本次机器调整<b>一次性设定、之后不变</b>的自建水位线。灰线是客户 24h 需求曲线。
  需求在水位线以下时全部自建（蓝色实线贴合需求）；需求涨过水位线后，自建被"削平"在水位线上、超出部分转橙色三方。
  <b>阶跃</b>最典型：水位线 1000w 固定，低谷需求 700w＜线→100%自建；峰值需求 2000w＞线→自建仍是 1000w、占比降到 50%。
  未列出：西山居 GLM-5.1（已满自建）、科大讯飞 GLM-5.1（无容量，全走三方）。`;
g.appendChild(note);
addEventListener('scroll',()=>tt.style.opacity=0,true);
</script></body></html>"""

html = (html.replace("__DATA__", DATA_JS)
            .replace("__RB__", f"{rb:,.0f}").replace("__RA__", f"{ra:,.0f}")
            .replace("__GAIN__", f"{gain:,.0f}"))
out = ROOT / "客户跑量调整示意图.html"
out.write_text(html, encoding="utf-8")
print("written:", out.name, "| customers:", len(data))
