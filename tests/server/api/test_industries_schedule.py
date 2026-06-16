from fastapi.testclient import TestClient
from server.main import app

client = TestClient(app)


def test_update_schedule_config_requires_auth():
    resp = client.put("/api/industries/ind-1/schedule-config", json={"pause_weekends": True})
    assert resp.status_code in (401, 403)


def test_start_schedule_requires_auth():
    resp = client.post("/api/industries/ind-1/schedule/start")
    assert resp.status_code in (401, 403)
