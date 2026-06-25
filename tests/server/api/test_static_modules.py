"""Static Web UI module wiring contracts."""

from pathlib import Path

from fastapi.testclient import TestClient

from server.main import app


STATIC_DIR = Path(__file__).resolve().parents[3] / "server" / "static"


def test_index_loads_api_job_device_and_dashboard_modules_before_inline_app():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    api_pos = html.index('src="/static/js/api.js"')
    jobs_pos = html.index('src="/static/js/jobs.js"')
    devices_pos = html.index('src="/static/js/devices.js"')
    dashboard_pos = html.index('src="/static/js/dashboard.js"')
    inline_app_pos = html.index("const API_BASE")
    assert api_pos < jobs_pos < devices_pos < dashboard_pos < inline_app_pos


def test_auth_view_reads_auth_status_before_submit_flow():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "/api/auth/status" in html
    assert 'id="auth-status-copy"' in html


def test_auth_view_formats_validation_errors_and_declares_password_constraints():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "function formatApiErrorDetail(detail)" in html
    assert "showToast(formatApiErrorDetail(data.detail)" in html
    assert 'id="auth-password"' in html
    assert 'minlength="8"' in html


def test_api_module_owns_fetch_wrappers():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    api_js = (STATIC_DIR / "js" / "api.js").read_text(encoding="utf-8")
    assert "async function apiFetchRaw" not in html
    assert "async function apiFetch" not in html
    assert "formatApiErrorDetail" in api_js
    assert "window.apiFetchRaw" in api_js
    assert "window.apiFetch" in api_js


def test_job_and_device_controllers_use_canonical_routes():
    jobs_js = (STATIC_DIR / "js" / "jobs.js").read_text(encoding="utf-8")
    devices_js = (STATIC_DIR / "js" / "devices.js").read_text(encoding="utf-8")
    assert "/api/jobs/${jobId}/cancel" in jobs_js
    assert "/api/jobs/${jobId}/devices" in jobs_js
    assert "/api/devices/${deviceId}/health" in devices_js
    assert "/api/devices/${deviceId}/screen/stream" in devices_js
    assert "/api/devices/${deviceId}/acceptance/dry-run" in devices_js
    assert "/api/devices/${deviceId}/acceptance/live-send" in devices_js


def test_index_does_not_repeat_authorized_status_copy():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "已授权授权" not in html


def test_favicon_request_is_handled():
    response = TestClient(app).get("/favicon.ico")
    assert response.status_code != 404


def test_dashboard_uses_mobile_drawer_navigation():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="dashboard-sidebar"' in html
    assert 'id="dashboard-sidebar-backdrop"' in html
    assert 'id="btn-sidebar-open"' in html
    assert "-translate-x-full lg:static lg:translate-x-0" in html
    assert 'aria-controls="dashboard-sidebar"' in html


def test_mobile_drawer_controls_are_wired():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "function setDashboardSidebarOpen(open)" in html
    assert "setDashboardSidebarOpen(true)" in html
    assert "setDashboardSidebarOpen(false)" in html


def test_index_uses_compiled_local_tailwind_css():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "cdn.tailwindcss.com" not in html
    assert 'href="/static/css/tailwind.css"' in html
    assert (STATIC_DIR / "css" / "tailwind.css").is_file()
