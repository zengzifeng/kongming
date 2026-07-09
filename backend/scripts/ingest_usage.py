"""一次性录入脚本：将「模型计量使用量明细」中、平台售卖名单内客户的时序跑量
录入数据库。

- 客户：按客户名 upsert 到 customers 表（不存在则新建，分配递增 customer_code）
- 跑量：写入 customer_usage_hourly（时序跑量明细），按自然键幂等去重

用法（在 backend 目录下）：
    .venv/Scripts/python.exe scripts/ingest_usage.py [路径/明细.xlsx] [路径/平台输入.xlsx]

默认从仓库根目录读取两个 xlsx。
"""
import sys
from datetime import datetime, date
from pathlib import Path

import openpyxl

# 允许以脚本方式运行时导入 app 包
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
REPO_ROOT = BACKEND_DIR.parent

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.utils.model_name import normalize_model_name  # noqa: E402
from app.models import Customer, CustomerUsageHourly  # noqa: E402

DETAIL_XLSX = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "副本模型计量使用量明细_20260709_232212.xlsx"
PLATFORM_XLSX = Path(sys.argv[2]) if len(sys.argv) > 2 else REPO_ROOT / "平台输入.xlsx"


def _to_int(v):
    if v in (None, ""):
        return 0
    try:
        return int(v)
    except (TypeError, ValueError):
        return int(float(v))


def _to_dt(v):
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    return datetime.strptime(str(v).strip(), "%Y-%m-%d %H:%M:%S")


def _to_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return datetime.strptime(str(v).strip(), "%Y-%m-%d").date()


def load_platform_customers(path: Path) -> set[str]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["售卖"]
    names = {
        row[1].strip()
        for row in ws.iter_rows(min_row=2, values_only=True)
        if row[1]  # 客户名称
    }
    wb.close()
    return names


def load_detail_rows(path: Path, keep_customers: set[str]) -> list[dict]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["Sheet2"]
    header = [str(h) for h in next(ws.iter_rows(values_only=True))]
    idx = {h: i for i, h in enumerate(header)}
    rows = []
    for r in ws.iter_rows(min_row=2, values_only=True):
        name = r[idx["客户名"]]
        if name is None or name.strip() not in keep_customers:
            continue
        rows.append(
            dict(
                customer_name=name.strip(),
                user_id=str(r[idx["用户ID"]]),
                key_id=str(r[idx["key_id"]]),
                data_time=_to_dt(r[idx["数据时间"]]),
                stat_date=_to_date(r[idx["日期"]]),
                phase=str(r[idx["阶段"]]),
                model=normalize_model_name(r[idx["模型"]]),
                provider=str(r[idx["provider"]]),
                model_source=r[idx["模型来源"]],
                data_source=r[idx["数据来源"]],
                output_token=_to_int(r[idx["outputToken"]]),
                cache_token=_to_int(r[idx["cacheToken"]]),
                cache_miss_token=_to_int(r[idx["cacheMissToken"]]),
                total_input=_to_int(r[idx["总输入"]]),
                input_output=_to_int(r[idx["输入+输出"]]),
                creation_cache_1h_token=_to_int(r[idx["creationCache1hToken"]]),
                creation_cache_5m_token=_to_int(r[idx["creationCache5mToken"]]),
                web_search_fc_count=_to_int(r[idx["webSearchFcCount"]]),
                av_duration=r[idx["音视频时长"]] or 0,
                status=r[idx["状态"]],
                account_type=r[idx["账户类型"]],
                department=r[idx["部门"]],
                business_owner=r[idx["商务负责人"]],
                industry=r[idx["行业"]],
            )
        )
    wb.close()
    return rows


def upsert_customers(names: set[str]) -> dict[str, int]:
    """按客户名 upsert，返回 {客户名: customer_id}。为新客户分配递增 customer_code。"""
    existing = {c.name: c for c in Customer.query.all()}
    # 计算下一个数字编码
    max_num = 0
    for code in (c.customer_code for c in existing.values()):
        if code and code.startswith("C") and code[1:].isdigit():
            max_num = max(max_num, int(code[1:]))
    name_to_id: dict[str, int] = {}
    created = 0
    for name in sorted(names):
        cust = existing.get(name)
        if cust is None:
            max_num += 1
            cust = Customer(customer_code=f"C{max_num:04d}", name=name, level="B")
            db.session.add(cust)
            db.session.flush()  # 取 id
            created += 1
        name_to_id[name] = cust.id
    db.session.commit()
    print(f"[customers] 命中 {len(names)} 个平台客户；新建 {created} 个，复用 {len(names) - created} 个")
    return name_to_id


def ingest_usage(rows: list[dict], name_to_id: dict[str, int]) -> None:
    # 已存在自然键（幂等）
    existing_keys = set(
        db.session.query(
            CustomerUsageHourly.customer_id,
            CustomerUsageHourly.user_id,
            CustomerUsageHourly.key_id,
            CustomerUsageHourly.data_time,
            CustomerUsageHourly.stat_date,
            CustomerUsageHourly.model,
            CustomerUsageHourly.provider,
            CustomerUsageHourly.phase,
        ).all()
    )
    to_add, skipped = [], 0
    for row in rows:
        cid = name_to_id[row["customer_name"]]
        nk = (cid, row["user_id"], row["key_id"], row["data_time"], row["stat_date"], row["model"], row["provider"], row["phase"])
        if nk in existing_keys:
            skipped += 1
            continue
        existing_keys.add(nk)
        to_add.append(CustomerUsageHourly(customer_id=cid, **row))
    db.session.bulk_save_objects(to_add)
    db.session.commit()
    print(f"[usage] 待录入 {len(rows)} 行：新增 {len(to_add)}，跳过已存在 {skipped}")


def main():
    print(f"明细文件 : {DETAIL_XLSX}")
    print(f"平台输入 : {PLATFORM_XLSX}")
    keep = load_platform_customers(PLATFORM_XLSX)
    rows = load_detail_rows(DETAIL_XLSX, keep)
    print(f"[filter] 平台客户 {len(keep)} 个；匹配明细 {len(rows)} 行")

    app = create_app("dev")
    with app.app_context():
        db.create_all()  # 确保新表 customer_usage_hourly 建立
        name_to_id = upsert_customers(keep)
        ingest_usage(rows, name_to_id)
        total = db.session.query(CustomerUsageHourly).count()
        print(f"[done] customer_usage_hourly 现有总行数：{total}")


if __name__ == "__main__":
    main()
