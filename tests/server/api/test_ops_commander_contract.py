from html.parser import HTMLParser
from pathlib import Path


STATIC_DIR = Path(__file__).resolve().parents[3] / "server" / "static"


class _OpsCommanderShellParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.primary_nav_labels: dict[str, str] = {}
        self.ids: set[str] = set()
        self.inline_scripts: list[str] = []
        self._in_dashboard_sidebar = False
        self._dashboard_sidebar_depth = 0
        self._in_primary_nav = False
        self._primary_nav_depth = 0
        self._current_nav_key: str | None = None
        self._current_nav_text: list[str] = []
        self._in_nav_label_span = False
        self._nav_label_span_depth = 0
        self._in_script = False
        self._script_chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        tag_id = attr_map.get("id")
        if tag_id:
            self.ids.add(tag_id)

        if tag == "aside" and tag_id == "dashboard-sidebar":
            self._in_dashboard_sidebar = True
            self._dashboard_sidebar_depth = 1
            return
        if tag == "aside" and self._in_dashboard_sidebar:
            self._dashboard_sidebar_depth += 1

        if tag == "nav" and self._in_dashboard_sidebar and not self._in_primary_nav:
            self._in_primary_nav = True
            self._primary_nav_depth = 1
            return
        if tag == "nav" and self._in_primary_nav:
            self._primary_nav_depth += 1

        if tag == "button" and self._in_primary_nav and attr_map.get("data-nav"):
            self._current_nav_key = attr_map["data-nav"]
            self._current_nav_text = []

        if tag == "span" and self._current_nav_key is not None and not self._in_nav_label_span:
            self._in_nav_label_span = True
            self._nav_label_span_depth = 1
            return
        if tag == "span" and self._in_nav_label_span:
            self._nav_label_span_depth += 1

        if tag == "script" and attr_map.get("src") is None:
            self._in_script = True
            self._script_chunks = []

    def handle_data(self, data: str) -> None:
        if self._in_nav_label_span:
            self._current_nav_text.append(data)
        if self._in_script:
            self._script_chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "button" and self._current_nav_key is not None:
            self.primary_nav_labels[self._current_nav_key] = "".join(self._current_nav_text).strip()
            self._current_nav_key = None
            self._current_nav_text = []
            return

        if tag == "span" and self._in_nav_label_span:
            self._nav_label_span_depth -= 1
            if self._nav_label_span_depth == 0:
                self._in_nav_label_span = False

        if tag == "nav" and self._in_primary_nav:
            self._primary_nav_depth -= 1
            if self._primary_nav_depth == 0:
                self._in_primary_nav = False

        if tag == "aside" and self._in_dashboard_sidebar:
            self._dashboard_sidebar_depth -= 1
            if self._dashboard_sidebar_depth == 0:
                self._in_dashboard_sidebar = False

        if tag == "script" and self._in_script:
            self.inline_scripts.append("".join(self._script_chunks))
            self._in_script = False
            self._script_chunks = []


def _html() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


def _parse_shell() -> _OpsCommanderShellParser:
    parser = _OpsCommanderShellParser()
    parser.feed(_html())
    return parser


def test_primary_navigation_uses_business_labels():
    shell = _parse_shell()
    expected_labels = {
        "overview": "首页总览",
        "industries": "项目中心",
        "devices": "设备中心",
        "tasks": "线索中心",
        "jobs": "任务中心",
        "settings": "系统设置",
    }
    actual_labels = {
        nav_key: shell.primary_nav_labels.get(nav_key)
        for nav_key in expected_labels
    }
    assert actual_labels == expected_labels


def test_overview_uses_single_primary_action():
    shell = _parse_shell()
    assert "overview-primary-action" in shell.ids
    assert "overview-btn-collect" not in shell.ids
    assert "overview-btn-send" not in shell.ids


def test_onboarding_modal_is_removed_from_shell():
    shell = _parse_shell()
    assert "modal-onboarding" not in shell.ids
    assert not any("startOnboarding(" in script for script in shell.inline_scripts)
