"""快速查看数据库内容。

用法（在 backend 目录下，用 venv 的 python）：

  # 打印概览（各表行数 + 时序跑量按客户汇总）
  .venv/Scripts/python.exe scripts/db_query.py

  # 执行任意 SQL
  .venv/Scripts/python.exe scripts/db_query.py "select * from customer_usage_hourly limit 5"
  .venv/Scripts/python.exe scripts/db_query.py "select model, sum(input_output) io from customer_usage_hourly group by model order by io desc"
"""
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

DB = Path(__file__).resolve().parent.parent / "instance" / "kongming.db"


def print_rows(cur):
    cols = [d[0] for d in cur.description] if cur.description else []
    rows = cur.fetchall()
    if cols:
        print(" | ".join(cols))
        print("-" * 60)
    for r in rows:
        print(" | ".join("" if v is None else str(v) for v in r))
    print(f"\n({len(rows)} 行)")


def overview(conn):
    print(f"数据库: {DB}\n")
    print("=== 各表行数 ===")
    tables = [r[0] for r in conn.execute(
        "select name from sqlite_master where type='table' order by name")]
    for t in tables:
        n = conn.execute(f'select count(*) from "{t}"').fetchone()[0]
        print(f"  {t:28} {n}")

    print("\n=== 时序跑量 customer_usage_hourly 按客户汇总 ===")
    q = """select c.customer_code, cu.customer_name, count(*) rows,
             round(sum(cu.input_output)/1e8,4) io_yi,
             min(cu.data_time), max(cu.data_time)
           from customer_usage_hourly cu
           join customers c on c.id = cu.customer_id
           group by c.customer_code, cu.customer_name
           order by rows desc"""
    print_rows(conn.execute(q))


def main():
    conn = sqlite3.connect(DB)
    try:
        if len(sys.argv) > 1:
            print_rows(conn.execute(sys.argv[1]))
        else:
            overview(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
