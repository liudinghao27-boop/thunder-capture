"""Contracts relied on by the same-origin Web UI."""

import pytest

from server.main import app


REQUIRED_ROUTES = {
    ("GET", "/api/auth/status"),
    ("GET", "/api/auth/me"),
    ("GET", "/api/dashboard/state"),
    ("GET", "/api/devices"),
    ("POST", "/api/devices/{device_id}/acceptance/dry-run"),
    ("POST", "/api/devices/{device_id}/acceptance/live-send"),
    ("GET", "/api/agent/execution-logs"),
    ("GET", "/api/industries"),
    ("GET", "/api/jobs"),
    ("GET", "/api/jobs/{job_id}"),
    ("GET", "/api/jobs/{job_id}/devices"),
    ("POST", "/api/jobs/collect/start"),
    ("POST", "/api/jobs/send/start"),
    ("POST", "/api/jobs/{job_id}/cancel"),
    ("GET", "/api/leads"),
    ("POST", "/api/leads/retry-failed"),
}

STRUCTURED_RESPONSE_ROUTES = {
    ("GET", "/api/auth/status"),
    ("GET", "/api/dashboard/state"),
    ("GET", "/api/agent/execution-logs"),
    ("GET", "/api/jobs/{job_id}"),
    ("GET", "/api/jobs/{job_id}/devices"),
    ("POST", "/api/jobs/collect/start"),
    ("POST", "/api/jobs/send/start"),
    ("POST", "/api/jobs/{job_id}/cancel"),
    ("GET", "/api/leads"),
}


def _openapi_operations():
    return {
        (method.upper(), path): operation
        for path, path_item in app.openapi()["paths"].items()
        for method, operation in path_item.items()
    }


@pytest.mark.contract
def test_required_frontend_routes_exist():
    assert REQUIRED_ROUTES <= set(_openapi_operations())


@pytest.mark.contract
def test_core_ui_routes_publish_response_models():
    operations = _openapi_operations()
    missing = [
        f"{method} {path}"
        for method, path in sorted(STRUCTURED_RESPONSE_ROUTES)
        if not operations[(method, path)]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
    ]
    assert missing == []
