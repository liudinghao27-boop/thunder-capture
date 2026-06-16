from fastapi.testclient import TestClient
from server.main import app

client = TestClient(app)


def test_effect_stats_requires_auth():
    resp = client.get("/api/stats/effects?industry_slug=recruitment")
    assert resp.status_code in (401, 403)
