from __future__ import annotations

from .base import DemandSnapshotItem


class SolverEconomicsMixin:
    """realtime 与 time_period 共用的经济学与集群物理规则（纯函数，无状态）。

    抽出来是为了两个 solver 共享同一套口径，避免复制粘贴后逻辑漂移。
    """

    # ---- 单位自建收入（密度）：售卖折扣 × (命中/未命中/输出 三档列表价按 io 比与缓存命中率加权) ----
    def _unit_self_revenue(self, demand: DemandSnapshotItem, model_prices: dict, vendors: list[dict]) -> float:
        price = model_prices.get(demand.model_name, {})
        fallback_unit_price = next(
            (float(v.get("unit_price", 0) or 0) for v in vendors if v.get("model") == demand.model_name and v.get("unit_price")),
            0.0014,
        )
        input_hit_price = float(price.get("input_cache_hit_price", fallback_unit_price * 0.2) or 0)
        input_miss_price = float(price.get("input_cache_miss_price", fallback_unit_price) or 0)
        output_price = float(price.get("output_price", fallback_unit_price) or 0)
        input_ratio = max(demand.input_ratio, 0)
        output_ratio = max(demand.output_ratio, 0)
        total_ratio = input_ratio + output_ratio
        if total_ratio <= 0:
            input_ratio = output_ratio = 0.5
            total_ratio = 1.0
        input_share = input_ratio / total_ratio
        output_share = output_ratio / total_ratio
        cache_hit_rate = min(max(demand.cache_hit_rate, 0), 1)
        unit_price = (
            input_share * cache_hit_rate * input_hit_price
            + input_share * (1 - cache_hit_rate) * input_miss_price
            + output_share * output_price
        )
        return unit_price * max(demand.discount_rate, 0)

    def _best_vendor(self, demand: DemandSnapshotItem, vendors: list[dict]) -> dict | None:
        matching = [
            v for v in vendors
            if v.get("model") == demand.model_name and float(v.get("quota_tpm", 0) or 0) > 0
        ]
        if not matching:
            return None
        return min(matching, key=lambda v: float(v.get("unit_cost", 0) or 0))

    def _purchase_discount(self, vendor: dict) -> float:
        unit_cost = float(vendor.get("unit_cost", 0) or 0)
        unit_price = float(vendor.get("unit_price", 0) or 0)
        if unit_price <= 0:
            return 1.0
        return unit_cost / unit_price

    def _vendor_key(self, vendor: dict) -> str:
        return f"{vendor.get('vendor', 'unknown')}::{vendor.get('model', '')}"

    # ---- 集群物理规则：专属集群、最小保留台数、可供出机器 ----
    def _matching_clusters(self, model_name: str, clusters: list[dict], customer_code: str | None = None) -> list[dict]:
        out = []
        for c in clusters:
            if c.get("deployed_model") != model_name:
                continue
            # 专属集群（KSCC/XISHANJU 命名）只能承接其对应客户的业务，不参与同模型共享池
            if self._is_dedicated(c) and customer_code is not None and c.get("primary_customer") != customer_code:
                continue
            out.append(c)
        return out

    @staticmethod
    def _is_dedicated(cluster: dict) -> bool:
        name = str(cluster.get("cluster_name", "")).upper()
        return "KSCC" in name or "XISHANJU" in name

    @staticmethod
    def _min_reserve_machines(cluster: dict) -> int:
        # KSCC 集群常态最少保留 2 台机器
        return 2 if "KSCC" in str(cluster.get("cluster_name", "")).upper() else 0

    def _donatable_machines(self, cluster: dict) -> int:
        # 可供出机器 = 空闲机器，且不能突破该集群的常态最小保留台数
        idle = int(cluster.get("current_redundant_machines", cluster.get("busy_redundant_machines", 0)) or 0)
        total = int(cluster.get("machine_count", 0) or 0)
        return max(0, min(idle, total - self._min_reserve_machines(cluster)))

    def _reject(self, demand: DemandSnapshotItem, reason: str) -> dict:
        return {
            "report_id": demand.report_id,
            "customer_code": demand.customer_code,
            "model": demand.model_name,
            "reason": reason,
        }
