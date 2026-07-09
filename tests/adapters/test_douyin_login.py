"""Regression tests for patched Douyin login behavior."""

from __future__ import annotations

import sys
import importlib.util
from pathlib import Path

import pytest


MC_DIR = Path(__file__).resolve().parents[2] / "deps" / "MediaCrawler"
if str(MC_DIR) not in sys.path:
    sys.path.insert(0, str(MC_DIR))

spec = importlib.util.spec_from_file_location(
    "douyin_login_under_test", MC_DIR / "media_platform" / "douyin" / "login.py"
)
assert spec and spec.loader
douyin_login = importlib.util.module_from_spec(spec)
spec.loader.exec_module(douyin_login)
DouYinLogin = douyin_login.DouYinLogin


class FakeContext:
    pass


class InterceptedLocator:
    async def click(self):
        raise Exception("subtree intercepts pointer events")


class FakeLoginPage:
    def __init__(self):
        self.evaluated_scripts: list[str] = []

    async def wait_for_selector(self, selector, timeout=None):
        raise TimeoutError("dialog not visible")

    def locator(self, selector):
        return InterceptedLocator()

    async def evaluate(self, script):
        self.evaluated_scripts.append(script)
        return True


@pytest.mark.asyncio
async def test_popup_login_dialog_uses_dom_click_when_overlay_intercepts_pointer_events():
    page = FakeLoginPage()
    login = DouYinLogin(
        login_type="qrcode",
        browser_context=FakeContext(),
        context_page=page,
    )

    await login.popup_login_dialog()

    assert page.evaluated_scripts
    assert "登录" in page.evaluated_scripts[0]


class VariantLoginPage(FakeLoginPage):
    async def evaluate(self, script):
        self.evaluated_scripts.append(script)
        return "登录 / 注册" in script and "includes(keyword)" in script


@pytest.mark.asyncio
async def test_popup_login_dialog_accepts_login_register_text_variant():
    page = VariantLoginPage()
    login = DouYinLogin(
        login_type="qrcode",
        browser_context=FakeContext(),
        context_page=page,
    )

    await login.popup_login_dialog()

    assert page.evaluated_scripts


class MissingLoginPage(FakeLoginPage):
    async def evaluate(self, script):
        self.evaluated_scripts.append(script)
        if "document.body" in script:
            return "首页 推荐 搜索"
        return False


@pytest.mark.asyncio
async def test_popup_login_dialog_reports_page_snapshot_when_entry_missing():
    page = MissingLoginPage()
    login = DouYinLogin(
        login_type="qrcode",
        browser_context=FakeContext(),
        context_page=page,
    )

    with pytest.raises(RuntimeError, match="login button not found"):
        await login.popup_login_dialog()

    assert any("document.body" in script for script in page.evaluated_scripts)
