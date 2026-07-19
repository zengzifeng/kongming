"""为所有「客户+模型」生成 闲时/忙时 拟合数据（demo 策略）。

客户+模型 universe = customer_usage_hourly 中有跑量、且客户在 monitor_consumers 且有
customer_code 的组合（__all__ 无 customer_code，跳过）。对每个组合 upsert busy/idle 两条
demo 配置，然后跑一次 run_fitting 产出客户级 + 集群级波形。

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
from app.models import CustomerUsageHourly, MonitorConsumer, WavePeriod  # noqa: E402
from app.services import WaveFittingService  # noqa: E402

ALGO = "demo"
GLOBAL_AI_CONSUMER = "__all__"


def consumer_model_pairs():
    """有跑量的 (customer_code, model) 组合；排除 __all__（全局汇总，非单客户）。

    per-user_id 粒度：customer_code(user_id) 为客户标识，同一 ai_consumer 多 uid 各算一组。
    """
    rows = db.session.query(
        distinct(MonitorConsumer.customer_code), CustomerUsageHourly.model
    ).join(
        MonitorConsumer, MonitorConsumer.id == CustomerUsageHourly.customer_id
    ).filter(MonitorConsumer.customer_code != GLOBAL_AI_CONSUMER).all()
    return sorted(set(rows))


def main():
    app = create_app("dev")
    with app.app_context():
        svc = WaveFittingService()
        pairs = consumer_model_pairs()
        print(f"客户(customer_code)+模型组合 {len(pairs)} 个，各生成 忙时/闲时 demo 配置")
        for customer_code, model in pairs:
            for period in (WavePeriod.BUSY, WavePeriod.IDLE):
                svc.upsert_config({
                    "customer_code": customer_code,
                    "model_name": model,
                    "period": period,
                    "algo_name": ALGO,
                })
        print(f"[config] upsert 完成：{len(pairs) * 2} 条配置")

        result = svc.run_fitting()
        print(f"[run_fitting] {result}")


if __name__ == "__main__":
    main()
