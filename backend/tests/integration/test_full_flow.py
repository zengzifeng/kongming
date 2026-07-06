"""端到端冒烟：sync → evaluate → approve → policy run → accept。"""


def _post(client, url, payload=None):
    return client.post(url, json=payload or {})


def test_full_flow(client, app):
    res = _post(client, "/api/v1/sync-batches/run", {"reason": "test"})
    assert res.status_code == 202, res.json
    batch = res.json["data"]
    assert batch["status"] in ("success", "running", "partial")

    res = client.get("/api/v1/demands?status=pending")
    assert res.status_code == 200
    items = res.json["data"]["items"]
    assert items, "mock 同步未产出任何需求"

    demand_id = items[0]["id"]
    res = _post(client, f"/api/v1/demands/{demand_id}/evaluate", {})
    assert res.status_code == 201, res.json
    evaluation = res.json["data"]
    eval_id = evaluation["id"]

    if evaluation["status"] == "pending":
        res = _post(client, f"/api/v1/evaluations/{eval_id}/approve",
                    {"operator": "tester", "comment": "ok"})
        assert res.status_code == 200, res.json

    res = client.get(f"/api/v1/demands/{demand_id}")
    assert res.json["data"]["demand"]["status"] in ("approved", "scheduled")

    res = _post(client, "/api/v1/policy-runs",
                {"algorithm": "realtime", "demand_ids": [demand_id]})
    assert res.status_code == 202, res.json
    run = res.json["data"]
    assert run["status"] in ("success", "failed", "running")

    res = client.get(f"/api/v1/policy-runs?status=success")
    if res.json["data"]["items"]:
        run_id = res.json["data"]["items"][0]["id"]
        res = client.get(f"/api/v1/policies?policy_run_id={run_id}")
        policies = res.json["data"]["items"]
        if policies:
            pid = policies[0]["id"]
            res = _post(client, f"/api/v1/policies/{pid}/accept", {"operator": "tester"})
            assert res.status_code == 200, res.json
