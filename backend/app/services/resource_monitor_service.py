from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from ..extensions import db
from ..integrations import resource_monitor_client
from ..integrations.resource_monitor_client import (
    KINGRESS_METRICS,
    MONITOR_METRICS,
    TOKEN_METRICS,
    ParsedMonitor,
    parse_envelope,
)
from ..models import (
    ClusterModelTpm,
    ConsumerModelTpm,
    GpuNodeCount,
    MonitorBatch,
    MonitorBatchStatus,
    MonitorConsumer,
)
from ..utils.errors import NotFound, ValidationFailed
from ..utils.time import utcnow


# token 侧接口 TPM 单位是「万」，还原为原始 TPM。
WAN = 10000


def _parse_time(s: str | None) -> datetime | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


class ResourceMonitorService:
    # ---------------- 采集 ----------------
    def run_collection(self, triggered_by: str = "cron",
                       start_time: str | None = None,
                       end_time: str | None = None) -> MonitorBatch:
        now = utcnow()
        batch = MonitorBatch(
            batch_no="M" + now.strftime("%Y%m%d%H%M%S%f")[:-3],
            triggered_by=triggered_by,
            started_at=now,
            status=MonitorBatchStatus.RUNNING,
        )
        db.session.add(batch)
        db.session.flush()

        client = resource_monitor_client()
        errors: list[str] = []
        cluster_rows = 0
        consumer_rows = 0
        consumers_ok = 0

        # 1) token 侧：全局拉一次（与客户无关的产能）。
        try:
            token_env = client.fetch(metrics=sorted(TOKEN_METRICS),
                                     start_time=start_time, end_time=end_time)
            token_parsed = parse_envelope(token_env)
            cluster_rows = self._persist_token_side(batch, token_parsed)
            if batch.window_start is None:
                batch.window_start = _parse_time(token_parsed.start_time)
                batch.window_end = _parse_time(token_parsed.end_time)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"token 侧采集失败: {exc}")

        # 2) kingress 侧：逐 enabled consumer 拉取。
        consumers = list(db.session.execute(
            select(MonitorConsumer).where(MonitorConsumer.enabled.is_(True))
        ).scalars())
        batch.consumers_total = len(consumers)
        for consumer in consumers:
            try:
                env = client.fetch(metrics=sorted(KINGRESS_METRICS),
                                   ai_consumer=consumer.ai_consumer,
                                   start_time=start_time, end_time=end_time)
                parsed = parse_envelope(env)
                n = self._persist_consumer_side(batch, consumer, parsed)
                consumer_rows += n
                consumers_ok += 1
                consumer.last_collected_at = now
                if batch.window_start is None:
                    batch.window_start = _parse_time(parsed.start_time)
                    batch.window_end = _parse_time(parsed.end_time)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"consumer[{consumer.ai_consumer}] 采集失败: {exc}")

        batch.cluster_rows = cluster_rows
        batch.consumer_rows = consumer_rows
        batch.consumers_ok = consumers_ok
        batch.finished_at = utcnow()
        if errors and consumers_ok == 0 and cluster_rows == 0:
            batch.status = MonitorBatchStatus.FAILED
        elif errors:
            batch.status = MonitorBatchStatus.PARTIAL
        else:
            batch.status = MonitorBatchStatus.SUCCESS
        if errors:
            batch.error_message = " | ".join(errors)[:2048]
        db.session.commit()
        return batch

    def _persist_token_side(self, batch: MonitorBatch, parsed: ParsedMonitor) -> int:
        # 三个按 inference_model 的 metric 对齐成集群瞬时行；GPU 台数独立表。
        # 注意：同一 inference_model 可能出现多条 series（接口重复），按语义聚合而非后者覆盖：
        #   tpm/node_count 相加；node_avg_tpm 事后按 tpm/node_count 重算（强度量不可直接相加）。
        cluster_tpm = self._collapse(parsed.series_of("token_cluster_tpm"), "inference_model")
        node_count = self._collapse(parsed.series_of("token_node_count"), "inference_model")
        node_avg = self._collapse(parsed.series_of("token_node_avg_tpm"), "inference_model")

        clusters = set(cluster_tpm) | set(node_count) | set(node_avg)
        rows = 0
        for cluster_name in clusters:
            times = (set(cluster_tpm.get(cluster_name, {}))
                     | set(node_count.get(cluster_name, {}))
                     | set(node_avg.get(cluster_name, {})))
            for time_str in times:
                dt = _parse_time(time_str)
                if dt is None:
                    continue
                tpm = self._sum(cluster_tpm, cluster_name, time_str) * WAN
                nodes = int(self._sum(node_count, cluster_name, time_str))
                if nodes > 0:
                    avg_tpm = tpm / nodes                       # 强度量：由总量/台数重算
                else:
                    avg_tpm = self._mean(node_avg, cluster_name, time_str) * WAN
                db.session.add(ClusterModelTpm(
                    batch_id=batch.id,
                    data_time=dt,
                    cluster_name=cluster_name,
                    tpm=tpm,
                    node_count=nodes,
                    node_avg_tpm=avg_tpm,
                ))
                rows += 1

        # GPU 台数（按 label_accelerator，同型号多条 series 相加）
        gpu = self._collapse(parsed.series_of("token_gpu_node_count"), "label_accelerator")
        for acc, by_time in gpu.items():
            for time_str in by_time:
                dt = _parse_time(time_str)
                if dt is None:
                    continue
                db.session.add(GpuNodeCount(
                    batch_id=batch.id, data_time=dt,
                    accelerator=acc, node_count=int(self._sum(gpu, acc, time_str)),
                ))
        db.session.flush()
        return rows

    def _persist_consumer_side(self, batch: MonitorBatch, consumer: MonitorConsumer,
                               parsed: ParsedMonitor) -> int:
        # 同一 ai_model 若多条 series：tpm 相加；比率/均值/命中率取均值（强度量不可相加）。
        tpm = self._collapse(parsed.series_of("kingress_model_tpm"), "ai_model")
        third = self._collapse(parsed.series_of("kingress_thirdparty_ratio"), "ai_model")
        ksyun = self._collapse(parsed.series_of("kingress_ksyun_ratio"), "ai_model")
        ain = self._collapse(parsed.series_of("kingress_avg_input_token"), "ai_model")
        aout = self._collapse(parsed.series_of("kingress_avg_output_token"), "ai_model")
        cache = self._collapse(parsed.series_of("kingress_cache_hit_rate"), "ai_model")

        rows = 0
        for model in set(tpm):  # 以有售卖量的模型为主轴
            for time_str in tpm.get(model, {}):
                dt = _parse_time(time_str)
                if dt is None:
                    continue
                db.session.add(ConsumerModelTpm(
                    batch_id=batch.id,
                    data_time=dt,
                    ai_consumer=consumer.ai_consumer,
                    customer_code=consumer.customer_code,
                    ai_model=model,
                    tpm=self._sum(tpm, model, time_str),
                    self_ratio=self._mean_or_none(ksyun, model, time_str),
                    thirdparty_ratio=self._mean_or_none(third, model, time_str),
                    avg_input_token=self._mean_or_none(ain, model, time_str),
                    avg_output_token=self._mean_or_none(aout, model, time_str),
                    cache_hit_rate=self._mean_or_none(cache, model, time_str),
                ))
                rows += 1
        db.session.flush()
        return rows

    # ---- series 聚合工具：{label: {time: [values]}}，同 label 多 series 归并 ----
    @staticmethod
    def _collapse(series_list, label_key: str) -> dict:
        out: dict[str, dict[str, list]] = {}
        for s in series_list:
            key = s.labels.get(label_key)
            if key is None:
                continue
            bucket = out.setdefault(key, {})
            for p in s.points:
                if p.value is None:
                    continue
                bucket.setdefault(p.time, []).append(p.value)
        return out

    @staticmethod
    def _sum(idx: dict, key: str, time_str: str) -> float:
        return float(sum(idx.get(key, {}).get(time_str, []) or [0]))

    @staticmethod
    def _mean(idx: dict, key: str, time_str: str) -> float:
        vals = idx.get(key, {}).get(time_str, [])
        return float(sum(vals) / len(vals)) if vals else 0.0

    @staticmethod
    def _mean_or_none(idx: dict, key: str, time_str: str):
        vals = idx.get(key, {}).get(time_str, [])
        return float(sum(vals) / len(vals)) if vals else None

    def get_batch(self, batch_id: int) -> MonitorBatch:
        batch = db.session.get(MonitorBatch, batch_id)
        if not batch:
            raise NotFound("采集批次不存在", details={"id": batch_id})
        return batch

    # ---------------- consumer 维护 ----------------
    def list_consumers(self, enabled: bool | None = None) -> list[MonitorConsumer]:
        stmt = select(MonitorConsumer).order_by(MonitorConsumer.id.asc())
        if enabled is not None:
            stmt = stmt.where(MonitorConsumer.enabled.is_(enabled))
        return list(db.session.execute(stmt).scalars())

    def add_consumer(self, ai_consumer: str, customer_code: str | None = None,
                     customer_name: str | None = None, note: str | None = None) -> MonitorConsumer:
        ai_consumer = (ai_consumer or "").strip()
        if not ai_consumer:
            raise ValidationFailed("ai_consumer 不能为空")
        existing = db.session.execute(
            select(MonitorConsumer).where(MonitorConsumer.ai_consumer == ai_consumer)
        ).scalar_one_or_none()
        if existing:
            # 幂等：已存在则复用并重新启用（客户需求回归时）。
            existing.enabled = True
            if customer_code is not None:
                existing.customer_code = customer_code
            if customer_name is not None:
                existing.customer_name = customer_name
            if note is not None:
                existing.note = note
            db.session.commit()
            return existing
        consumer = MonitorConsumer(
            ai_consumer=ai_consumer,
            customer_code=customer_code,
            customer_name=customer_name,
            note=note,
            enabled=True,
        )
        db.session.add(consumer)
        db.session.commit()
        return consumer

    def remove_consumer(self, ai_consumer: str, hard: bool = False) -> None:
        consumer = db.session.execute(
            select(MonitorConsumer).where(MonitorConsumer.ai_consumer == ai_consumer)
        ).scalar_one_or_none()
        if not consumer:
            raise NotFound("客户不在采集清单中", details={"ai_consumer": ai_consumer})
        if hard:
            db.session.delete(consumer)
        else:
            consumer.enabled = False  # 软删：客户无需求时停采，保留历史
        db.session.commit()
