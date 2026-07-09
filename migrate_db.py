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


def run(config_name: str = "dev") -> None:
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

        print("迁移完成。")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "dev")
