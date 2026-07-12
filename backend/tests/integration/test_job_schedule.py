"""定时任务配置：列出 / 查询 / 改 enabled / 改 cron（DB 持久化，可被前端管理）。"""


def test_default_schedules_seeded(client):
    res = client.get("/api/v1/jobs")
    assert res.status_code == 200, res.json
    items = res.json["data"]
    names = {j["job_name"] for j in items}
    # 5 个既有任务 + 新增 policy_auto_run 都应被 seed。
    assert {
        "sync_filings_hourly",
        "revenue_after_snapshot",
        "customer_usage_daily",
        "weekly_report",
        "monthly_report",
        "policy_auto_run",
    } <= names


def test_policy_auto_run_defaults(client):
    res = client.get("/api/v1/jobs/policy_auto_run")
    assert res.status_code == 200, res.json
    job = res.json["data"]
    assert job["trigger_type"] == "cron"
    assert job["enabled"] is True
    assert job["args_json"]["algorithm"] == "time_period"


def test_patch_job_enabled_persists(client):
    res = client.patch("/api/v1/jobs/policy_auto_run", json={"enabled": False})
    assert res.status_code == 200, res.json
    assert res.json["data"]["enabled"] is False
    # 再查一次确认落库。
    res = client.get("/api/v1/jobs/policy_auto_run")
    assert res.json["data"]["enabled"] is False


def test_patch_job_cron_persists(client):
    res = client.patch("/api/v1/jobs/policy_auto_run",
                       json={"cron_expr": "0 3 * * *"})
    assert res.status_code == 200, res.json
    assert res.json["data"]["cron_expr"] == "0 3 * * *"


def test_patch_job_invalid_cron_rejected(client):
    res = client.patch("/api/v1/jobs/policy_auto_run",
                       json={"cron_expr": "not-a-cron"})
    assert res.status_code == 400, res.json


def test_patch_unknown_job_404(client):
    res = client.patch("/api/v1/jobs/does_not_exist", json={"enabled": False})
    assert res.status_code == 404, res.json


def test_switch_to_interval_requires_seconds(client):
    res = client.patch("/api/v1/jobs/policy_auto_run",
                       json={"trigger_type": "interval"})
    assert res.status_code == 400, res.json

    res = client.patch("/api/v1/jobs/policy_auto_run",
                       json={"trigger_type": "interval", "interval_seconds": 3600})
    assert res.status_code == 200, res.json
    assert res.json["data"]["trigger_type"] == "interval"
    assert res.json["data"]["interval_seconds"] == 3600
