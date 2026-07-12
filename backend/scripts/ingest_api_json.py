"""一次性录入脚本：把资源模型监控接口的真实返回（api.json）录入监控数据表。

参考 resource_monitor_client / ResourceMonitorService 的解析与落库逻辑：
  - parse_envelope 把接口信封解析为结构化 ParsedMonitor
  - token 侧（全局产能）-> cluster_model_tpm + gpu_node_count
  - kingress 侧（售卖瞬时 TPM）-> consumer_model_tpm

与线上采集的差异：api.json 是一次「全局」返回（kingress 未按 ai_consumer 拆分，
series 仅带 ai_model），因此这里以哨兵 ai_consumer="__all__" 记录全局聚合。

规则「入库前清理历史」：先清空 4 张监控表（子表先删再删批次），再建一个新批次写入，
可重复运行（幂等）。

用法（backend 目录下）：
    .venv/Scripts/python.exe scripts/ingest_api_json.py [路径/api.json]
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
REPO_ROOT = BACKEND_DIR.parent

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.integrations.resource_monitor_client import parse_envelope  # noqa: E402
from app.models import (  # noqa: E402
    ClusterModelTpm,
    ConsumerModelTpm,
    GpuNodeCount,
    MonitorBatch,
    MonitorBatchStatus,
)
from app.services.resource_monitor_service import ResourceMonitorService, _parse_time  # noqa: E402
from app.utils.time import utcnow  # noqa: E402

API_JSON = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "api.json"

# 全局返回无 ai_consumer 维度，用哨兵标定这批全局聚合数据。
GLOBAL_AI_CONSUMER = "__all__"


def clear_history():
    """清空监控 4 表历史数据（子表先删，最后删批次以满足外键）。"""
    c = ConsumerModelTpm.query.delete()
    g = GpuNodeCount.query.delete()
    t = ClusterModelTpm.query.delete()
    b = MonitorBatch.query.delete()
    db.session.commit()
    print(f"[clear] consumer_model_tpm {c}、gpu_node_count {g}、"
          f"cluster_model_tpm {t}、monitor_batches {b} 行已清理")


def ingest(envelope: dict):
    parsed = parse_envelope(envelope)
    now = utcnow()
    batch = MonitorBatch(
        batch_no="M" + now.strftime("%Y%m%d%H%M%S%f")[:-3],
        triggered_by="ingest",
        started_at=now,
        status=MonitorBatchStatus.RUNNING,
        window_start=_parse_time(parsed.start_time),
        window_end=_parse_time(parsed.end_time),
        raw_json={"source": "api.json"},
    )
    db.session.add(batch)
    db.session.flush()

    svc = ResourceMonitorService()
    cluster_rows = svc._persist_token_side(batch, parsed)
    consumer = SimpleNamespace(ai_consumer=GLOBAL_AI_CONSUMER, customer_code=None)
    consumer_rows = svc._persist_consumer_side(batch, consumer, parsed)

    batch.cluster_rows = cluster_rows
    batch.consumer_rows = consumer_rows
    batch.consumers_total = 1
    batch.consumers_ok = 1
    batch.finished_at = utcnow()
    batch.status = MonitorBatchStatus.SUCCESS
    db.session.commit()
    print(f"[ingest] 批次 {batch.batch_no} 窗口 {parsed.start_time} ~ {parsed.end_time}："
          f"cluster_model_tpm {cluster_rows} 行、consumer_model_tpm {consumer_rows} 行")


def main():
    print(f"api.json: {API_JSON}")
    envelope = json.loads(API_JSON.read_text(encoding="utf-8"))
    app = create_app("dev")
    with app.app_context():
        db.create_all()
        clear_history()
        ingest(envelope)
        print("\n[done] 各表现有行数：")
        for label, model in [
            ("monitor_batches", MonitorBatch),
            ("cluster_model_tpm", ClusterModelTpm),
            ("gpu_node_count", GpuNodeCount),
            ("consumer_model_tpm", ConsumerModelTpm),
        ]:
            print(f"  {label:22} {db.session.query(model).count()}")


if __name__ == "__main__":
    main()
