"""策略状态机 + 审计：patch/accept/cancel/recalculate 各留审计，状态守卫收敛为 draft/accepted/cancelled。"""


def _post(client, url, payload=None):
    return client.post(url, json=payload or {})


def _make_draft_policy(client):
    res = _post(client, "/api/v1/sync-batches/run", {"reason": "audit-test"})
    assert res.status_code == 202, res.json

    res = client.get("/api/v1/demands?status=pending")
    demands = res.json["data"]["items"]
    assert demands
    demand_id = demands[0]["id"]

    res = _post(client, f"/api/v1/demands/{demand_id}/evaluate", {})
    assert res.status_code == 201, res.json
    evaluation = res.json["data"]
    if evaluation["status"] == "pending":
        _post(client, f"/api/v1/evaluations/{evaluation['id']}/approve",
              {"operator": "tester", "comment": "ok"})

    res = _post(client, "/api/v1/policy-runs",
                {"algorithm": "realtime", "demand_ids": [demand_id]})
    assert res.status_code == 202, res.json
    run_id = res.json["data"]["id"]

    res = client.get(f"/api/v1/policies?policy_run_id={run_id}")
    policies = res.json["data"]["items"]
    assert policies, "策略运行未产出 DRAFT 策略"
    return policies[0]["id"]


def _audit_actions(client, policy_id):
    res = client.get(f"/api/v1/policies/{policy_id}/audit-logs")
    assert res.status_code == 200, res.json
    return [x["action"] for x in res.json["data"]]


def test_patch_only_on_draft_and_audited(client):
    pid = _make_draft_policy(client)
    res = client.patch(f"/api/v1/policies/{pid}",
                       json={"operator": "alice", "expected_revenue_gain": 123.45})
    assert res.status_code == 200, res.json
    assert "patch" in _audit_actions(client, pid)


def test_accept_audited_and_stores_comment(client):
    pid = _make_draft_policy(client)
    res = _post(client, f"/api/v1/policies/{pid}/accept",
                {"operator": "bob", "comment": "上线"})
    assert res.status_code == 200, res.json
    assert res.json["data"]["status"] == "accepted"
    assert res.json["data"]["accepted_by"] == "bob"

    res = client.get(f"/api/v1/policies/{pid}/audit-logs")
    accept_logs = [x for x in res.json["data"] if x["action"] == "accept"]
    assert accept_logs and accept_logs[0]["comment"] == "上线"


def test_patch_rejected_after_accept(client):
    pid = _make_draft_policy(client)
    _post(client, f"/api/v1/policies/{pid}/accept", {"operator": "bob"})
    # 已采纳不可再改数（避免生效策略被静默修改）。
    res = client.patch(f"/api/v1/policies/{pid}",
                       json={"operator": "bob", "expected_revenue_gain": 999})
    assert res.status_code == 409, res.json


def test_cancel_audited(client):
    pid = _make_draft_policy(client)
    res = _post(client, f"/api/v1/policies/{pid}/cancel",
                {"operator": "carol", "reason": "不采纳"})
    assert res.status_code == 200, res.json
    assert res.json["data"]["status"] == "cancelled"
    assert "cancel" in _audit_actions(client, pid)


def test_recalculate_keeps_old_draft(client):
    pid = _make_draft_policy(client)
    res = _post(client, f"/api/v1/policies/{pid}/recalculate", {"operator": "dave"})
    assert res.status_code == 200, res.json

    # 旧策略保持 DRAFT（是否取消由人工另行触发）。
    res = client.get(f"/api/v1/policies/{pid}")
    assert res.json["data"]["policy"]["status"] == "draft"
    assert "recalculate" in _audit_actions(client, pid)
