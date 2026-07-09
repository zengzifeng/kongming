"""DB → PolicyInputSnapshot 组装层：验证新增字段（实跑量4字段、列表价、采购折扣）确实从 DB 读出。"""
from datetime import timedelta

from app.algorithms.snapshot import build_snapshot
from app.extensions import db
from app.models import Demand, ModelListPrice, VendorQuota
from app.utils.time import utcnow


def _seed_demand():
    d = Demand(
        report_id="R-DBFIELDS",
        customer_id=None,
        model_name="GLM-5.2",
        expected_tpm=50_000_000,
        discount_rate=0.84,
        current_self_ratio=0.3,
        current_vendor_ratios={"tp-GLM-5.2": 0.7},
        input_ratio=50,
        cache_hit_rate=0.45,
    )
    db.session.add(d)
    db.session.flush()
    return d


def test_snapshot_reads_demand_runtime_fields_from_db(app):
    d = _seed_demand()
    snap = build_snapshot("realtime", [d])
    item = next(i for i in snap.demands if i.report_id == "R-DBFIELDS")
    # 四个实跑量字段来自 DB 列，而非 params 注入
    assert float(item.current_self_ratio) == 0.3
    assert item.current_vendor_ratios == {"tp-GLM-5.2": 0.7}
    assert float(item.input_ratio) == 50
    assert float(item.cache_hit_rate) == 0.45


def test_snapshot_reads_model_prices_from_db(app):
    d = _seed_demand()
    now = utcnow()
    db.session.add(ModelListPrice(
        model_name="GLM-5.2",
        input_cache_hit_price=0.000002,
        input_cache_miss_price=0.000008,
        output_price=0.000028,
        effective_from=now - timedelta(days=1),
    ))
    db.session.flush()

    snap = build_snapshot("realtime", [d])
    prices = snap.params["model_prices"]["GLM-5.2"]
    assert prices["input_cache_hit_price"] == 0.000002
    assert prices["input_cache_miss_price"] == 0.000008
    assert prices["output_price"] == 0.000028


def test_purchase_discount_direct_value_wins_over_derived(app):
    # vendor_quotas.purchase_discount 直值优先于 unit_cost/unit_price 导出
    from app.algorithms._shared import SolverEconomicsMixin
    m = SolverEconomicsMixin()
    # 导出会是 0.4；直值 0.75 应覆盖
    v = {"unit_cost": 0.0004, "unit_price": 0.0010, "purchase_discount": 0.75}
    assert m._purchase_discount(v) == 0.75
    # 直值缺省(<=0)时回退导出
    v2 = {"unit_cost": 0.0004, "unit_price": 0.0010, "purchase_discount": 0}
    assert abs(m._purchase_discount(v2) - 0.4) < 1e-9
