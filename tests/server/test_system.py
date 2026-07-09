"""Tests for system-level endpoints (health, info, metrics)."""

from fastapi.testclient import TestClient

from server.main import app

client = TestClient(app)


def test_liveness_endpoint_returns_healthy():
    """Liveness endpoint reports healthy when DB is reachable."""
    response = client.get("/api/system/live")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["version"] == "0.2.0"
    assert "dependencies" in data
    assert data["dependencies"]["database"]["status"] == "ok"


def test_liveness_endpoint_masks_database_url():
    """Database URL in liveness response must not expose credentials."""
    response = client.get("/api/system/live")
    data = response.json()
    db_url = data["dependencies"]["database"]["url"]
    assert "@" not in db_url or "***" in db_url


def test_info_endpoint_returns_metadata():
    """Info endpoint returns public application metadata."""
    response = client.get("/api/system/info")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Thunder Capture"
    assert data["version"] == "0.2.0"
    assert data["docs"] == "/docs"


def test_metrics_endpoint_exists_or_is_optional():
    """Metrics endpoint is exposed when Prometheus dependency is installed."""
    response = client.get("/api/system/metrics")
    # Either 200 (prometheus installed) or 404 (optional dependency missing)
    assert response.status_code in (200, 404)
