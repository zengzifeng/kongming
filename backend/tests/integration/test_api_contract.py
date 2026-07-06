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
