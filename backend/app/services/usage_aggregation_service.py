"""把 consumer_model_tpm（分钟级中转数据）按 客户×模型 聚合成 customer_usage_hourly。

口径：
- 小时总量 total = Σ 该小时各分钟 tpm（consumer_model_tpm.tpm 为自建+三方总量）
- 用 thirdparty_ratio（%）把总量拆成 自建量 = total×(1-tr) 与 三方量 = total×tr，
  分别落成一条 hourly（自建行 provider 取 provider_mappings、model_source=自建；
  三方行 provider="thirdparty"、model_source=三方）
- 输入/输出按 avg_input:avg_output 比例、缓存按 cache_hit_rate 拆（两部分同比例）
- user_id 暂留空；ai_consumer=="__all__" 作为全客户汇总的特殊客户保留
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select

from ..extensions import db
from ..models import (
    ConsumerModelTpm,
    CustomerUsageHourly,
    MonitorConsumer,
    ProviderMapping,
)

SELF_SOURCE = "自建"
THIRD_SOURCE = "三方"
THIRD_PROVIDER = "thirdparty"
GLOBAL_AI_CONSUMER = "__all__"


def _mean(values) -> float:
    nums = [float(v) for v in values if v is not None]
    return sum(nums) / len(nums) if nums else 0.0


class UsageAggregationService:
    def aggregate_hourly(self, hour_start: datetime | None = None) -> dict:
        """聚合某个整点小时的数据；hour_start 缺省取 consumer_model_tpm 里最新数据所在小时。"""
        if hour_start is None:
            latest = db.session.execute(
                select(func.max(ConsumerModelTpm.data_time))
            ).scalar()
            if latest is None:
                return {"hour_start": None, "rows": 0}
            hour_start = latest.replace(minute=0, second=0, microsecond=0)
        hour_end = hour_start + timedelta(hours=1)

        rows = db.session.execute(
            select(ConsumerModelTpm).where(
                ConsumerModelTpm.data_time >= hour_start,
                ConsumerModelTpm.data_time < hour_end,
            )
        ).scalars().all()

        groups: dict[tuple[str, str], list[ConsumerModelTpm]] = {}
        for r in rows:
            groups.setdefault((r.customer_code, r.ai_model), []).append(r)

        provider_index = self._provider_index()
        consumer_cache: dict[str, MonitorConsumer] = {}
        written = 0
        for (customer_code, ai_model), pts in groups.items():
            consumer = self._resolve_consumer(customer_code, consumer_cache)
            if consumer is None:
                continue  # 该 user_id 不在 monitor_consumers（数据缺口），跳过避免悬空 customer_id
            customer_name = consumer.customer_name or consumer.ai_consumer

            total = sum(int(p.tpm or 0) for p in pts)  # 小时总量（自建+三方）
            if total <= 0:
                continue
            ai = _mean([p.avg_input_token for p in pts])
            ao = _mean([p.avg_output_token for p in pts])
            chr_pct = _mean([p.cache_hit_rate for p in pts])
            input_share = ai / (ai + ao) if (ai + ao) > 0 else 0.5
            chr_frac = min(max(chr_pct / 100.0, 0.0), 1.0)

            # 三方占比：优先 thirdparty_ratio；缺失时用 (1-ksyun_ratio) 兜底；再缺失按全自建。
            tr_vals = [p.thirdparty_ratio for p in pts if p.thirdparty_ratio is not None]
            if tr_vals:
                tr_frac = _mean(tr_vals) / 100.0
            else:
                sr_vals = [p.self_ratio for p in pts if p.self_ratio is not None]
                tr_frac = (1 - _mean(sr_vals) / 100.0) if sr_vals else 0.0
            tr_frac = min(max(tr_frac, 0.0), 1.0)

            self_io = round(total * (1 - tr_frac))
            third_io = total - self_io
            self_provider, _ = self._provider_of(customer_name, ai_model, provider_index)

            if self_io > 0:
                self._write_row(consumer.id, customer_name, hour_start, ai_model,
                                self_provider, SELF_SOURCE, self_io, input_share, chr_frac)
                written += 1
            if third_io > 0:
                self._write_row(consumer.id, customer_name, hour_start, ai_model,
                                THIRD_PROVIDER, THIRD_SOURCE, third_io, input_share, chr_frac)
                written += 1

        db.session.commit()
        return {"hour_start": hour_start.isoformat(), "rows": written}

    # ---------------- helpers ----------------
    @staticmethod
    def _provider_index() -> dict[tuple[str, str], str]:
        """{(customer_name, model_name_lower): provider}；同键多 provider 取首个。"""
        index: dict[tuple[str, str], str] = {}
        for m in db.session.execute(select(ProviderMapping)).scalars():
            key = (m.customer_name, (m.model_name or "").lower())
            index.setdefault(key, m.provider)
        return index

    @staticmethod
    def _provider_of(customer_name: str, model: str, index: dict) -> tuple[str, str]:
        provider = index.get((customer_name, (model or "").lower()))
        if provider:
            return provider, SELF_SOURCE
        return "", SELF_SOURCE

    @staticmethod
    def _resolve_consumer(customer_code: str,
                           cache: dict[str, MonitorConsumer]) -> MonitorConsumer | None:
        """按 customer_code(user_id) 解析客户。customer_code 现为 NOT NULL UNIQUE 自然主键，
        不再自动建档（避免无 user_id 的脏行）；未在册返回 None，由调用方跳过。__all__ 需预录入。
        """
        if customer_code in cache:
            return cache[customer_code]
        consumer = db.session.execute(
            select(MonitorConsumer).where(MonitorConsumer.customer_code == customer_code)
        ).scalar_one_or_none()
        if consumer is None:
            return None
        cache[customer_code] = consumer
        return consumer

    @staticmethod
    def _write_row(customer_id, customer_name, data_time, model, provider, model_source,
                   io, input_share, chr_frac):
        total_input = round(io * input_share)
        output_token = io - total_input
        cache_token = round(total_input * chr_frac)
        cache_miss_token = total_input - cache_token
        row = db.session.execute(
            select(CustomerUsageHourly).where(
                CustomerUsageHourly.customer_id == customer_id,
                CustomerUsageHourly.data_time == data_time,
                CustomerUsageHourly.model == model,
                CustomerUsageHourly.provider == provider,
            )
        ).scalar_one_or_none()
        if row is None:
            row = CustomerUsageHourly(
                customer_id=customer_id,
                data_time=data_time,
                model=model,
                provider=provider,
                stat_date=data_time.date(),
            )
            db.session.add(row)
        row.customer_name = customer_name
        row.model_source = model_source
        row.data_source = "生产"
        row.user_id = ""
        row.input_output = io
        row.total_input = total_input
        row.output_token = output_token
        row.cache_token = cache_token
        row.cache_miss_token = cache_miss_token

