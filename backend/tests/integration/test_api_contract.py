def _post(client, url, payload=None):
    return client.post(url, json=payload or {})


def _prepare_policy(client):
    res = _post(client, "/api/v1/sync-batches/run", {"reason": "contract-test"})
    assert res.status_code == 202, res.json

    res = client.get("/api/v1/demands?status=pending")
    assert res.status_code == 200, res.json
    demands = res.json["data"]["items"]
    assert demands
    demand_id = demands[0]["id"]

    res = _post(client, f"/api/v1/demands/{demand_id}/evaluate", {})
    assert res.status_code == 201, res.json
    evaluation = res.json["data"]
    if evaluation["status"] == "pending":
        res = _post(
            client,
            f"/api/v1/evaluations/{evaluation['id']}/approve",
            {"operator": "tester", "comment": "contract"},
        )
        assert res.status_code == 200, res.json

    res = _post(client, "/api/v1/policy-runs", {"algorithm": "realtime", "demand_ids": [demand_id]})
    assert res.status_code == 202, res.json
    run_id = res.json["data"]["id"]

    res = client.get(f"/api/v1/policies?policy_run_id={run_id}")
    assert res.status_code == 200, res.json
    policies = res.json["data"]["items"]
    assert policies
    return run_id, policies[0]["id"]


def test_dashboard_operations_contract(client):
    res = client.get("/api/v1/dashboard/operations")
    assert res.status_code == 200, res.json
    data = res.json["data"]
    assert "pending_demands" in data
    assert "pending_evaluations" in data
    assert "draft_policies" in data
    assert "open_alerts" in data
    assert "revenue_last_24h" in data


def test_revenue_dashboard_contract(client):
    res = client.get("/api/v1/revenue/dashboard")
    assert res.status_code == 200, res.json
    data = res.json["data"]
    assert "generated_at" in data
    assert isinstance(data["idle"], list)
    assert isinstance(data["busy"], list)
    assert isinstance(data["peak_shaving"], list)


def test_watched_clusters_crud_contract(client):
    res = client.get("/api/v1/watched-clusters")
    assert res.status_code == 200, res.json
    items = res.json["data"]
    assert "DeepSeek-V3.2" in {item["cluster_name"] for item in items}

    res = client.post("/api/v1/watched-clusters", json={"cluster_name": "contract-cluster", "sort_order": 99})
    assert res.status_code == 201, res.json
    created = res.json["data"]
    assert created["cluster_name"] == "contract-cluster"
    assert created["enabled"] is True

    res = client.patch(f"/api/v1/watched-clusters/{created['id']}", json={"enabled": False})
    assert res.status_code == 200, res.json
    assert res.json["data"]["enabled"] is False

    res = client.get("/api/v1/watched-clusters")
    assert res.status_code == 200, res.json
    assert "contract-cluster" not in {item["cluster_name"] for item in res.json["data"]}

    res = client.get("/api/v1/watched-clusters?include_disabled=true")
    assert res.status_code == 200, res.json
    assert "contract-cluster" in {item["cluster_name"] for item in res.json["data"]}

    res = client.delete(f"/api/v1/watched-clusters/{created['id']}")
    assert res.status_code == 200, res.json


def test_dashboard_resources_contract(client):
    res = client.get("/api/v1/dashboard/resources?gpu_model=qwen&datacenter=bj")
    assert res.status_code == 200, res.json
    data = res.json["data"]
    assert "nodes" in data
    assert "clusters" in data
    assert "total_capacity_tpm" in data
    assert "total_available_tpm" in data
    assert "avg_utilization" in data
    if data["nodes"]:
        node = data["nodes"][0]
        assert "node_id" in node
        assert "gpu_model" in node
        assert "datacenter" in node
        assert "az" in node
        assert "capacity_tpm" in node
        assert "available_tpm" in node
        assert "utilization" in node
    if data["clusters"]:
        cluster = data["clusters"][0]
        assert "provider" in cluster
        assert "tpm_per_machine_w" in cluster
        assert "current_redundant_machines" in cluster
        assert "cluster_utilization" in cluster


def test_update_cluster_tpm_per_machine_recalculates_and_persists(client, app):
    from app.extensions import db
    from app.models import ClusterCapacity
    from tests.conftest import seed_cluster

    with app.app_context():
        # 监控给出台数=2、实跑=150万；单机能力由本接口录入。
        seed_cluster("db-glm", "db-glm", machine_count=2, tpm_per_machine=2_000_000,
                     current_tpm=1_500_000, provider="ksyun-glm")
        db.session.commit()

    res = client.patch("/api/v1/dashboard/resources/clusters", json={
        "cluster_name": "db-glm",
        "tpm_per_machine_w": 260,
    })
    assert res.status_code == 200, res.json
    data = res.json["data"]
    assert data["tpm_per_machine_w"] == 260
    assert data["total_capacity_w"] == 520        # 2 × 260
    assert data["current_redundant_w"] == 370      # 520 − 150
    assert data["current_redundant_machines"] == 1  # 370 // 260

    with app.app_context():
        row = db.session.query(ClusterCapacity).filter_by(cluster_name="db-glm").one()
        assert float(row.tpm_per_machine) == 2_600_000


