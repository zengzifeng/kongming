"""录入 tmp_data 下的监控数据（1hr.json=__all__ 全局，consumer_*.json=按 customer_code），
并按整点小时聚合写入 customer_usage_hourly。

- token 侧（集群产能，全局，与客户无关）只从 1hr.json 录一次 -> cluster_model_tpm + gpu_node_count
- kingress 侧：1hr.json -> consumer_model_tpm(ai_consumer="__all__", customer_code="__all__")；
  每个 consumer_{customer_code}.json 若含 kingress 数据，则以文件名中的 customer_code(user_id)
  录入，ai_consumer(客户名) 由 monitor_consumers 反查。
- 聚合：对数据窗口内每个整点小时跑 UsageAggregationService.aggregate_hourly（per-user_id 粒度）。

用法（backend 目录下）：
    python scripts/ingest_tmp_data.py
"""
import json
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.integrations.resource_monitor_client import parse_envelope  # noqa: E402
from app.models import (  # noqa: E402
    ClusterModelTpm,
    ConsumerModelTpm,
    CustomerUsageHourly,
    GpuNodeCount,
    MonitorBatch,
    MonitorBatchStatus,
)
from app.services import UsageAggregationService  # noqa: E402
from app.services.resource_monitor_service import ResourceMonitorService, _parse_time  # noqa: E402
from app.utils.time import utcnow  # noqa: E402

DATA_DIR = BACKEND_DIR / "tmp_data"
ALL_FILE = DATA_DIR / "1hr.json"
GLOBAL_AI_CONSUMER = "__all__"


def clear_history():
    c = ConsumerModelTpm.query.delete()
    g = GpuNodeCount.query.delete()
    t = ClusterModelTpm.query.delete()
    h = CustomerUsageHourly.query.delete()
    b = MonitorBatch.query.delete()
    db.session.commit()
    print(f"[clear] consumer_model_tpm {c}、gpu_node_count {g}、cluster_model_tpm {t}、"
          f"customer_usage_hourly {h}、monitor_batches {b} 行已清理")


def _has_kingress(parsed) -> bool:
    return any(parsed.series_of(name) for name in (
        "kingress_model_tpm", "kingress_thirdparty_ratio", "kingress_ksyun_ratio",
        "kingress_avg_input_token", "kingress_avg_output_token", "kingress_cache_hit_rate",
    ))


def _consumer_name(path: Path) -> str:
    return path.name[len("consumer_"):-len(".json")]


def ingest(batch: MonitorBatch) -> tuple[int, int, list[str]]:
    svc = ResourceMonitorService()

    # 1) __all__：token 全局 + kingress 全局
    all_parsed = parse_envelope(json.loads(ALL_FILE.read_text(encoding="utf-8")))
    if batch.window_start is None:
        batch.window_start = _parse_time(all_parsed.start_time)
        batch.window_end = _parse_time(all_parsed.end_time)
    cluster_rows = svc._persist_token_side(batch, all_parsed)
    consumer_rows = svc._persist_consumer_side(
        batch, SimpleNamespace(ai_consumer=GLOBAL_AI_CONSUMER, customer_code=GLOBAL_AI_CONSUMER),
        all_parsed)
    db.session.commit()

    # 2) 逐个 consumer 文件：仅当含 kingress 数据时按客户名录入
    ingested_consumers: list[str] = []
    empty_consumers: list[str] = []
    # 文件名 consumer_{customer_code}.json -> _consumer_name 得 customer_code(user_id)。
    # ai_consumer(客户名) 由 monitor_consumers 反查；缺失则用 customer_code 兜底显示。
    name_by_code = {
        c.customer_code: (c.ai_consumer or c.customer_code)
        for c in db.session.query(MonitorConsumer).all()
    }
    for path in sorted(DATA_DIR.glob("consumer_*.json")):
        customer_code = _consumer_name(path)
        parsed = parse_envelope(json.loads(path.read_text(encoding="utf-8")))
        if not _has_kingress(parsed):
            empty_consumers.append(customer_code)
            continue
        ai_consumer = name_by_code.get(customer_code, customer_code)
        n = svc._persist_consumer_side(
            batch, SimpleNamespace(ai_consumer=ai_consumer, customer_code=customer_code), parsed)
        consumer_rows += n
        ingested_consumers.append(f"{ai_consumer}/{customer_code}({n})")
        db.session.commit()

    if empty_consumers:
        print(f"[warn] {len(empty_consumers)} 个 consumer 文件 kingress 为 null（无按客户数据），已跳过：")
        print("       " + "、".join(empty_consumers))
    if ingested_consumers:
        print(f"[consumer] 录入分客户 kingress：{'、'.join(ingested_consumers)}")
    return cluster_rows, consumer_rows, ingested_consumers


def aggregate_window(batch: MonitorBatch):
    svc = UsageAggregationService()

    def floor_hour(dt):
        return dt.replace(minute=0, second=0, microsecond=0)

    hour = floor_hour(batch.window_start)
    end = floor_hour(batch.window_end)
    total, buckets = 0, 0
    while hour <= end:
        r = svc.aggregate_hourly(hour)
        total += r["rows"]
        buckets += 1
        hour += timedelta(hours=1)
    print(f"[aggregate] 聚合 {buckets} 个整点小时，写入 customer_usage_hourly {total} 行")


def main():
    print(f"数据目录: {DATA_DIR}")
    app = create_app("dev")
    with app.app_context():
        db.create_all()
        clear_history()
        now = utcnow()
        batch = MonitorBatch(
            batch_no="M" + now.strftime("%Y%m%d%H%M%S%f")[:-3],
            triggered_by="ingest", started_at=now, status=MonitorBatchStatus.RUNNING,
            raw_json={"source": "tmp_data"},
        )
        db.session.add(batch)
        db.session.flush()
        cluster_rows, consumer_rows, _ = ingest(batch)
        batch.cluster_rows = cluster_rows
        batch.consumer_rows = consumer_rows
        batch.finished_at = utcnow()
        batch.status = MonitorBatchStatus.SUCCESS
        db.session.commit()
        print(f"[ingest] 批次 {batch.batch_no} 窗口 {batch.window_start} ~ {batch.window_end}："
              f"cluster_model_tpm {cluster_rows} 行、consumer_model_tpm {consumer_rows} 行")
        aggregate_window(batch)
        print("\n[done] 各表现有行数：")
        for label, model in [
            ("cluster_model_tpm", ClusterModelTpm),
            ("gpu_node_count", GpuNodeCount),
            ("consumer_model_tpm", ConsumerModelTpm),
            ("customer_usage_hourly", CustomerUsageHourly),
        ]:
            print(f"  {label:22} {db.session.query(model).count()}")


if __name__ == "__main__":
    main()
