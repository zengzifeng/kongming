"""资源模型监控采集：解析信封 + mock 采集入库 + consumer 维护 + 最新快照查询。"""


def _post(client, url, payload=None):
    return client.post(url, json=payload or {})


def test_parse_envelope_handles_null_series():
    from app.integrations.resource_monitor_client import parse_envelope
    env = {
        "code": 0, "message": "success",
        "data": {"start_time": "2026-01-01 00:00:00", "end_time": "2026-01-01 00:01:00",
                 "metrics": [
                     {"name": "kingress_model_tpm", "label": "x", "series": None},
                     {"name": "token_node_count", "label": "y", "series": [
                         {"labels": {"inference_model": "DeepSeek-V3.2"},
                          "values": [{"time": "2026-01-01 00:00:00", "value": 9}]}]},
                 ]}}
    parsed = parse_envelope(env)
    assert parsed.series_of("kingress_model_tpm") == []          # null -> 空列表
    assert len(parsed.series_of("token_node_count")) == 1
    assert parsed.series_of("token_node_count")[0].latest() == 9


def test_collect_persists_cluster_and_consumer(client, app):
    # 先加一个 consumer，才会拉 kingress 侧。
    res = _post(client, "/api/v1/monitor/consumers",
                {"ai_consumer": "acme", "customer_code": "C0001", "customer_name": "Acme"})
    assert res.status_code == 201, res.json

    res = _post(client, "/api/v1/monitor/collect", {})
    assert res.status_code == 202, res.json
    batch = res.json["data"]
    assert batch["status"] in ("success", "partial")
    assert batch["cluster_rows"] > 0      # token 侧集群瞬时行
    assert batch["consumer_rows"] > 0     # kingress 侧客户瞬时行
    assert batch["consumers_total"] == 1
    assert batch["consumers_ok"] == 1


def test_cluster_tpm_unit_restored_to_raw(client, app):
    _post(client, "/api/v1/monitor/consumers", {"ai_consumer": "acme", "customer_code": "C0001"})
    _post(client, "/api/v1/monitor/collect", {})
    res = client.get("/api/v1/monitor/cluster-tpm")
    assert res.status_code == 200, res.json
    items = res.json["data"]["items"]
    assert items
    ds = [x for x in items if x["cluster_name"] == "DeepSeek-V3.2"]
    assert ds, "缺 DeepSeek-V3.2 集群行"
    # mock 中 token_cluster_tpm 最新值 1464(万) -> 还原为 14,640,000 TPM
    assert float(ds[0]["tpm"]) == 1464 * 10000


def test_consumer_tpm_carries_ratios(client, app):
    _post(client, "/api/v1/monitor/consumers", {"ai_consumer": "acme", "customer_code": "C0001"})
    _post(client, "/api/v1/monitor/collect", {})
    res = client.get("/api/v1/monitor/consumer-tpm?ai_consumer=acme")
    assert res.status_code == 200, res.json
    items = res.json["data"]["items"]
    assert items
    row = items[0]
    assert row["ai_model"] == "deepseek-v3.2"
    assert row["customer_code"] == "C0001"
    assert float(row["self_ratio"]) > 0          # kingress_ksyun_ratio
    assert float(row["thirdparty_ratio"]) > 0     # kingress_thirdparty_ratio


def test_consumer_lifecycle_add_disable_reenable(client, app):
    # 新增（customer_code 为自然主键，必填）
    res = _post(client, "/api/v1/monitor/consumers", {"ai_consumer": "beta", "customer_code": "CBETA"})
    assert res.status_code == 201, res.json
    # 软删（停采）—— 按 customer_code 删除
    res = client.delete("/api/v1/monitor/consumers/CBETA")
    assert res.status_code == 200, res.json
    res = client.get("/api/v1/monitor/consumers?enabled=true")
    assert "CBETA" not in {c["customer_code"] for c in res.json["data"]}
    # 需求回归：再次新增 -> 幂等复用并重新启用
    res = _post(client, "/api/v1/monitor/consumers", {"ai_consumer": "beta", "customer_code": "CBETA"})
    assert res.status_code == 201, res.json
    assert res.json["data"]["enabled"] is True
    res = client.get("/api/v1/monitor/consumers?enabled=true")
    assert "CBETA" in {c["customer_code"] for c in res.json["data"]}


def test_collect_without_consumers_still_gets_clusters(client, app):
    # 无 enabled consumer 时：token 产能 + kingress 全局(__all__)仍应采集成功。
    res = _post(client, "/api/v1/monitor/collect", {})
    assert res.status_code == 202, res.json
    batch = res.json["data"]
    assert batch["cluster_rows"] > 0
    assert batch["consumer_rows"] > 0          # kingress 全局 __all__ 汇总
    assert batch["consumers_total"] == 0        # 无逐客户计划
    assert batch["status"] == "success"
    # 应存在 ai_consumer='__all__' 的全局汇总行
    snap = client.get("/api/v1/monitor/consumer-tpm?ai_consumer=__all__").json["data"]
    assert snap["items"], "缺 __all__ 全局汇总行"


def test_monitor_job_seeded(client):
    res = client.get("/api/v1/jobs/resource_monitor_collect")
    assert res.status_code == 200, res.json
    assert res.json["data"]["trigger_type"] == "cron"


def test_collect_writes_all_global_and_per_consumer(client, app):
    # 带 customer_code 的客户：__all__ 全局汇总 + 该逐客户两套行都落库。
    _post(client, "/api/v1/monitor/consumers", {"ai_consumer": "acme", "customer_code": "C0001"})
    _post(client, "/api/v1/monitor/collect", {})
    all_rows = client.get("/api/v1/monitor/consumer-tpm?ai_consumer=__all__").json["data"]["items"]
    acme_rows = client.get("/api/v1/monitor/consumer-tpm?ai_consumer=acme").json["data"]["items"]
    assert all_rows, "缺 __all__ 全局汇总行"
    assert acme_rows, "缺逐客户行"
    assert all(r["customer_code"] == "__all__" for r in all_rows)  # __all__ 行 customer_code="__all__"
    assert all(r["customer_code"] == "C0001" for r in acme_rows)


def test_consumer_create_requires_customer_code(client, app):
    # customer_code(user_id) 现为必填自然主键：缺失应被校验拒绝（400 pydantic 校验），不再静默建档/跳过。
    res = _post(client, "/api/v1/monitor/consumers", {"ai_consumer": "noCode"})
    assert res.status_code == 400
