"""usage_demand_source：验证从实跑量 + 售卖折扣构建 DemandSnapshotItem 的口径。"""
from datetime import datetime

from app.algorithms.usage_demand_source import build_usage_demand_items
from app.extensions import db
from app.models import Customer, CustomerSellDiscount, CustomerUsageHourly


def _usage(cust_id, model, dt, io, ti, ot, ct, cmt, source, provider):
    return CustomerUsageHourly(
        customer_id=cust_id, customer_name="c", user_id="u", key_id="k",
        data_time=dt, stat_date=dt.date(), phase="p0", model=model, provider=provider,
        model_source=source, data_source="生产",
        output_token=ot, cache_token=ct, cache_miss_token=cmt,
        total_input=ti, input_output=io, creation_cache_1h_token=0,
        creation_cache_5m_token=0, web_search_fc_count=0, av_duration=0,
    )


def _seed(app):
    signed = Customer(customer_code="C0100", name="签约客户", level="B")
    unsigned = Customer(customer_code="C0101", name="未签客户", level="B")
    db.session.add_all([signed, unsigned])
    db.session.flush()

    # 签约客户 glm-5.1：两小时序列，自建+第三方混合
    t0 = datetime(2026, 7, 7, 10, 0, 0)
    t1 = datetime(2026, 7, 7, 11, 0, 0)  # 最新小时
    db.session.add_all([
        # t0：自建 io=600, 第三方 io=400（total 1000）
        _usage(signed.id, "glm-5.1", t0, 600, 600, 100, 90, 10, "自建", "ksyun-glm5.1-qy-10056"),
        _usage(signed.id, "glm-5.1", t0, 400, 400, 100, 10, 90, "第三方", "thirdparty-baidu-ofb"),
        # t1（最新）：total io=1200 → expected_tpm=1200/60=20；自建 900、第三方 300
        _usage(signed.id, "glm-5.1", t1, 900, 900, 150, 0, 0, "自建", "ksyun-glm5.1-qy-10056"),
        _usage(signed.id, "glm-5.1", t1, 300, 300, 50, 0, 0, "第三方", "thirdparty-baidu-ofb"),
        # 未签客户 glm-5.2：单小时，纯第三方
        _usage(unsigned.id, "glm-5.2", t0, 6000, 6000, 60, 0, 0, "第三方", "thirdparty-ddfy-openai"),
    ])
    db.session.add(CustomerSellDiscount(
        customer_id=signed.id, customer_name="签约客户", model_name="glm-5.1",
        sell_discount=0.65, effective_from=t0.date(),
    ))
    db.session.flush()
    return signed, unsigned


def test_builds_one_item_per_customer_model(app):
    _seed(app)
    items = build_usage_demand_items()
    keys = {(i.customer_code, i.model_name) for i in items}
    assert keys == {("C0100", "glm-5.1"), ("C0101", "glm-5.2")}


def test_discount_backfill_signed_vs_default(app):
    _seed(app)
    items = {(i.customer_code, i.model_name): i for i in build_usage_demand_items()}
    assert items[("C0100", "glm-5.1")].discount_rate == 0.65   # 签约取真值
    assert items[("C0101", "glm-5.2")].discount_rate == 1.0    # 未签取默认


def test_expected_tpm_is_latest_hour(app):
    _seed(app)
    item = next(i for i in build_usage_demand_items() if i.customer_code == "C0100")
    # 最新小时 t1 total io=1200 → 1200/60 = 20
    assert item.expected_tpm == 20.0
    # tpm_series 两个点，升序
    assert [round(v, 4) for _, v in item.tpm_series] == [round(1000 / 60, 4), 20.0]


def test_ratios_match_hand_calc(app):
    _seed(app)
    item = next(i for i in build_usage_demand_items() if i.customer_code == "C0100")
    # 自建 io = 600+900=1500，总 io = 1000+1200=2200
    assert item.current_self_ratio == 1500 / 2200
    # 第三方 io = 400+300=700 全在 baidu
    assert item.current_vendor_ratios == {"thirdparty-baidu-ofb": 700 / 2200}
    # input_ratio = Σtotal_input/Σoutput = (600+400+900+300)/(100+100+150+50) = 2200/400
    assert item.input_ratio == 2200 / 400
    # cache_hit_rate = Σcache/(Σcache+Σmiss) = (90+10)/((90+10)+(10+90)) = 100/200
    assert item.cache_hit_rate == 0.5
