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
    from app.models import ClusterResource
    from app.utils.time import utcnow

    with app.app_context():
        db.session.add(ClusterResource(
            snapshot_date=utcnow().date(),
            cluster_name="db-glm",
            deployed_model="GLM-5.2",
            machine_count=2,
            tpm_per_machine=2_000_000,
            total_capacity_tpm=4_000_000,
            current_tpm=1_500_000,
            current_redundant_tpm=2_500_000,
            current_redundant_machines=1,
            raw_json={"provider": "ksyun-glm"},
        ))
        db.session.commit()

    res = client.patch("/api/v1/dashboard/resources/clusters", json={
        "cluster_name": "db-glm",
        "deployed_model": "GLM-5.2",
        "tpm_per_machine_w": 260,
    })
    assert res.status_code == 200, res.json
    data = res.json["data"]
    assert data["tpm_per_machine_w"] == 260
    assert data["total_capacity_w"] == 520
    assert data["current_redundant_w"] == 370
    assert data["current_redundant_machines"] == 1

    with app.app_context():
        row = db.session.query(ClusterResource).filter_by(cluster_name="db-glm", deployed_model="GLM-5.2").one()
        assert float(row.tpm_per_machine) == 2_600_000
        assert float(row.total_capacity_tpm) == 5_200_000
        assert float(row.current_redundant_tpm) == 3_700_000
        assert row.current_redundant_machines == 1
        assert row.raw_json["单台承接能力_wTPM"] == 260


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
