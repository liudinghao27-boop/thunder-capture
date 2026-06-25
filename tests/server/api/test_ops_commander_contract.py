from pathlib import Path


STATIC_DIR = Path(__file__).resolve().parents[3] / "server" / "static"


def _html() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


def test_primary_navigation_uses_business_labels():
    html = _html()
    assert "首页总览" in html
    assert "项目中心" in html
    assert "设备中心" in html
    assert "线索中心" in html
    assert "任务中心" in html
    assert "系统设置" in html


def test_overview_uses_single_primary_action():
    html = _html()
    assert 'id="overview-primary-action"' in html
    assert 'id="overview-btn-collect"' not in html
    assert 'id="overview-btn-send"' not in html


def test_onboarding_modal_is_removed_from_shell():
    html = _html()
    assert 'id="modal-onboarding"' not in html
    assert "startOnboarding()" not in html
