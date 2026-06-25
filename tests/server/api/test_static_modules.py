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