def test_monitor_consumer_tpm_range_and_options_contract(client, app):
    from datetime import datetime

    from app.extensions import db
    from app.models import ConsumerModelTpm, MonitorBatch, MonitorBatchStatus

    with app.app_context():
        batch = MonitorBatch(
            batch_no="CONSUMER-TPM-RANGE",
            triggered_by="test",
            started_at=datetime(2026, 7, 7, 10, 0, 0),
            status=MonitorBatchStatus.SUCCESS,
        )
        db.session.add(batch)
        db.session.flush()
        for minute, tpm in ((0, 100), (5, 180)):
            db.session.add(ConsumerModelTpm(
                batch_id=batch.id,
                data_time=datetime(2026, 7, 7, 10, minute, 0),
                ai_consumer="consumer-a",
                customer_code="user-a",
                ai_model="model-a",
                tpm=tpm,
                self_ratio=0.7,
                thirdparty_ratio=0.3,
            ))
        db.session.commit()

    res = client.get("/api/v1/monitor/consumer-tpm?ai_consumer=consumer-a&ai_model=model-a")
    assert res.status_code == 200, res.json
    assert len(res.json["data"]["items"]) == 1
    assert float(res.json["data"]["items"][0]["tpm"]) == 180

    res = client.get(
        "/api/v1/monitor/consumer-tpm?"
        "start_time=2026-07-07T10:00:00&end_time=2026-07-07T10:05:00&"
        "ai_consumer=consumer-a&ai_model=model-a&customer_code=user-a"
    )
    assert res.status_code == 200, res.json
    items = res.json["data"]["items"]
    assert len(items) == 2
    assert [float(item["tpm"]) for item in items] == [100, 180]

    res = client.get("/api/v1/monitor/consumer-tpm/options")
    assert res.status_code == 200, res.json
    assert "model-a" in res.json["data"]["ai_models"]
    assert "consumer-a" in res.json["data"]["ai_consumers"]
    assert "user-a" in res.json["data"]["customer_codes"]


def test_dashboard_management_contract(client):
    res = client.get("/api/v1/dashboard/management?range=7d")
    assert res.status_code == 200, res.json
    data = res.json["data"]
    assert "platform_revenue_delta" in data
    assert "policy_adoption_rate" in data
    assert data["range"] == "7d"
    assert "generated_at" in data
    assert "current" in data["revenue"]
    assert "current" in data["cost"]
    assert "current" in data["margin"]
    assert isinstance(data["strategy_contribution"], list)
    assert isinstance(data["trend"], list)


def test_dashboard_customers_contract(client):
    _post(client, "/api/v1/sync-batches/run", {"reason": "contract-test"})
    res = client.get("/api/v1/dashboard/customers")
    assert res.status_code == 200, res.json
    data = res.json["data"]
    assert "customer_id" in data
    assert "demand_count" in data
    assert "active_models" in data
    assert "expected_tpm" in data
    assert "expected_revenue" in data
    assert "fulfillment" in data
    assert "recent_demands" in data
    assert "items" in data


def test_reports_contract(client):
    for url in ("/api/v1/reports/weekly", "/api/v1/reports/monthly"):
        res = client.get(url)
        assert res.status_code == 200, res.json
        data = res.json["data"]
        assert "kind" in data
        assert "label" in data
        assert "range" in data
        assert "new_demands" in data
        assert "new_policies" in data
        assert "revenue_delta" in data
        assert "period" in data
        assert "generated_at" in data
        assert "summary" in data
        assert "highlights" in data
        assert "charts" in data
        assert "new_demands" in data["summary"]
        assert "demand_status" in data["charts"]
        assert "policy_gain_by_algorithm" in data["charts"]


def test_policy_snapshot_contract(client):
    run_id, _ = _prepare_policy(client)
    res = client.get(f"/api/v1/policy-runs/{run_id}/snapshot")
    assert res.status_code == 200, res.json
    data = res.json["data"]
    assert "input_snapshot" in data
    assert "input_hash" in data
    assert "run" in data
    assert "demands" in data
    assert "resources" in data
    assert "constraints" in data


def test_policy_revenue_contract(client):
    _, policy_id = _prepare_policy(client)
    res = client.get(f"/api/v1/revenue/policies/{policy_id}")
    assert res.status_code == 200, res.json
    data = res.json["data"]
    assert data["policy_id"] == policy_id
    assert "policy" in data
    assert "snapshots" in data
    assert "attributions" in data
    assert "analysis" in data
