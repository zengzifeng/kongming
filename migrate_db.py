# -*- coding: utf-8 -*-
"""增量迁移脚本（无 Alembic，配合 create_all 机制）。

做两件事，均幂等、可重复执行、不动已有数据：
  1. create_all()：为「新增的模型表」（model_list_prices）建表；已存在的表不受影响。
  2. ALTER TABLE ADD COLUMN：给已存在的表补新列（create_all 不会给旧表补列）。
     先用 PRAGMA table_info 查重，已存在的列跳过。

用法：  python migrate_db.py [config_name]   # config_name 缺省 dev
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import text  # noqa: E402

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402

# 表 -> [(列名, 列定义SQL)]。列定义含类型与默认值，SQLite ADD COLUMN 要求默认值为常量。
NEW_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "demands": [
        ("current_self_ratio", "NUMERIC(6, 4) NOT NULL DEFAULT 0"),
        ("current_vendor_ratios", "JSON DEFAULT '{}'"),
        ("input_ratio", "NUMERIC(10, 4) NOT NULL DEFAULT 1.0"),
        ("cache_hit_rate", "NUMERIC(6, 4) NOT NULL DEFAULT 0"),
    ],
    "vendor_quotas": [
        ("actual_tpm", "NUMERIC(18, 2) NOT NULL DEFAULT 0"),
        ("actual_redundant_tpm", "NUMERIC(18, 2) NOT NULL DEFAULT 0"),
        ("purchase_discount", "NUMERIC(6, 4) NOT NULL DEFAULT 0"),
    ],
    "cluster_resources": [
        ("current_redundant_machines", "INTEGER NOT NULL DEFAULT 0"),
    ],
    "policies": [
        ("demand_id", "INTEGER"),
    ],
    "watched_clusters": [
        ("deployed_model", "VARCHAR(64)"),
    ],
}


# 重点集群 -> 部署模型 映射（小写规范形，与需求/客户跑量的 model_name 一致）。
# 拟合叠加按此把「模型级叠加波形」归属到对应集群。仅回填 deployed_model 为空的行，
# 不覆盖人工已设置的值；若该集群尚未在 watched_clusters，则补一条。
WATCHED_DEPLOYED_MODEL_MAP: dict[str, str] = {
    "DeepSeek-V3.2": "deepseek-v3.2",
    "GLM-5.1-FP8": "glm-5.1",
    "GLM-5.1-KSCC": "glm-5.1",
    "GLM-5.1-XISHANJU": "glm-5.1",
    "GLM-5.2": "glm-5.2",
    "GLM-5.2-Tencent": "glm-5.2",
    "GLM-5.2-KSCC": "glm-5.2",
    "Kimi-K2.5-NVFP4-MIHAYOU": "kimi-k2.5",
    "Kimi-K2.6-MIHAYOU": "kimi-k2.6",
}


def _existing_columns(conn, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {r[1] for r in rows}


def _table_exists(conn, table: str) -> bool:
    row = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t"),
        {"t": table},
    ).fetchone()
    return row is not None


def _index_exists(conn, index: str) -> bool:
    row = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='index' AND name=:i"),
        {"i": index},
    ).fetchone()
    return row is not None


def _dedupe_customer_fitting_configs(conn) -> None:
    if not _table_exists(conn, "customer_fitting_configs"):
        return
    # 列名已由 ai_consumer 改为 customer_code（per-user_id 改造）；旧库可能仍是 ai_consumer，兼容两种。
    cols = _existing_columns(conn, "customer_fitting_configs")
    key_col = "customer_code" if "customer_code" in cols else "ai_consumer"
    result = conn.execute(text(f"""
        DELETE FROM customer_fitting_configs
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM customer_fitting_configs
            GROUP BY {key_col}, model_name
        )
    """))
    print(f"[dedupe] customer_fitting_configs 删除重复行 {result.rowcount} 条。")

    index_name = "uq_customer_fitting_natural_key"
    if _index_exists(conn, index_name):
        print(f"[skip] 索引 {index_name} 已存在。")
        return
    conn.execute(text(
        f"CREATE UNIQUE INDEX {index_name} "
        f"ON customer_fitting_configs ({key_col}, model_name)"
    ))
    print(f"[index] 已创建唯一索引 {index_name}。")


def _backfill_watched_deployed_model(conn) -> None:
    """回填 watched_clusters.deployed_model：仅填空值、补缺失集群，幂等。"""
    if not _table_exists(conn, "watched_clusters"):
        print("[skip] watched_clusters 表不存在，跳过部署模型回填。")
        return
    have = _existing_columns(conn, "watched_clusters")
    if "deployed_model" not in have:
        print("[skip] watched_clusters.deployed_model 列尚未创建，跳过回填。")
        return
    updated = 0
    for name, dm in WATCHED_DEPLOYED_MODEL_MAP.items():
        res = conn.execute(text(
            "UPDATE watched_clusters SET deployed_model = :dm "
            "WHERE lower(cluster_name) = lower(:name) AND deployed_model IS NULL"
        ), {"dm": dm, "name": name})
        updated += res.rowcount or 0
        exists = conn.execute(text(
            "SELECT 1 FROM watched_clusters WHERE lower(cluster_name) = lower(:name)"
        ), {"name": name}).fetchone()
        if not exists:
            next_order = conn.execute(text(
                "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM watched_clusters"
            )).scalar()
            conn.execute(text(
                "INSERT INTO watched_clusters "
                "(cluster_name, enabled, sort_order, deployed_model, created_at, updated_at) "
                "VALUES (:name, 1, :order, :dm, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ), {"name": name, "order": next_order, "dm": dm})
            print(f"[add ] watched_clusters 新增 {name}（部署模型 {dm}，sort_order {next_order}）")
    print(f"[backfill] watched_clusters.deployed_model 回填 {updated} 行。")


def _pre_alter_watched_deployed_model(config_name: str) -> None:
    """create_app 会触发 ensure_default_watched_clusters 查询 WatchedCluster（含新列），
    必须先用裸连接把 deployed_model 列建出来，否则 create_app 即崩。仅 sqlite 文件库需要。"""
    import sqlite3
    from app.config import CONFIG_MAP
    uri = CONFIG_MAP[config_name].SQLALCHEMY_DATABASE_URI
    if not uri.startswith("sqlite:///"):
        return
    db_path = uri[len("sqlite:///"):]
    if db_path == ":memory:":
        return
    con = sqlite3.connect(db_path)
    try:
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        if "watched_clusters" not in tables:
            return
        cols = {r[1] for r in con.execute("PRAGMA table_info(watched_clusters)").fetchall()}
        if "deployed_model" in cols:
            return
        con.execute("ALTER TABLE watched_clusters ADD COLUMN deployed_model VARCHAR(64)")
        con.commit()
        print(f"[pre ] watched_clusters.deployed_model 已预建（create_app 前）。")
    finally:
        con.close()


def run(config_name: str = "dev") -> None:
    _pre_alter_watched_deployed_model(config_name)
    app = create_app(config_name)
    with app.app_context():
        # 1. 建缺失的新表（model_list_prices 等）
        db.create_all()
        print("[create_all] 已确保所有模型表存在（新表已建）。")

        # 2. 给已有表补新列
        with db.engine.begin() as conn:
            for table, cols in NEW_COLUMNS.items():
                if not _table_exists(conn, table):
                    print(f"[skip] 表 {table} 不存在（create_all 已按模型新建，无需补列）。")
                    continue
                have = _existing_columns(conn, table)
                for name, ddl in cols:
                    if name in have:
                        print(f"[skip] {table}.{name} 已存在。")
                        continue
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                    print(f"[add ] {table}.{name}  ->  {ddl}")
            _dedupe_customer_fitting_configs(conn)
            _backfill_watched_deployed_model(conn)

        print("迁移完成。")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "dev")
