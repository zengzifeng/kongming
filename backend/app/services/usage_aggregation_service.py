"""把 consumer_model_tpm（API 落地的分钟级中转数据）按 客户×模型 聚合成
customer_usage_hourly 的小时级跑量，供后续计算与展示。

口径：
- input_output（小时总 token）= Σ 该小时内各分钟点的 tpm（kingress_model_tpm 为每分钟总 token）
- 输入/输出拆分：按该小时 avg_input_token : avg_output_token 的均值比例
- 缓存命中/未命中拆分：按 cache_hit_rate（%）均值
- provider / model_source：查 provider_mappings(客户,模型)，命中=自建并取其 provider，否则=三方
- user_id 暂留空；ai_consumer=="__all__" 作为「集群粒度/全客户汇总」的特殊客户保留
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
            groups.setdefault((r.ai_consumer, r.ai_model), []).append(r)

        provider_index = self._provider_index()
        consumer_cache: dict[str, MonitorConsumer] = {}
        written = 0
        for (ai_consumer, ai_model), pts in groups.items():
            consumer = self._resolve_consumer(ai_consumer, consumer_cache)
            customer_name = consumer.customer_name or ai_consumer

            total = sum(int(p.tpm or 0) for p in pts)  # 小时总 token
            ai = _mean([p.avg_input_token for p in pts])
            ao = _mean([p.avg_output_token for p in pts])
            chr_pct = _mean([p.cache_hit_rate for p in pts])

            input_share = ai / (ai + ao) if (ai + ao) > 0 else 0.5
            total_input = round(total * input_share)
            output_token = total - total_input
            chr_frac = min(max(chr_pct / 100.0, 0.0), 1.0)
            cache_token = round(total_input * chr_frac)
            cache_miss_token = total_input - cache_token

            provider, model_source = self._provider_of(customer_name, ai_model, provider_index)

            self._upsert(
                customer_id=consumer.id,
                customer_name=customer_name,
                data_time=hour_start,
                model=ai_model,
                provider=provider,
                model_source=model_source,
                input_output=total,
                total_input=total_input,
                output_token=output_token,
                cache_token=cache_token,
                cache_miss_token=cache_miss_token,
            )
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
        return "", THIRD_SOURCE

    @staticmethod
    def _resolve_consumer(ai_consumer: str, cache: dict[str, MonitorConsumer]) -> MonitorConsumer:
        if ai_consumer in cache:
            return cache[ai_consumer]
        consumer = db.session.execute(
            select(MonitorConsumer).where(MonitorConsumer.ai_consumer == ai_consumer)
        ).scalar_one_or_none()
        if consumer is None:
            # 缺失则建档：__all__ 作为「全客户汇总」的特殊客户，默认不参与逐客户采集。
            consumer = MonitorConsumer(
                ai_consumer=ai_consumer,
                customer_name=ai_consumer,
                level="B",
                enabled=ai_consumer != GLOBAL_AI_CONSUMER,
            )
            db.session.add(consumer)
            db.session.flush()
        cache[ai_consumer] = consumer
        return consumer

    @staticmethod
    def _upsert(customer_id, customer_name, data_time, model, provider, model_source,
                input_output, total_input, output_token, cache_token, cache_miss_token):
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
        row.input_output = input_output
        row.total_input = total_input
        row.output_token = output_token
        row.cache_token = cache_token
        row.cache_miss_token = cache_miss_token
