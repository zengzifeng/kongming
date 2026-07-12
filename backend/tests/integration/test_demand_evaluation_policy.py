def _post(client, url, payload=None):
    return client.post(url, json=payload or {})


def _prepare_pending_demand(client):
    res = _post(client, "/api/v1/sync-batches/run", {"reason": "demand-evaluation-policy"})
    assert res.status_code == 202, res.json
    res = client.get("/api/v1/demands?status=pending")
    assert res.status_code == 200, res.json
    demands = res.json["data"]["items"]
    assert demands
    return demands[0]["id"]


def test_evaluating_demand_generates_policy_and_accept_updates_demand(client):
    demand_id = _prepare_pending_demand(client)

    res = _post(client, f"/api/v1/demands/{demand_id}/evaluate", {})
    assert res.status_code == 201, res.json
    evaluation = res.json["data"]

    # 评估生成后需求进入待审批态，且详情接口应回填其产出策略（一个需求对应一条策略）。
    res = client.get(f"/api/v1/demands/{demand_id}")
    assert res.status_code == 200, res.json
    assert res.json["data"]["demand"]["status"] == "awaiting_approval"
    assert res.json["data"]["policy"] is not None

    res = client.get("/api/v1/policies?algorithm=demand_evaluation")
    assert res.status_code == 200, res.json
    policy = res.json["data"]["items"][0]
    assert policy["summary_json"]["demand_id"] == demand_id
    assert policy["summary_json"]["evaluation_id"] == evaluation["id"]
    assert "feasibility_score" in policy["summary_json"]
    assert "expected_margin" in policy["summary_json"]

    res = _post(client, f"/api/v1/policies/{policy['id']}/accept", {
        "operator": "tester",
        "comment": "confirm demand plan",
    })
    assert res.status_code == 200, res.json

    res = client.get(f"/api/v1/demands/{demand_id}")
    assert res.status_code == 200, res.json
    assert res.json["data"]["demand"]["status"] == "approved"
    assert res.json["data"]["latest_evaluation"]["status"] == "approved"


def test_cancel_demand_evaluation_policy_rejects_demand(client):
    demand_id = _prepare_pending_demand(client)

    res = _post(client, f"/api/v1/demands/{demand_id}/evaluate", {})
    assert res.status_code == 201, res.json

    res = client.get("/api/v1/policies?algorithm=demand_evaluation")
    assert res.status_code == 200, res.json
    policy = res.json["data"]["items"][0]

    res = _post(client, f"/api/v1/policies/{policy['id']}/cancel", {
        "operator": "tester",
        "reason": "reject demand plan",
    })
    assert res.status_code == 200, res.json

    res = client.get(f"/api/v1/demands/{demand_id}")
    assert res.status_code == 200, res.json
    assert res.json["data"]["demand"]["status"] == "rejected"
    assert res.json["data"]["latest_evaluation"]["status"] == "rejected"
