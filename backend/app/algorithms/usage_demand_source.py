"""从实跑量 + 平台定价主数据实时构建求解器需求（DemandSnapshotItem 列表）。

替代「从 demands 表读已审批报备单」的旧输入源：realtime / time_period 两个算法的默认
需求来自本表构建的结果。demands 表仅保留给「前端手动指定新增某客户需求评估」路径。

需求 universe = customer_usage_hourly 中全部 (客户, 模型) 组合；售卖折扣左连
customer_sell_discounts（未签约用 default_discount）。各字段口径见 build 函数内注释，
与计划文档一致。
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from ..extensions import db
from ..models import ProviderMapping, MonitorConsumer, CustomerSellDiscount, CustomerUsageHourly
from .base import DemandSnapshotItem

SELF_SOURCE = "自建"
VENDOR_SOURCE = "第三方"
GLOBAL_AI_CONSUMER = "__all__"


def _cfg(key: str, default):
    """安全读取 Flask config（无 app 上下文时回退默认，保证可脱离 app 调用/测试）。"""
    try:
        from flask import current_app

        return current_app.config.get(key, default)
    except Exception:
        return default


def build_self_provider_whitelist() -> dict[str, set[str]]:
    """自建 provider 白名单：provider_mappings 里各 provider 按 model_name 聚合。
    只有 provider ∈ 该模型白名单，才算「本模型自建集群」提供的真自建产能。"""
    wl: dict[str, set[str]] = defaultdict(set)
    for m in db.session.execute(db.select(ProviderMapping)).scalars():
        if m.provider:
            wl[m.model_name].add(m.provider)
    return dict(wl)


def build_usage_demand_items(
    default_discount: float = 1.0,
    default_input_ratio: float = 1.0,
    default_cache_hit_rate: float = 0.0,
    *,
    apply_self_provider_whitelist: bool | None = None,
    exclude_customer_codes: Iterable[str] | None = None,
    period: str | None = None,
    restrict_to_sell_discount: bool = False,
) -> list[DemandSnapshotItem]:
    """把实跑量按 (客户, 模型) 聚合成 DemandSnapshotItem 列表。

    - expected_tpm：该组合**最新一个小时**的 TPM（当前负载）= Σio(最新小时)/60
    - tpm_series ：按 data_time 升序的 [(iso, Σio/60)]，同一整点跨结算日的多条求和
    - input_ratio：Σtotal_input / Σoutput_token（分母 0 退化 default_input_ratio）
    - cache_hit_rate：Σcache_token / (Σcache_token + Σcache_miss_token)
    - current_self_ratio：Σio[真自建] / Σio
    - current_vendor_ratios：{provider: Σio / Σio_total}（三方 + 被白名单剔除的错挂自建）
    - discount_rate：customer_sell_discounts.sell_discount，缺省 default_discount

    口径开关（默认取 config，可回退）：
    - apply_self_provider_whitelist：自建须 provider ∈ 本模型自建集群白名单，否则改判三方。
    - exclude_customer_codes：整户剔除的 customer_code（转售/网络客户），其量不计入。
    - period：idle/busy 时**只统计该时段小时**的数据（口径与波形拟合一致，全局忙时边界取
      config.WAVE_FIT_BUSY_HOURS），使 input_ratio/cache_hit_rate/自建占比/量都反映该时段行为；
      None（realtime 等）时统计全部小时（向后兼容）。
    - restrict_to_sell_discount：置 True 时需求 universe **只保留在 customer_sell_discounts 表里
      出现过的 (客户, 模型) 组合**（time_period 策略用）；未出现的客户/模型的用量整体不参与测算。
    """
    if apply_self_provider_whitelist is None:
        apply_self_provider_whitelist = _cfg("SELF_PROVIDER_WHITELIST_ENABLED", True)
    if exclude_customer_codes is None:
        exclude_customer_codes = _cfg("EXCLUDE_CUSTOMER_CODES", ())
    exclude_codes = set(exclude_customer_codes or ())
    whitelist = build_self_provider_whitelist() if apply_self_provider_whitelist else {}

    # 时段过滤：仅统计该时段小时的实跑（口径与拟合一致），非 idle/busy 则不过滤。
    period_hours: frozenset[int] | None = None
    if period:
        from ..models import WavePeriod
        if period in WavePeriod.ALL:
            from ..services.wave_fitting_service import WaveFittingService
            period_hours = WaveFittingService.period_hours(period)

    code_by_id: dict[int, str] = {}
    name_by_id: dict[int, str] = {}
    excluded_ids: set[int] = set()
    for c in db.session.execute(db.select(MonitorConsumer)).scalars():
        code_by_id[c.id] = c.customer_code
        name_by_id[c.id] = c.customer_name or ""
        # __all__ 是全客户汇总口径，非单客户，不作为需求参与计算；同时排除整户剔除名单。
        if c.ai_consumer == GLOBAL_AI_CONSUMER or c.customer_code in exclude_codes:
            excluded_ids.add(c.id)

    discount_by_pair: dict[tuple[int, str], float] = {}
    for s in db.session.execute(db.select(CustomerSellDiscount)).scalars():
        discount_by_pair[(s.customer_id, s.model_name)] = float(s.sell_discount or 0)

    # 售卖折扣白名单：restrict_to_sell_discount 时只保留 customer_sell_discounts 出现过的 (客户,模型)。
    allowed_pairs = set(discount_by_pair.keys()) if restrict_to_sell_discount else None


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
        if customer_id in excluded_ids:
            continue  # 整户剔除（转售/网络客户）
        if period_hours is not None and data_time.hour not in period_hours:
            continue  # 只统计该时段（idle/busy）小时的数据
        pair = (customer_id, model)
        io = float(io or 0)
        ts = data_time.isoformat()
        hourly_io[pair][ts] += io
        tot_input[pair] += float(ti or 0)
        tot_output[pair] += float(ot or 0)
        tot_cache[pair] += float(ct or 0)
        tot_cache_miss[pair] += float(cmt or 0)
        tot_io[pair] += io
        # 真自建 = 挂自建标记 且（未开白名单 或 provider ∈ 本模型自建集群白名单）
        is_true_self = (source == SELF_SOURCE) and (
            not apply_self_provider_whitelist or provider in whitelist.get(model, set())
        )
        if is_true_self:
            self_io[pair] += io
        else:
            vendor_io[pair][provider] += io

    items: list[DemandSnapshotItem] = []
    for pair in sorted(hourly_io):
        if allowed_pairs is not None and pair not in allowed_pairs:
            continue  # restrict_to_sell_discount：非售卖折扣表内的 (客户,模型) 不参与
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
            customer_name=name_by_id.get(customer_id, ""),
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
