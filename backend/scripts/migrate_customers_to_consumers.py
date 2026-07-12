"""一次性迁移：把 customers 表合并进 monitor_consumers，并删除 customers 表。

背景：monitor_consumers 现作为客户主表 + kingress 采集清单。原 customers 表数据
（14 行左右）按 id 对齐灌入 monitor_consumers，保证 usage/sell_discount/demand 等
表的 customer_id 外键仍然指向正确记录（id 不变），随后删除 customers 表。

映射：customers.id -> monitor_consumers.id（保持一致）
      customers.name -> ai_consumer（= 客户名，唯一）+ customer_name
      customers.customer_code -> customer_code
      customers.level -> level
      enabled 默认 True

幂等：可重复运行——已存在同名/同 id 的 monitor_consumers 记录会跳过。

用法（backend 目录下）：
    python scripts/migrate_customers_to_consumers.py
"""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import text  # noqa: E402

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import MonitorConsumer  # noqa: E402


def _table_names() -> set[str]:
    rows = db.session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table'")
    ).scalars()
    return set(rows)


def _columns(table: str) -> set[str]:
    rows = db.session.execute(text(f"PRAGMA table_info({table})")).all()
    return {r[1] for r in rows}


def ensure_level_column():
    """monitor_consumers 若缺 level 列则补上（SQLite ADD COLUMN 需带默认值）。"""
    if "level" not in _columns("monitor_consumers"):
        db.session.execute(text(
            "ALTER TABLE monitor_consumers ADD COLUMN level VARCHAR(8) NOT NULL DEFAULT 'B'"
        ))
        db.session.commit()
        print("[schema] monitor_consumers 增加 level 列")
    else:
        print("[schema] monitor_consumers 已有 level 列，跳过")


def migrate_rows():
    tables = _table_names()
    if "customers" not in tables:
        print("[migrate] customers 表不存在，无需迁移")
        return

    customers = db.session.execute(text(
        "SELECT id, customer_code, name, level FROM customers ORDER BY id"
    )).all()
    if not customers:
        print("[migrate] customers 表为空，无数据迁移")
        return

    # 名称唯一性校验（ai_consumer 唯一约束）
    names = [c[2] for c in customers]
    dups = {n for n in names if names.count(n) > 1}
    if dups:
        raise SystemExit(f"[migrate] 客户名重复，无法作为 ai_consumer 唯一键：{dups}")

    existing_ids = set(db.session.execute(text(
        "SELECT id FROM monitor_consumers"
    )).scalars())
    existing_consumers = set(db.session.execute(text(
        "SELECT ai_consumer FROM monitor_consumers"
    )).scalars())

    inserted, skipped = 0, 0
    for cid, code, name, level in customers:
        if cid in existing_ids or name in existing_consumers:
            skipped += 1
            continue
        db.session.execute(text(
            "INSERT INTO monitor_consumers "
            "(id, ai_consumer, customer_code, customer_name, level, enabled, created_at, updated_at) "
            "VALUES (:id, :ac, :code, :cname, :level, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ), {"id": cid, "ac": name, "code": code, "cname": name, "level": level or "B"})
        inserted += 1
    db.session.commit()
    print(f"[migrate] customers -> monitor_consumers：插入 {inserted} 行，跳过 {skipped} 行")


def drop_customers():
    if "customers" in _table_names():
        db.session.execute(text("DROP TABLE customers"))
        db.session.commit()
        print("[drop] customers 表已删除")
    else:
        print("[drop] customers 表不存在，跳过")


def main():
    app = create_app("dev")
    with app.app_context():
        db.create_all()
        ensure_level_column()
        migrate_rows()
        drop_customers()
        total = db.session.query(MonitorConsumer).count()
        print(f"[done] monitor_consumers 现有 {total} 行")


if __name__ == "__main__":
    main()
