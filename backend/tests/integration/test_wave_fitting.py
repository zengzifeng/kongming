"""波形拟合模块：算法目录只读、客户关联配置增改、跑拟合产出客户+集群波形、开关接入求解。"""
from datetime import datetime

from app.extensions import db
from app.models import CustomerSellDiscount, MonitorConsumer, CustomerUsageHourly, ProviderMapping
from tests.conftest import seed_cluster



def _usage(cust_id, model, dt, io):
    return CustomerUsageHourly(
        customer_id=cust_id, customer_name="c", user_id="u",
        data_time=dt, stat_date=dt.date(), model=model, provider="prov",
        model_source="自建", data_source="生产",
        output_token=0, cache_token=0, cache_miss_token=0,
        total_input=0, input_output=io,
    )


def _seed_usage(app):
    cust = MonitorConsumer(ai_consumer="客户A", customer_code="C0200", customer_name="客户A", level="B")
    db.session.add(cust)
    db.session.flush()
    # 忙时点（10 点，io=1200 -> tpm 20）与闲时点（3 点，io=600 -> tpm 10）
    db.session.add_all([
        _usage(cust.id, "glm-5.1", datetime(2026, 7, 7, 10, 0, 0), 1200),
        _usage(cust.id, "glm-5.1", datetime(2026, 7, 7, 3, 0, 0), 600),
    ])
    # 部署 glm-5.1 的集群（集群名=部署模型名），供集群级叠加波形。
    seed_cluster("glm-5.1", "glm-5.1", machine_count=10, tpm_per_machine=1_000_000)
    db.session.flush()
    return cust


# ---- 算法目录只读 ----
def test_default_algorithm_seeded(client):
    res = client.get("/api/v1/fittings/algorithms")
    assert res.status_code == 200, res.json
    names = {a["algo_name"] for a in res.json["data"]}
    assert "demo" in names
    demo = next(a for a in res.json["data"] if a["algo_name"] == "demo")
    assert demo["entry_ref"] == "demo"
    assert demo["enabled"] is True


def test_algorithms_readonly_no_post_route(client):
    # 目录不提供写接口：POST 到 algorithms 应 404/405，不可通过 API 新增算法。
    res = client.post("/api/v1/fittings/algorithms", json={"algo_name": "x"})
    assert res.status_code in (404, 405), res.json


# ---- 客户关联配置增改查 ----
def test_config_create_and_list(client):
    payload = {"customer_code": "C0200", "model_name": "glm-5.1",
               "period": "busy", "algo_name": "demo",
               "params_json": {"delta_tpm": 5.0}}
    res = client.post("/api/v1/fittings/configs", json=payload)
    assert res.status_code == 200, res.json
    cfg_id = res.json["data"]["id"]

    res = client.get("/api/v1/fittings/configs?customer_code=C0200")
    assert res.status_code == 200
    assert len(res.json["data"]) == 1
    assert res.json["data"][0]["id"] == cfg_id


def test_config_upsert_is_idempotent_on_consumer_model(client):
    payload = {"customer_code": "C0200", "model_name": "glm-5.1",
               "period": "busy", "algo_name": "demo"}
    r1 = client.post("/api/v1/fittings/configs", json=payload)
    r2 = client.post("/api/v1/fittings/configs",
                     json={**payload, "period": "idle", "params_json": {"delta_tpm": 9.0}})
    assert r1.json["data"]["id"] == r2.json["data"]["id"]  # 同客户+模型，更新非新增
    assert r2.json["data"]["params_json"]["delta_tpm"] == 9.0

    res = client.get("/api/v1/fittings/configs?customer_code=C0200")
    assert res.status_code == 200
    assert len(res.json["data"]) == 1


def test_config_patch(client):
    payload = {"customer_code": "C0200", "model_name": "glm-5.1",
               "period": "idle", "algo_name": "demo"}
    cfg_id = client.post("/api/v1/fittings/configs", json=payload).json["data"]["id"]
    res = client.patch(f"/api/v1/fittings/configs/{cfg_id}", json={"enabled": False})
    assert res.status_code == 200
    assert res.json["data"]["enabled"] is False


