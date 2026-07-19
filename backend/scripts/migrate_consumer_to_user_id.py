# -*- coding: utf-8 -*-
"""一次性结构迁移：monitor_consumers 改为 per-user_id(customer_code 唯一) 粒度。

背景：customer_code(user_id) 成为自然主键（UNIQUE NOT NULL），ai_consumer(客户名) 去 unique，
一行 = (ai_consumer, customer_code)，一个客户名可对应多个 user_id。配套 consumer_model_tpm
唯一键加 customer_code、customer_fitting_configs/fitting_results 的 ai_consumer 列改 customer_code。

SQLite 无 Alembic、不能 ALTER 改唯一约束/主键，故对受影响的 4 张表 DROP + 让 create_all 按新模型
重建；对仅数据失效（无结构变化）的依赖表清空行。保留 customer_sell_discounts 原样（同客户名下
uid 折扣相同，不重关联；FK 未强制，悬空无害）。

清空范围（用户已确认「清空重建」）：
  - DROP + 重建（结构变了）：monitor_consumers、consumer_model_tpm、customer_fitting_configs、fitting_results
  - 清空行（结构不变，customer_id 会悬空/为派生数据）：demands、customer_usage_hourly、
    customer_usage_daily、policies、policy_runs、policy_actions、policy_audit_logs
  - 保留不动：customer_sell_discounts、watched_clusters、fitting_algorithms、job_schedules、
    provider_mappings、monitor_batches、cluster_model_tpm、gpu_node_count 等

幂等可重复执行；执行前自动备份 instance/kongming.db。

用法（backend 目录下）：
    python scripts/migrate_consumer_to_user_id.py [config_name]   # 缺省 dev
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from sqlalchemy import text

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import CONFIG_MAP, DevConfig  # noqa: E402


class MigrateCfg(DevConfig):
    SCHEDULER_ENABLED = False
    USAGE_HOURLY_AGGREGATE_ENABLED = False
    RESOURCE_MONITOR_MODE = "mock"


# 受结构变更影响、需 DROP 后由 create_all 重建的表（按新模型定义）。
REBUILD_TABLES = [
    "fitting_results",
    "customer_fitting_configs",
    "consumer_model_tpm",
    "monitor_consumers",
]
# 仅清空行（结构不变）的依赖/派生表。
CLEAR_TABLES = [
    "policy_audit_logs",
    "policy_actions",
    "policies",
    "policy_runs",
    "demands",
    "customer_usage_hourly",
    "customer_usage_daily",
]


def _db_path(config_name: str) -> Path | None:
    uri = CONFIG_MAP[config_name].SQLALCHEMY_DATABASE_URI
    if not uri.startswith("sqlite:///") or uri.endswith(":memory:"):
        return None
    return Path(uri[len("sqlite:///"):]).resolve()


def _table_exists(conn, table: str) -> bool:
    return conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t"),
        {"t": table},
    ).fetchone() is not None


def run(config_name: str = "dev") -> None:
    CONFIG_MAP.setdefault("migrate_consumer", MigrateCfg)
    cfg_name = "migrate_consumer" if config_name == "dev" else config_name

    db_path = _db_path(cfg_name)
    if db_path:
        if not db_path.exists():
            raise SystemExit(f"数据库不存在: {db_path}")
        bak = db_path.with_suffix(".db.bak_before_user_id")
        shutil.copy2(db_path, bak)
        print(f"[backup] {db_path} -> {bak}")

    from app import create_app  # noqa: E402
    from app.extensions import db  # noqa: E402

    app = create_app(cfg_name)  # create_all 首次跑：旧表已存在则不动
    with app.app_context():
        # 1) 清空依赖表行 + DROP 受结构变更影响的表（单独事务，先提交）
        with db.engine.begin() as conn:
            for t in CLEAR_TABLES:
                if _table_exists(conn, t):
                    n = conn.execute(text(f"DELETE FROM {t}")).rowcount
                    print(f"[clear] {t}: 删除 {n} 行")
            for t in REBUILD_TABLES:
                if _table_exists(conn, t):
                    conn.execute(text(f"DROP TABLE {t}"))
                    print(f"[drop ] {t}")
        # 2) 重建被 DROP 的表（按新模型约束）；须在 DROP 事务提交后另起，否则 create_all 见表仍在而不建。
        db.create_all()
        print("[create_all] 已重建受影响表（新约束）")
        # 3) 验证新约束
        with db.engine.begin() as conn:
            cols = {r[1] for r in conn.execute(text("PRAGMA table_info(monitor_consumers)")).fetchall()}
            idx = {r[1] for r in conn.execute(text("PRAGMA index_list(monitor_consumers)")).fetchall()}
            print(f"[verify] monitor_consumers 列: {sorted(cols)}")
            print(f"[verify] monitor_consumers 索引: {sorted(idx)}")
        print("迁移完成。")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "dev")
