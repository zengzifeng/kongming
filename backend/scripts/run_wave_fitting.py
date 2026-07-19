"""为 customer_sell_discounts 表内出现过的「客户+模型」生成 闲时/忙时 拟合数据（demo 策略）。

客户+模型 universe = customer_usage_hourly 中有跑量、客户在 monitor_consumers 且有
customer_code（__all__ 无 customer_code，跳过）、**且该 (客户,模型) 出现在
customer_sell_discounts 表**的组合。只对这些组合 upsert busy/idle 两条 demo 配置；同时把
不在该白名单内的历史启用配置停用（enabled=False），确保 run_fitting 只拟合这些组合。

用法（backend 目录下）：
    python scripts/run_wave_fitting.py
"""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import distinct  # noqa: E402

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import (  # noqa: E402
    CustomerFittingConfig,
    CustomerSellDiscount,
    CustomerUsageHourly,
    FitLevel,
    FittingResult,
    MonitorConsumer,
    WavePeriod,
)
from app.services import WaveFittingService  # noqa: E402

ALGO = "demo"
GLOBAL_AI_CONSUMER = "__all__"


def sell_discount_pairs() -> set[tuple[str, str]]:
    """customer_sell_discounts 表内的 (customer_code, model_name) 全集（经 monitor_consumers 取 code）。"""
    rows = db.session.query(
        MonitorConsumer.customer_code, CustomerSellDiscount.model_name
    ).join(
        MonitorConsumer, MonitorConsumer.id == CustomerSellDiscount.customer_id
    ).filter(MonitorConsumer.customer_code != GLOBAL_AI_CONSUMER).all()
    return set(rows)


def consumer_model_pairs():
    """有跑量、且出现在 customer_sell_discounts 表里的 (customer_code, model) 组合；排除 __all__。

    per-user_id 粒度：customer_code(user_id) 为客户标识，同一 ai_consumer 多 uid 各算一组。
    只保留售卖折扣表内出现过的 (客户,模型)——与 time_period 策略需求 universe 口径一致。
    """
    rows = db.session.query(
        distinct(MonitorConsumer.customer_code), CustomerUsageHourly.model
    ).join(
        MonitorConsumer, MonitorConsumer.id == CustomerUsageHourly.customer_id
    ).join(
        CustomerSellDiscount,
        db.and_(
            CustomerSellDiscount.customer_id == CustomerUsageHourly.customer_id,
            CustomerSellDiscount.model_name == CustomerUsageHourly.model,
        ),
    ).filter(MonitorConsumer.customer_code != GLOBAL_AI_CONSUMER).all()
    return sorted(set(rows))


def disable_stale_configs(allowed_pairs: set[tuple[str, str]]) -> int:
    """把不在售卖折扣白名单内的启用配置停用，使 run_fitting 只拟合白名单组合。"""
    disabled = 0
    for cfg in db.session.execute(
        db.select(CustomerFittingConfig).where(CustomerFittingConfig.enabled.is_(True))
    ).scalars():
        if (cfg.customer_code, cfg.model_name) not in allowed_pairs:
            cfg.enabled = False
            disabled += 1
    if disabled:
        db.session.commit()
    return disabled


def purge_foreign_fitting_results(sd_pairs: set[tuple[str, str]]) -> dict[str, int]:
    """删除不属于 customer_sell_discounts 的历史拟合结果。

    - 客户级(FitLevel.CUSTOMER)：(customer_code, model_name) 不在售卖折扣表内的删除；
    - 集群级(FitLevel.CLUSTER)：model_name 不在售卖折扣表模型集合内的删除（集群级为按模型叠加）。
    """
    sd_models = {m for _, m in sd_pairs}
    removed_customer = 0
    removed_cluster = 0
    for r in db.session.execute(db.select(FittingResult)).scalars():
        if r.level == FitLevel.CUSTOMER:
            if (r.customer_code, r.model_name) not in sd_pairs:
                db.session.delete(r)
                removed_customer += 1
        elif r.level == FitLevel.CLUSTER:
            if r.model_name not in sd_models:
                db.session.delete(r)
                removed_cluster += 1
    if removed_customer or removed_cluster:
        db.session.commit()
    return {"customer": removed_customer, "cluster": removed_cluster}


def main():
    app = create_app("dev")
    with app.app_context():
        svc = WaveFittingService()
        pairs = consumer_model_pairs()
        print(f"客户(customer_code)+模型组合 {len(pairs)} 个（售卖折扣表内），各生成 忙时/闲时 demo 配置")
        for customer_code, model in pairs:
            for period in (WavePeriod.BUSY, WavePeriod.IDLE):
                svc.upsert_config({
                    "customer_code": customer_code,
                    "model_name": model,
                    "period": period,
                    "algo_name": ALGO,
                    "enabled": True,  # 显式重新启用：避免历史被 disable 的配置在本轮仍被跳过
                })
        print(f"[config] upsert 完成：{len(pairs) * 2} 条配置")

        disabled = disable_stale_configs(set(pairs))
        print(f"[config] 停用白名单外历史配置：{disabled} 条")

        result = svc.run_fitting()
        print(f"[run_fitting] {result}")

        # 清掉不在 customer_sell_discounts 里的历史拟合记录（客户级 + 集群级）
        purged = purge_foreign_fitting_results(sell_discount_pairs())
        print(f"[purge] 删除表外拟合记录：客户级={purged['customer']} 集群级={purged['cluster']}")


if __name__ == "__main__":
    main()
