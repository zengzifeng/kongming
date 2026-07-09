"""录入「平台输入.xlsx」的 4 张 sheet 到对应主数据表，并清理 mock 数据。

映射：
  自建集群信息 -> cluster_resources     (ClusterResource)
  供应商信息   -> vendor_quotas         (VendorQuota)
  售卖         -> customer_sell_discounts(CustomerSellDiscount, 新表)
  列表价       -> model_list_prices      (ModelListPrice)

规则「入库前清空目标表 mock」：每张目标表先 DELETE 再插入（幂等，可重复运行）。
另按确认：清理 3 个 mock 客户(C0001-C0003) 及其依赖的 demands(71)/customer_usage_daily(47)。

用法（backend 目录下）：
    .venv/Scripts/python.exe scripts/ingest_platform_inputs.py [平台输入.xlsx]
"""
import sys
from datetime import date
from pathlib import Path

import openpyxl

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
REPO_ROOT = BACKEND_DIR.parent

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.utils.model_name import normalize_model_name  # noqa: E402
from app.models import (  # noqa: E402
    Customer,
    ClusterResource,
    VendorQuota,
    ModelListPrice,
    CustomerSellDiscount,
    Demand,
    CustomerUsageDaily,
)

PLATFORM_XLSX = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "平台输入.xlsx"

# 平台输入无日期字段，统一采用与实跑数据(2026-07-07)对齐的快照/生效日。
SNAPSHOT_DATE = date(2026, 7, 7)
MOCK_CUSTOMER_CODES = ("C0001", "C0002", "C0003")
# 自建集群「承接能力TPM」表内单位为「万 TPM」(wTPM)，入库统一换算为绝对 TPM。
WTPM = 10000


def _num(v):
    if v in (None, ""):
        return 0
    return float(v)


def read_sheet(wb, name):
    ws = wb[name]
    rows = list(ws.iter_rows(values_only=True))
    header = [str(h).strip() for h in rows[0]]
    out = []
    for r in rows[1:]:
        if all(v is None for v in r):
            continue
        out.append({header[i]: r[i] for i in range(len(header))})
    return out


def clear_mock_customers():
    """删除 3 个 mock 客户及其依赖明细（已确认全部为 mock）。"""
    mock = Customer.query.filter(Customer.customer_code.in_(MOCK_CUSTOMER_CODES)).all()
    ids = [c.id for c in mock]
    if not ids:
        print("[mock] 无 mock 客户可清理")
        return
    d = CustomerUsageDaily.query.filter(CustomerUsageDaily.customer_id.in_(ids)).delete(synchronize_session=False)
    dm = Demand.query.filter(Demand.customer_id.in_(ids)).delete(synchronize_session=False)
    for c in mock:
        db.session.delete(c)
    db.session.commit()
    print(f"[mock] 删除 mock 客户 {len(ids)} 个（{','.join(MOCK_CUSTOMER_CODES)}），"
          f"连带 demands {dm} 行、customer_usage_daily {d} 行")


def ingest_clusters(wb):
    ClusterResource.query.delete()
    rows = read_sheet(wb, "自建集群信息")
    for r in rows:
        db.session.add(ClusterResource(
            snapshot_date=SNAPSHOT_DATE,
            cluster_name=str(r["自建集群名称"]),
            deployed_model=normalize_model_name(r["部署模型名称"]),
            machine_count=int(_num(r["部署机器台数"])),
            # 承接能力单位为「万TPM」，换算为绝对 TPM 存库；原始 wTPM 值留档 raw_json。
            tpm_per_machine=_num(r["单台承接能力TPM"]) * WTPM,
            total_capacity_tpm=_num(r["总承接能力TPM"]) * WTPM,
            raw_json={
                "provider": r["provider"],
                "单台承接能力_wTPM": r["单台承接能力TPM"],
                "总承接能力_wTPM": r["总承接能力TPM"],
                "source": "平台输入.自建集群信息",
            },
        ))
    print(f"[cluster_resources] 清空 mock，写入 {len(rows)} 行")


def ingest_vendors(wb):
    VendorQuota.query.delete()
    rows = read_sheet(wb, "供应商信息")
    for r in rows:
        db.session.add(VendorQuota(
            vendor=str(r["provider"]),
            model=normalize_model_name(r["模型名称"]),
            # 供应商总量(W)：原值单位为「万」，转为绝对量存入 quota_tpm，原值留档 raw_json
            quota_tpm=_num(r["供应商总量(W)"]) * 10000,
            purchase_discount=_num(r["采购折扣"]),
            effective_from=SNAPSHOT_DATE,
            raw_json={"供应商总量_W": r["供应商总量(W)"], "source": "平台输入.供应商信息"},
        ))
    print(f"[vendor_quotas] 清空 mock，写入 {len(rows)} 行")


def ingest_list_prices(wb):
    ModelListPrice.query.delete()
    rows = read_sheet(wb, "列表价")
    for r in rows:
        db.session.add(ModelListPrice(
            model_name=normalize_model_name(r["模型名称"]),
            input_cache_hit_price=_num(r["输入命中列表价"]),
            input_cache_miss_price=_num(r["输入未命中列表价"]),
            output_price=_num(r["输出列表价"]),
            effective_from=SNAPSHOT_DATE,
        ))
    print(f"[model_list_prices] 清空 mock，写入 {len(rows)} 行")


def ingest_sell_discounts(wb):
    CustomerSellDiscount.query.delete()
    name_to_id = {c.name: c.id for c in Customer.query.all()}
    rows = read_sheet(wb, "售卖")
    written, missing = 0, []
    for r in rows:
        name = str(r["客户名称"]).strip()
        cid = name_to_id.get(name)
        if cid is None:
            missing.append(name)
            continue
        db.session.add(CustomerSellDiscount(
            customer_id=cid,
            customer_name=name,
            model_name=normalize_model_name(r["模型名称"]),
            sell_discount=_num(r["售卖折扣"]),
            effective_from=SNAPSHOT_DATE,
        ))
        written += 1
    print(f"[customer_sell_discounts] 清空 mock，写入 {written} 行"
          + (f"，跳过未匹配客户 {len(missing)}: {missing}" if missing else ""))


def main():
    print(f"平台输入: {PLATFORM_XLSX}")
    wb = openpyxl.load_workbook(PLATFORM_XLSX, data_only=True)
    app = create_app("dev")
    with app.app_context():
        db.create_all()  # 建新表 customer_sell_discounts
        clear_mock_customers()
        ingest_clusters(wb)
        ingest_vendors(wb)
        ingest_list_prices(wb)
        ingest_sell_discounts(wb)
        db.session.commit()
        print("\n[done] 各表现有行数：")
        for label, model in [
            ("cluster_resources", ClusterResource),
            ("vendor_quotas", VendorQuota),
            ("model_list_prices", ModelListPrice),
            ("customer_sell_discounts", CustomerSellDiscount),
            ("customers", Customer),
            ("demands", Demand),
            ("customer_usage_daily", CustomerUsageDaily),
        ]:
            print(f"  {label:26} {db.session.query(model).count()}")
    wb.close()


if __name__ == "__main__":
    main()
