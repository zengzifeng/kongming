"""从实跑量 + 平台定价主数据实时构建求解器需求（DemandSnapshotItem 列表）。

替代「从 demands 表读已审批报备单」的旧输入源：realtime / time_period 两个算法的默认
需求来自本表构建的结果。demands 表仅保留给「前端手动指定新增某客户需求评估」路径。

需求 universe = customer_usage_hourly 中全部 (客户, 模型) 组合；售卖折扣左连
customer_sell_discounts（未签约用 default_discount）。各字段口径见 build 函数内注释，
与计划文档一致。
"""
from __future__ import annotations

from collections import defaultdict

from ..extensions import db
from ..models import Customer, CustomerSellDiscount, CustomerUsageHourly
from .base import DemandSnapshotItem

SELF_SOURCE = "自建"
VENDOR_SOURCE = "第三方"


def build_usage_demand_items(
    default_discount: float = 1.0,
    default_input_ratio: float = 1.0,
    default_cache_hit_rate: float = 0.0,
) -> list[DemandSnapshotItem]:
    """把实跑量按 (客户, 模型) 聚合成 DemandSnapshotItem 列表。

    - expected_tpm：该组合**最新一个小时**的 TPM（当前负载）= Σio(最新小时)/60
    - tpm_series ：按 data_time 升序的 [(iso, Σio/60)]，同一整点跨结算日的多条求和
    - input_ratio：Σtotal_input / Σoutput_token（分母 0 退化 default_input_ratio）
    - cache_hit_rate：Σcache_token / (Σcache_token + Σcache_miss_token)
    - current_self_ratio：Σio[自建] / Σio
    - current_vendor_ratios：{provider: Σio / Σio_total}（仅第三方行）
    - discount_rate：customer_sell_discounts.sell_discount，缺省 default_discount
    """
    code_by_id = {c.id: c.customer_code for c in db.session.execute(db.select(Customer)).scalars()}

    discount_by_pair: dict[tuple[int, str], float] = {}
    for s in db.session.execute(db.select(CustomerSellDiscount)).scalars():
        discount_by_pair[(s.customer_id, s.model_name)] = float(s.sell_discount or 0)

    # 逐 (客户, 模型) 聚合器
    hourly_io: dict[tuple[int, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    tot_input: dict[tuple[int, str], float] = defaultdict(float)
    tot_output: dict[tuple[int, str], float] = defaultdict(float)
    tot_cache: dict[tuple[int, str], float] = defaultdict(float)
    tot_cache_miss: dict[tuple[int, str], float] = defaultdict(float)
    tot_io: dict[tuple[int, str], float] = defaultdict(float)
    self_io: dict[tuple[int, str], float] = defaultdict(float)
    vendor_io: dict[tuple[int, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))

    rows = db.session.execute(
        db.select(
            CustomerUsageHourly.customer_id,
            CustomerUsageHourly.model,
            CustomerUsageHourly.data_time,
            CustomerUsageHourly.input_output,
            CustomerUsageHourly.total_input,
            CustomerUsageHourly.output_token,
            CustomerUsageHourly.cache_token,
            CustomerUsageHourly.cache_miss_token,
            CustomerUsageHourly.model_source,
            CustomerUsageHourly.provider,
        )
    ).all()

    for (customer_id, model, data_time, io, ti, ot, ct, cmt, source, provider) in rows:
        pair = (customer_id, model)
        io = float(io or 0)
        ts = data_time.isoformat()
        hourly_io[pair][ts] += io
        tot_input[pair] += float(ti or 0)
        tot_output[pair] += float(ot or 0)
        tot_cache[pair] += float(ct or 0)
        tot_cache_miss[pair] += float(cmt or 0)
        tot_io[pair] += io
        if source == SELF_SOURCE:
            self_io[pair] += io
        else:
            vendor_io[pair][provider] += io

    items: list[DemandSnapshotItem] = []
    for pair in sorted(hourly_io):
        customer_id, model = pair
        series_map = hourly_io[pair]
        series = [(ts, series_map[ts] / 60.0) for ts in sorted(series_map)]
        expected_tpm = series[-1][1] if series else 0.0  # 最新一小时 = 当前负载

        out_sum = tot_output[pair]
        input_ratio = (tot_input[pair] / out_sum) if out_sum > 0 else default_input_ratio
        cache_denom = tot_cache[pair] + tot_cache_miss[pair]
        cache_hit_rate = (tot_cache[pair] / cache_denom) if cache_denom > 0 else default_cache_hit_rate
        io_sum = tot_io[pair]
        current_self_ratio = (self_io[pair] / io_sum) if io_sum > 0 else 0.0
        current_vendor_ratios = (
            {prov: v / io_sum for prov, v in vendor_io[pair].items()} if io_sum > 0 else {}
        )

        customer_code = code_by_id.get(customer_id, str(customer_id))
        items.append(DemandSnapshotItem(
            report_id=f"USG-{customer_code}-{model}",
            customer_code=customer_code,
            model_name=model,
            expected_tpm=expected_tpm,
            expected_rpm=0.0,
            discount_rate=discount_by_pair.get(pair, default_discount),
            input_ratio=input_ratio,
            cache_hit_rate=cache_hit_rate,
            current_self_ratio=current_self_ratio,
            current_vendor_ratios=current_vendor_ratios,
            quality_score=0.0,
            tpm_series=series,
        ))
    return items
