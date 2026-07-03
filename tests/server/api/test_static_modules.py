"""Static Web UI module wiring contracts."""

from html.parser import HTMLParser
from pathlib import Path


STATIC_DIR = Path(__file__).resolve().parents[3] / "server" / "static"


class _ScriptTagParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[dict[str, str | None]] = []
        self._current_script: dict[str, str | None] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "script":
            return
        attr_map = dict(attrs)
        self._current_script = {"src": attr_map.get("src"), "content": ""}

    def handle_data(self, data: str) -> None:
        if self._current_script is None:
            return
        self._current_script["content"] = (self._current_script["content"] or "") + data

    def handle_endtag(self, tag: str) -> None:
        if tag != "script" or self._current_script is None:
            return
        self.scripts.append(self._current_script)
        self._current_script = None


def test_index_loads_api_job_device_and_dashboard_modules_before_inline_app():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    parser = _ScriptTagParser()
    parser.feed(html)

    bootstrap_index = next(
        index
        for index, script in enumerate(parser.scripts)
        if script["src"] is None and (script["content"] or "").strip()
    )
    module_srcs = [
        script["src"]
        for script in parser.scripts[:bootstrap_index]
        if script["src"] is not None
    ]

    assert module_srcs == [
        "/static/js/api.js",
        "/static/js/jobs.js",
        "/static/js/devices.js",
        "/static/js/dashboard.js",
    ]


def test_static_ui_uses_jobs_cancel_endpoint_only():
    """All visible cancel actions must use the canonical jobs API route."""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    jobs_js = (STATIC_DIR / "js" / "jobs.js").read_text(encoding="utf-8")

    assert "/api/tasks/status/${jobId}/cancel" not in html
    assert "/api/tasks/status/" not in html
    assert "/api/tasks/status/" not in jobs_js
    assert "/api/jobs/${jobId}/cancel" in jobs_js


def test_static_ui_renders_agent_trace_contract_fields():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    assert "renderAgentDecisionTrace" in html
    assert "latest_execution?.agent_decision" in html
    assert "latest_execution?.send_verification" in html
    assert "before_decision" in html
    assert "send_verification" in html


def test_static_ui_device_acceptance_uses_in_page_flow():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    assert 'id="modal-device-acceptance"' in html
    assert 'id="form-device-acceptance"' in html
    assert 'id="acceptance-industry"' in html
    assert 'id="acceptance-target"' in html
    assert 'id="acceptance-message"' in html
    assert 'id="acceptance-result"' in html
    assert "openDeviceAcceptanceModal" in html
    assert "submitDeviceAcceptance" in html
    assert "runDeviceAcceptance(id, liveSend)" in html
    assert "renderEvidenceScreenshotLink" in html
    assert "openEvidenceScreenshot" in html


def test_static_ui_device_acceptance_does_not_use_prompt_dialogs():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    acceptance_start = html.index("async function runDeviceAcceptance")
    acceptance_end = html.index("// Delete device", acceptance_start)
    acceptance_source = html[acceptance_start:acceptance_end]

    assert "prompt(" not in acceptance_source


def test_static_ui_job_evidence_drawer_contract():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    assert 'id="drawer-job-evidence"' in html
    assert 'id="job-evidence-title"' in html
    assert 'id="job-evidence-timeline"' in html
    assert "openJobEvidenceDrawer" in html
    assert "closeJobEvidenceDrawer" in html
    assert "renderJobEvidenceTimeline" in html
    assert "renderJobEvidenceLog" in html
    assert "/api/agent/execution-logs?job_id=" in html
