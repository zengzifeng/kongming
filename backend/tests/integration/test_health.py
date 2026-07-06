def test_healthz(client):
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json["data"]["status"] == "ok"


def test_readyz(client):
    res = client.get("/readyz")
    assert res.status_code == 200
    assert res.json["data"]["ready"] is True
