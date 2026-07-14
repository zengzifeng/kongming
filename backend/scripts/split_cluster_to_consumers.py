"""按「集群(模型)↔客户」关联，把集群波形拆分到客户维度写入 consumer_model_tpm。

关联来源：provider_mappings.cluster_name ↔ cluster_model_tpm.cluster_name（大小写不敏感）。
拆分规则：
  - 集群只有 1 个客户 → 集群每分钟波形全量给该 ai_consumer；
  - 集群有 n 个客户 → 每分钟 tpm 平均成 n 份，分别给各 ai_consumer。
同一 (ai_consumer, model) 若来自多个集群，则按时间点求和。

写入后清空 customer_usage_hourly 并从 consumer_model_tpm 重新聚合（含 __all__ 与分客户）。

用法（backend 目录下）：
    python scripts/split_cluster_to_consumers.py
"""
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import func  # noqa: E402

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import (  # noqa: E402
    ClusterModelTpm,
    ConsumerModelTpm,
    CustomerUsageHourly,
    MonitorConsumer,
    ProviderMapping,
)
from app.services import UsageAggregationService  # noqa: E402

GLOBAL_AI_CONSUMER = "__all__"


def build_cluster_consumer_map():
    """cluster_name(lower) -> [(ai_consumer, model_name)]，仅取在 monitor_consumers 的客户。"""
    consumers = {c.ai_consumer for c in db.session.query(MonitorConsumer).all()}
    cmap: dict[str, set] = defaultdict(set)
    for m in db.session.query(ProviderMapping).all():
        if m.cluster_name and m.customer_name in consumers:
            cmap[m.cluster_name.lower()].add((m.customer_name, (m.model_name or "").lower()))
    return {k: sorted(v) for k, v in cmap.items()}


def _all_ratio_map(batch_id: int) -> dict:
    """{(model_lower, data_time): thirdparty_ratio(%)}，取自 __all__ 的 kingress 三方占比。"""
    rows = db.session.query(
        ConsumerModelTpm.ai_model, ConsumerModelTpm.data_time, ConsumerModelTpm.thirdparty_ratio
    ).filter(
        ConsumerModelTpm.ai_consumer == GLOBAL_AI_CONSUMER,
        ConsumerModelTpm.batch_id == batch_id,
    ).all()
    out: dict[tuple, float] = {}
    for model, dt, tr in rows:
        if tr is not None:
            out[((model or "").lower(), dt)] = float(tr)
    return out


def split_to_consumers(batch_id: int, cmap: dict) -> int:
    code_by_consumer = {c.ai_consumer: c.customer_code for c in db.session.query(MonitorConsumer).all()}
    all_ratio = _all_ratio_map(batch_id)
    rows = db.session.query(
        ClusterModelTpm.cluster_name, ClusterModelTpm.data_time, ClusterModelTpm.tpm
    ).filter(ClusterModelTpm.batch_id == batch_id).all()

    # (ai_consumer, model, data_time) -> {total, tr}
    acc_total: dict[tuple, float] = defaultdict(float)
    acc_tr: dict[tuple, float] = {}
    for cluster_name, data_time, tpm in rows:
        entries = cmap.get(cluster_name.lower())
        if not entries:
            continue
        n = len(entries)
        self_share = float(tpm or 0) / n           # 集群自建波形按客户均分 = 客户自建量
        for ai_consumer, model in entries:
            tr_pct = all_ratio.get((model, data_time), 0.0)   # 该模型三方占比(%)
            tr = min(max(tr_pct / 100.0, 0.0), 0.99)
            total = self_share / (1 - tr) if tr < 1 else self_share  # 反推总量(自建+三方)
            key = (ai_consumer, model, data_time)
            acc_total[key] += total
            acc_tr[key] = tr_pct

    # 清掉旧的分客户行（保留 __all__），再写入本次拆分结果到同一批次
    deleted = db.session.query(ConsumerModelTpm).filter(
        ConsumerModelTpm.ai_consumer != GLOBAL_AI_CONSUMER
    ).delete(synchronize_session=False)
    objs = []
    for (ai_consumer, model, data_time), total in acc_total.items():
        tr_pct = acc_tr[(ai_consumer, model, data_time)]
        objs.append(ConsumerModelTpm(
            batch_id=batch_id, data_time=data_time,
            ai_consumer=ai_consumer, customer_code=code_by_consumer.get(ai_consumer),
            ai_model=model, tpm=total,
            self_ratio=100.0 - tr_pct, thirdparty_ratio=tr_pct,
        ))
    db.session.bulk_save_objects(objs)
    db.session.commit()
    print(f"[split] 删除旧分客户行 {deleted}，写入分客户 consumer_model_tpm {len(objs)} 行"
          f"（tpm=自建+三方总量，thirdparty_ratio 取自 __all__ 同模型占比）")
    return len(objs)


def reaggregate_hourly():
    db.session.query(CustomerUsageHourly).delete()
    db.session.commit()
    win = db.session.query(func.min(ConsumerModelTpm.data_time),
                           func.max(ConsumerModelTpm.data_time)).one()
    if win[0] is None:
        print("[aggregate] consumer_model_tpm 为空")
        return
    svc = UsageAggregationService()

    def floor_hour(dt):
        return dt.replace(minute=0, second=0, microsecond=0)

    hour, end = floor_hour(win[0]), floor_hour(win[1])
    total = 0
    while hour <= end:
        total += svc.aggregate_hourly(hour)["rows"]
        hour += timedelta(hours=1)
    print(f"[aggregate] 重新聚合 customer_usage_hourly {total} 行")


def main():
    app = create_app("dev")
    with app.app_context():
        batch_id = db.session.query(func.max(ClusterModelTpm.batch_id)).scalar()
        if batch_id is None:
            print("cluster_model_tpm 无数据")
            return
        cmap = build_cluster_consumer_map()
        print(f"最新批次 {batch_id}；关联到客户的集群 {len(cmap)} 个")
        split_to_consumers(batch_id, cmap)
        reaggregate_hourly()
        # 各表计数
        for label, q in [
            ("consumer_model_tpm(分客户)", db.session.query(ConsumerModelTpm).filter(ConsumerModelTpm.ai_consumer != GLOBAL_AI_CONSUMER).count()),
            ("consumer_model_tpm(__all__)", db.session.query(ConsumerModelTpm).filter(ConsumerModelTpm.ai_consumer == GLOBAL_AI_CONSUMER).count()),
            ("customer_usage_hourly", db.session.query(CustomerUsageHourly).count()),
        ]:
            print(f"  {label:28} {q}")


if __name__ == "__main__":
    main()
