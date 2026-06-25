"""Static Web UI module wiring contracts."""

from pathlib import Path


STATIC_DIR = Path(__file__).resolve().parents[3] / "server" / "static"


def test_index_loads_api_job_device_and_dashboard_modules_before_inline_app():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    api_pos = html.index('src="/static/js/api.js"')
    jobs_pos = html.index('src="/static/js/jobs.js"')
    devices_pos = html.index('src="/static/js/devices.js"')
    dashboard_pos = html.index('src="/static/js/dashboard.js"')
    inline_app_pos = html.index("const API_BASE")
    assert api_pos < jobs_pos < devices_pos < dashboard_pos < inline_app_pos