def test_config_rejects_unknown_algo(client):
    res = client.post("/api/v1/fittings/configs", json={
        "customer_code": "C0200", "model_name": "glm-5.1",
        "period": "busy", "algo_name": "does-not-exist"})
    assert res.status_code == 400, res.json


def test_config_rejects_bad_period(client):
    res = client.post("/api/v1/fittings/configs", json={
        "customer_code": "C0200", "model_name": "glm-5.1",
        "period": "midday", "algo_name": "demo"})
    assert res.status_code == 400, res.json


# ---- 跑拟合：客户波形 + 集群叠加 ----
def test_run_fitting_produces_customer_and_cluster_results(client, app):
    _seed_usage(app)
    client.post("/api/v1/fittings/configs", json={
        "customer_code": "C0200", "model_name": "glm-5.1",
        "period": "busy", "algo_name": "demo"})

    res = client.post("/api/v1/fittings/run")
    assert res.status_code == 200, res.json
    summary = res.json["data"]
    assert summary["customer_results"] == 2     # busy + idle 各一条客户波形
    assert summary["cluster_results"] == 2      # 每时段一条集群波形（1 个集群部署该模型）

    # 客户级忙时波形：前一天同点平移，tpm 保持 20
    res = client.get("/api/v1/fittings/results?level=customer&period=busy")
    series = res.json["data"]["items"][0]["series_json"]
    assert series and series[0][1] == 20.0

    # 集群级叠加存在
    res = client.get("/api/v1/fittings/results?level=cluster")
    assert res.json["data"]["total"] == 2


def test_results_restrict_to_sell_discount_filters_and_names(client, app):

    cust = _seed_usage(app)
    other = MonitorConsumer(ai_consumer="客户B", customer_code="C0300",
                            customer_name="客户B", level="B")
    db.session.add(other)
    db.session.flush()
    db.session.add(_usage(other.id, "glm-5.1", datetime(2026, 7, 7, 10, 0, 0), 1800))
    db.session.add(CustomerSellDiscount(
        customer_id=cust.id, customer_name="客户A", model_name="glm-5.1",
        sell_discount=0.65, effective_from=datetime(2026, 7, 1).date(),
    ))
    db.session.add(ProviderMapping(
        customer_name="客户A", model_name="glm-5.1", provider="prov", cluster_name="glm-5.1",
    ))
    db.session.flush()

    for code in ("C0200", "C0300"):
        client.post("/api/v1/fittings/configs", json={
            "customer_code": code, "model_name": "glm-5.1",
            "period": "busy", "algo_name": "demo"})
    client.post("/api/v1/fittings/run")

    res = client.get("/api/v1/fittings/results?level=customer&period=busy")
    assert res.json["data"]["total"] == 2

    res = client.get("/api/v1/fittings/results?level=customer&period=busy&restrict_to_sell_discount=true")
    assert res.status_code == 200, res.json
    items = res.json["data"]["items"]
    assert [item["customer_code"] for item in items] == ["C0200"]
    assert items[0]["ai_consumer"] == "客户A"
    assert items[0]["customer_name"] == "客户A"
    assert items[0]["cluster_name"] == "glm-5.1"


def test_run_fitting_delta_applied(client, app):
    _seed_usage(app)

    client.post("/api/v1/fittings/configs", json={
        "customer_code": "C0200", "model_name": "glm-5.1",
        "period": "busy", "algo_name": "demo", "params_json": {"delta_tpm": 6.0}})
    client.post("/api/v1/fittings/run")
    res = client.get("/api/v1/fittings/results?level=customer&period=busy")
    series = res.json["data"]["items"][0]["series_json"]
    # 忙时单点，delta 6 全摊到该点：20 + 6 = 26
    assert series[0][1] == 26.0


def test_build_fitted_series_merges_periods(app):
    from app.services import WaveFittingService

    _seed_usage(app)
    svc = WaveFittingService()
    svc.upsert_config({"customer_code": "C0200", "model_name": "glm-5.1",
                       "period": "busy", "algo_name": "demo"})
    svc.run_fitting()
    merged = svc.build_fitted_series("C0200", "glm-5.1")
    # 闲时(3点 tpm10) + 忙时(10点 tpm20) 合并为两点整段序列
    assert len(merged) == 2
    tpms = sorted(t for _, t in merged)
    assert tpms == [10.0, 20.0]
