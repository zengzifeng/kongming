from __future__ import annotations

from ..algorithms._shared import SolverEconomicsMixin
from ..algorithms.base import DemandSnapshotItem
from ..extensions import db
from ..models import MonitorConsumer, Policy, PolicyRun
from ..utils.errors import NotFound

# 收入/收益为「TPM·整点」积分口径；× 60min ÷ 1e6(列表价元/百万token) = 元/天，
# 同一因子把 TPM 积分体量换成「百万token/天」。故 收益(元/天)=单TPM收入(元/百万token)×体量(百万token/天)。
Y = 60 / 1e6


class _Econ(SolverEconomicsMixin):
    """复用求解器经济学（_unit_self_revenue），避免单TPM收入公式在报告层漂移。"""


def _is_dedicated(cluster_name: str) -> bool:
    u = str(cluster_name or "").upper()
    return "KSCC" in u or "XISHANJU" in u


class PolicyReportService:
    """把已持久化的 time_period 策略（Policy.summary_json + PolicyRun.input_snapshot_json）
    汇成结构化报告 payload（纯数值，前端渲染）。不重跑 solver。

    单位：收益一律 元/天；体量 百万token/天；单TPM收入 元/百万token；TPM 量仍用 TPM。
    """

    def build(self, policy_id: int) -> dict:
        policy = db.session.get(Policy, policy_id)
        if not policy:
            raise NotFound("策略不存在", details={"id": policy_id})
        run = db.session.get(PolicyRun, policy.policy_run_id) if policy.policy_run_id else None
        snap = (run.input_snapshot_json or {}) if run else {}
        summary = policy.summary_json or {}

        demands = snap.get("demands", [])
        params = snap.get("params", {}) or {}
        vendors = snap.get("vendors", []) or []
        model_prices = params.get("model_prices", {}) or {}
        name_by_code = {c.customer_code: c.customer_name
                        for c in db.session.execute(db.select(MonitorConsumer)).scalars()}
        dem_by_key = {(d["customer_code"], d["model_name"]): d for d in demands}
        econ = _Econ()

        attributions = self._attributions(summary, dem_by_key, model_prices, vendors,
                                           name_by_code, econ)
        return {
            "policy_id": policy_id,
            "algorithm": policy.algorithm,
            "kpis": self._kpis(summary),
            "unit_example": self._unit_example(attributions, dem_by_key, model_prices,
                                               vendors, name_by_code, econ),
            "attributions": attributions,
            "cluster_utilization": self._cluster_utilization(snap, summary, demands),
            "peak_feasibility": summary.get("peak_feasibility", {}),
            "model_rebalance": self._rebalance(summary, name_by_code),
        }

    # ---------------- KPI ----------------
    @staticmethod
    def _kpis(summary: dict) -> dict:
        rb = float(summary.get("self_revenue_before", 0.0))
        ra = float(summary.get("self_revenue_after", 0.0))
        g = float(summary.get("expected_revenue_gain", 0.0))
        return {
            "self_revenue_before_yuan_day": rb * Y,
            "self_revenue_after_yuan_day": ra * Y,
            "expected_revenue_gain_yuan_day": g * Y,
            "expected_revenue_gain_yuan_month": g * Y * 30,
            "expected_revenue_gain_yuan_year": g * Y * 365,
        }

    # ---------------- 逐调整收益（元/天）----------------
    def _attributions(self, summary, dem_by_key, model_prices, vendors, name_by_code, econ):
        rows = []
        for wmc in summary.get("watermark_changes", []):
            d = dem_by_key.get((wmc["customer_code"], wmc["model"]))
            if not d:
                continue
            ser = [float(t) for _, t in (d.get("tpm_series") or [])]
            wm = float(wmc["watermark_self_tpm"])
            s0 = float(wmc.get("current_self_ratio", 0.0))
            sum_after = sum(min(t, wm) for t in ser)
            sum_before = sum(t * s0 for t in ser)
            delta = sum_after - sum_before
            gain = float(wmc.get("customer_revenue_gain", 0.0))
            rows.append({
                "customer_code": wmc["customer_code"],
                "customer": name_by_code.get(wmc["customer_code"], wmc["customer_code"]),
                "model": wmc["model"],
                "unit_self_revenue": self._unit_of(d, model_prices, vendors, econ),  # 元/百万token
                "current_self_ratio": s0,
                "watermark_self_tpm": wm,
                "sum_before_mtok_day": sum_before * Y,
                "sum_after_mtok_day": sum_after * Y,
                "delta_mtok_day": delta * Y,
                "gain_yuan_day": gain * Y,
                "fallback_vendor": wmc.get("fallback_vendor"),
                "peak_tpm": max(ser) if ser else 0.0,
                "series": [{"ts": ts, "tpm": float(t)} for ts, t in (d.get("tpm_series") or [])],
            })
        rows.sort(key=lambda a: -a["gain_yuan_day"])
        return rows

    @staticmethod
    def _unit_of(d, model_prices, vendors, econ) -> float:
        item = DemandSnapshotItem(
            report_id=d.get("report_id", ""), customer_code=d["customer_code"],
            model_name=d["model_name"], expected_tpm=float(d.get("expected_tpm", 0.0)),
            expected_rpm=0.0, discount_rate=float(d.get("discount_rate", 1.0)),
            input_ratio=float(d.get("input_ratio", 1.0)),
            cache_hit_rate=float(d.get("cache_hit_rate", 0.0)),
        )
        return econ._unit_self_revenue(item, model_prices, vendors)

    # ---------------- 单TPM收入 计算示例（头号收益客户，公式代入）----------------
    def _unit_example(self, attributions, dem_by_key, model_prices, vendors, name_by_code, econ):
        if not attributions:
            return None
        top = attributions[0]
        d = dem_by_key.get((top["customer_code"], top["model"]))
        if not d:
            return None
        model = d["model_name"]
        price = model_prices.get(model, {})
        fallback = next((float(v.get("unit_price", 0) or 0) for v in vendors
                         if v.get("model") == model and v.get("unit_price")), 0.0014)
        hit = float(price.get("input_cache_hit_price", fallback * 0.2) or 0)
        miss = float(price.get("input_cache_miss_price", fallback) or 0)
        out = float(price.get("output_price", fallback) or 0)
        io = float(d.get("input_ratio", 1.0))
        io = io if io > 0 else 1.0
        denom = io + 1.0
        input_share, output_share = io / denom, 1.0 / denom
        chr_ = min(max(float(d.get("cache_hit_rate", 0.0)), 0.0), 1.0)
        term_hit = input_share * chr_ * hit
        term_miss = input_share * (1 - chr_) * miss
        term_out = output_share * out
        weighted = term_hit + term_miss + term_out
        disc = max(float(d.get("discount_rate", 1.0)), 0.0)
        return {
            "customer": name_by_code.get(d["customer_code"], d["customer_code"]),
            "model": model, "input_ratio": io, "input_share": input_share,
            "output_share": output_share, "cache_hit_rate": chr_,
            "input_hit_price": hit, "input_miss_price": miss, "output_price": out,
            "term_hit": term_hit, "term_miss": term_miss, "term_out": term_out,
            "weighted_list_price": weighted, "discount_rate": disc,
            "unit_self_revenue": weighted * disc,  # 元/百万token
        }

    # ---------------- 集群利用率 切量前/后 + 共享池占用率 ----------------
    def _cluster_utilization(self, snap, summary, demands):
        clusters = snap.get("resources", {}).get("clusters", []) or []
        mb = summary.get("machines_before", {}) or {}
        ma = summary.get("machines_after", {}) or {}
        rate_by = {c["cluster_name"]: float(c.get("tpm_per_machine", 0) or 0) for c in clusters}
        model_by = {c["cluster_name"]: c.get("deployed_model") for c in clusters}

        wm_by = {(w["customer_code"], w["model"]): float(w["watermark_self_tpm"])
                 for w in summary.get("watermark_changes", [])}
        ratio_by = {(w["customer_code"], w["model"]): float(w.get("current_self_ratio", 0.0))
                    for w in summary.get("watermark_changes", [])}

        before_ts: dict[str, list[float]] = {}
        after_ts: dict[str, list[float]] = {}
        for d in demands:
            model = d["model_name"]
            key = (d["customer_code"], model)
            s0 = ratio_by.get(key, float(d.get("current_self_ratio") or 0.0))
            wm = wm_by.get(key)
            ser = [float(t) for _, t in (d.get("tpm_series") or [])]
            bl = before_ts.setdefault(model, [])
            al = after_ts.setdefault(model, [])
            for i, t in enumerate(ser):
                if i >= len(bl):
                    bl.append(0.0)
                    al.append(0.0)
                bl[i] += t * s0
                al[i] += (min(t, wm) if wm is not None else t * s0)
        peak_before = {m: (max(v) if v else 0.0) for m, v in before_ts.items()}
        peak_after = {m: (max(v) if v else 0.0) for m, v in after_ts.items()}

        cap_before: dict[str, float] = {}
        cap_after: dict[str, float] = {}
        shared_after: dict[str, float] = {}
        for c in clusters:
            nm = c["cluster_name"]
            m = model_by[nm]
            rate = rate_by[nm]
            cap_before[m] = cap_before.get(m, 0.0) + int(mb.get(nm, c.get("machine_count", 0)) or 0) * rate
            capa = int(ma.get(nm, c.get("machine_count", 0)) or 0) * rate
            cap_after[m] = cap_after.get(m, 0.0) + capa
            if not _is_dedicated(nm):
                shared_after[m] = shared_after.get(m, 0.0) + capa
        swm: dict[str, float] = {}
        for w in summary.get("watermark_changes", []):
            swm[w["model"]] = swm.get(w["model"], 0.0) + float(w["watermark_self_tpm"])

        models = sorted(set(list(peak_before) + list(peak_after) + list(cap_after)))
        rows = []
        for m in models:
            cb, ca, sh = cap_before.get(m, 0.0), cap_after.get(m, 0.0), shared_after.get(m, 0.0)
            rows.append({
                "model": m,
                "capacity_before": cb, "capacity_after": ca,
                "peak_self_before": peak_before.get(m, 0.0),
                "peak_self_after": peak_after.get(m, 0.0),
                "util_before": (peak_before.get(m, 0.0) / cb if cb else 0.0),
                "util_after": (peak_after.get(m, 0.0) / ca if ca else 0.0),
                "shared_capacity": sh,
                "sum_watermark": swm.get(m, 0.0),
                "shared_occupancy": (swm.get(m, 0.0) / sh if sh else 0.0),
            })
        return rows

    # ---------------- 模型级再平衡（元/天 折算 + 客户名）----------------
    def _rebalance(self, summary, name_by_code):
        rb = summary.get("model_rebalance") or {}
        if not rb:
            return None

        def named(lst):
            out = []
            for x in (lst or []):
                y = dict(x)
                y["customer"] = name_by_code.get(x.get("customer_code"), x.get("customer_code"))
                out.append(y)
            return out

        per_cluster = []
        for c in rb.get("per_cluster", []):
            cc = dict(c)
            cc["gainers"] = named(c.get("gainers"))
            cc["losers"] = named(c.get("losers"))
            per_cluster.append(cc)
        # 流向聚合（源→目标 台数 + 收益元/天）
        flows: dict[tuple, dict] = {}
        for mv in rb.get("moves", []):
            k = (mv["from_cluster"], mv["to_cluster"])
            f = flows.setdefault(k, {"from_cluster": mv["from_cluster"], "to_cluster": mv["to_cluster"],
                                     "from_model": mv.get("model"), "n": 0, "gain_yuan_day": 0.0,
                                     "from_rate": mv.get("from_tpm_per_machine"),
                                     "to_rate": mv.get("to_tpm_per_machine")})
            f["n"] += int(mv.get("machine_count", 1))
            f["gain_yuan_day"] += float(mv.get("gain", 0.0)) * Y
        return {
            "extra_gain_yuan_day": float(rb.get("extra_revenue_gain", 0.0)) * Y,
            "self_revenue_before_yuan_day": float(rb.get("self_revenue_before", 0.0)) * Y,
            "self_revenue_after_yuan_day": float(rb.get("self_revenue_after", 0.0)) * Y,
            "moves": [dict(mv, gain_yuan_day=float(mv.get("gain", 0.0)) * Y) for mv in rb.get("moves", [])],
            "flows": sorted(flows.values(), key=lambda f: -f["gain_yuan_day"]),
            "per_model": rb.get("per_model", []),
            "per_cluster": per_cluster,
        }
