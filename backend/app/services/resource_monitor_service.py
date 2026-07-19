from __future__ import annotations

from datetime import datetime

from flask import current_app
from sqlalchemy import select

from ..extensions import db
from ..integrations import resource_monitor_client
from ..integrations.resource_monitor_client import (
    KINGRESS_METRICS,
    MONITOR_METRICS,
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

# kingress 侧「全客户汇总」的特殊 ai_consumer：全局拉取（不区分客户）落此值。
# 与 usage_aggregation_service.GLOBAL_AI_CONSUMER 同口径，下游按需排除/单独看待。
GLOBAL_AI_CONSUMER = "__all__"


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
        empty_consumers: list[str] = []      # 逐客户拉取返回空（数据缺口，非异常）
        cluster_rows = 0
        consumer_rows = 0
        consumers_ok = 0

        # 1) 全局拉一次（所有指标）：token 侧 -> 集群/GPU 产能（与客户无关）；
        #    kingress 侧 -> ai_consumer='__all__' 的全客户汇总。线上 kingress 只按
        #    ai_model 全局聚合、响应无客户维度，全局结果即「不区分客户」的汇总。
        try:
            env = client.fetch(metrics=sorted(MONITOR_METRICS),
                               start_time=start_time, end_time=end_time)
            parsed = parse_envelope(env)
            cluster_rows = self._persist_token_side(batch, parsed)
            consumer_rows += self._persist_kingress_side(
                batch, parsed, ai_consumer=GLOBAL_AI_CONSUMER, customer_code=GLOBAL_AI_CONSUMER)
            if batch.window_start is None:
                batch.window_start = _parse_time(parsed.start_time)
                batch.window_end = _parse_time(parsed.end_time)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"全局采集失败: {exc}")

        # 2) kingress 逐客户：以 monitor_consumers.customer_code 作为接口的 user_id 过滤拉取。
        #    接口的逐客户过滤参数是 user_id（线上实测有效；ai_consumer 参数被忽略）。
        #    customer_code 需存放该客户在接口侧的真实 user_id，否则该客户返回空。
        consumers = list(db.session.execute(
            select(MonitorConsumer).where(MonitorConsumer.enabled.is_(True))
        ).scalars())
        batch.consumers_total = len(consumers)
        for consumer in consumers:
            # customer_code(user_id) 现为 NOT NULL 唯一，必有值；__all__ 行 enabled=False 不在此列。
            try:
                env = client.fetch(metrics=sorted(KINGRESS_METRICS),
                                   user_id=consumer.customer_code,
                                   start_time=start_time, end_time=end_time)
                parsed = parse_envelope(env)
                n = self._persist_kingress_side(
                    batch, parsed,
                    ai_consumer=consumer.ai_consumer,
                    customer_code=consumer.customer_code)
                consumer_rows += n
                consumers_ok += 1
                consumer.last_collected_at = now
                if batch.window_start is None:
                    batch.window_start = _parse_time(parsed.start_time)
                    batch.window_end = _parse_time(parsed.end_time)
                if n == 0:
                    empty_consumers.append(
                        f"{consumer.ai_consumer}[user_id={consumer.customer_code}] 返回0条")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"consumer[{consumer.ai_consumer}] 采集失败: {exc}")

        batch.cluster_rows = cluster_rows
        batch.consumer_rows = consumer_rows
        batch.consumers_ok = consumers_ok
        batch.finished_at = utcnow()
        if errors and cluster_rows == 0 and consumer_rows == 0:
            batch.status = MonitorBatchStatus.FAILED
        elif errors:
            batch.status = MonitorBatchStatus.PARTIAL
        else:
            batch.status = MonitorBatchStatus.SUCCESS
        if errors:
            batch.error_message = " | ".join(errors)[:2048]
        if empty_consumers:
            # 数据缺口（非异常）：仅记日志，便于排查 customer_code 是否为有效 user_id；
            # 不改批次状态，避免逐客户未配 user_id 时把每次定时采集都标成 partial。
            try:
                current_app.logger.warning(
                    "[resource_monitor] 逐客户拉取返回空/跳过 %d 个: %s",
                    len(empty_consumers), " | ".join(empty_consumers)[:1000])
            except Exception:  # noqa: BLE001  无 app 上下文时静默
                pass
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
        # 内存按 (cluster_name, dt) 去重（接口偶发返回同点多次），后者覆盖；再跳过库内已存在行
        # （相邻切片端点 inclusive 重叠、或重跑同批次时幂等）。
        cluster_rows: dict[tuple, tuple] = {}
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
                cluster_rows[(cluster_name, dt)] = (tpm, nodes, avg_tpm)

        # GPU 台数（按 label_accelerator，同型号多条 series 相加）
        gpu = self._collapse(parsed.series_of("token_gpu_node_count"), "label_accelerator")
        gpu_rows: dict[tuple, int] = {}
        for acc, by_time in gpu.items():
            for time_str in by_time:
                dt = _parse_time(time_str)
                if dt is None:
                    continue
                gpu_rows[(acc, dt)] = int(self._sum(gpu, acc, time_str))

        added = 0
        added += self._add_new_cluster_rows(batch, cluster_rows)
        added += self._add_new_gpu_rows(batch, gpu_rows)
        db.session.flush()
        return added

    def _add_new_cluster_rows(self, batch: MonitorBatch,
                              cluster_rows: dict[tuple, tuple]) -> int:
        """跳过库内已存在的 (cluster_name, dt)，仅新增剩余行。"""
        if not cluster_rows:
            return 0
        dts = [dt for _, dt in cluster_rows]
        existing = set(db.session.execute(
            select(ClusterModelTpm.cluster_name, ClusterModelTpm.data_time).where(
                ClusterModelTpm.batch_id == batch.id,
                ClusterModelTpm.data_time >= min(dts),
                ClusterModelTpm.data_time <= max(dts),
            )
        ).all())
        added = 0
        for (cluster_name, dt), (tpm, nodes, avg_tpm) in cluster_rows.items():
            if (cluster_name, dt) in existing:
                continue
            db.session.add(ClusterModelTpm(
                batch_id=batch.id, data_time=dt, cluster_name=cluster_name,
                tpm=tpm, node_count=nodes, node_avg_tpm=avg_tpm,
            ))
            added += 1
        return added

    def _add_new_gpu_rows(self, batch: MonitorBatch, gpu_rows: dict[tuple, int]) -> int:
        if not gpu_rows:
            return 0
        dts = [dt for _, dt in gpu_rows]
        existing = set(db.session.execute(
            select(GpuNodeCount.accelerator, GpuNodeCount.data_time).where(
                GpuNodeCount.batch_id == batch.id,
                GpuNodeCount.data_time >= min(dts),
                GpuNodeCount.data_time <= max(dts),
            )
        ).all())
        added = 0
        for (acc, dt), node_count in gpu_rows.items():
            if (acc, dt) in existing:
                continue
            db.session.add(GpuNodeCount(
                batch_id=batch.id, data_time=dt, accelerator=acc, node_count=node_count,
            ))
            added += 1
        return added

    def _persist_kingress_side(self, batch: MonitorBatch, parsed: ParsedMonitor,
                               ai_consumer: str, customer_code: str | None) -> int:
        """把 kingress 解析结果按 ai_model 聚合写入 consumer_model_tpm。

        ``ai_consumer``/``customer_code`` 由调用方提供：
          - 全局汇总传 ``ai_consumer='__all__'``、``customer_code='__all__'``；
          - 逐客户传 ``ai_consumer=客户名``、``customer_code=该客户 user_id``。
        同一 ai_model 若多条 series：tpm 相加；比率/均值/命中率取均值（强度量不可相加）。
        幂等：内存按 (ai_model, dt) 去重并跳过库内已存在行（相邻切片端点重叠/重跑安全）。
        """
        tpm = self._collapse(parsed.series_of("kingress_model_tpm"), "ai_model")
        third = self._collapse(parsed.series_of("kingress_thirdparty_ratio"), "ai_model")
        ksyun = self._collapse(parsed.series_of("kingress_ksyun_ratio"), "ai_model")
        ain = self._collapse(parsed.series_of("kingress_avg_input_token"), "ai_model")
        aout = self._collapse(parsed.series_of("kingress_avg_output_token"), "ai_model")
        cache = self._collapse(parsed.series_of("kingress_cache_hit_rate"), "ai_model")

        rows_map: dict[tuple, dict] = {}
        for model in set(tpm):  # 以有售卖量的模型为主轴
            for time_str in tpm.get(model, {}):
                dt = _parse_time(time_str)
                if dt is None:
                    continue
                rows_map[(model, dt)] = dict(
                    tpm=self._sum(tpm, model, time_str),
                    self_ratio=self._mean_or_none(ksyun, model, time_str),
                    thirdparty_ratio=self._mean_or_none(third, model, time_str),
                    avg_input_token=self._mean_or_none(ain, model, time_str),
                    avg_output_token=self._mean_or_none(aout, model, time_str),
                    cache_hit_rate=self._mean_or_none(cache, model, time_str),
                )

        added = 0
        if rows_map:
            dts = [dt for _, dt in rows_map]
            existing = set(db.session.execute(
                select(ConsumerModelTpm.ai_model, ConsumerModelTpm.data_time).where(
                    ConsumerModelTpm.batch_id == batch.id,
                    ConsumerModelTpm.customer_code == customer_code,
                    ConsumerModelTpm.data_time >= min(dts),
                    ConsumerModelTpm.data_time <= max(dts),
                )
            ).all())
            for (model, dt), fields in rows_map.items():
                if (model, dt) in existing:
                    continue
                db.session.add(ConsumerModelTpm(
                    batch_id=batch.id, data_time=dt,
                    ai_consumer=ai_consumer, customer_code=customer_code,
                    ai_model=model, **fields,
                ))
                added += 1
        db.session.flush()
        return added

    def _persist_consumer_side(self, batch: MonitorBatch, consumer: MonitorConsumer,
                               parsed: ParsedMonitor) -> int:
        """兼容离线录入脚本(ingest_tmp_data)：转发到通用 _persist_kingress_side。"""
        return self._persist_kingress_side(batch, parsed,
                                            ai_consumer=consumer.ai_consumer,
                                            customer_code=consumer.customer_code)

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

    def add_consumer(self, ai_consumer: str, customer_code: str,
                     customer_name: str | None = None, note: str | None = None) -> MonitorConsumer:
        """新增/复用客户采集行。自然主键为 customer_code(user_id)；同一 ai_consumer 可多行。"""
        ai_consumer = (ai_consumer or "").strip()
        customer_code = (customer_code or "").strip()
        if not ai_consumer:
            raise ValidationFailed("ai_consumer 不能为空")
        if not customer_code:
            raise ValidationFailed("customer_code 不能为空")
        existing = db.session.execute(
            select(MonitorConsumer).where(MonitorConsumer.customer_code == customer_code)
        ).scalar_one_or_none()
        if existing:
            # 幂等：同 user_id 已存在则复用并重新启用（客户需求回归时）。
            existing.enabled = True
            existing.ai_consumer = ai_consumer
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

    def remove_consumer(self, customer_code: str, hard: bool = False) -> None:
        """按 customer_code(user_id) 软删/硬删单条采集行。"""
        consumer = db.session.execute(
            select(MonitorConsumer).where(MonitorConsumer.customer_code == customer_code)
        ).scalar_one_or_none()
        if not consumer:
            raise NotFound("客户不在采集清单中", details={"customer_code": customer_code})
        if hard:
            db.session.delete(consumer)
        else:
            consumer.enabled = False  # 软删：客户无需求时停采，保留历史
        db.session.commit()
