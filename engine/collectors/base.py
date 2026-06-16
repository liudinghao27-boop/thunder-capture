"""Base collector interfaces for multi-platform social media collection."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.config import IndustryConfig

log = logging.getLogger("thunder.collector")
BASE_DIR = Path(__file__).resolve().parent.parent.parent
PROFILES_DIR = BASE_DIR / "data" / "profiles"


class BaseCollector(ABC):
    """Abstract collector for one social media platform."""

    platform: str = ""

    # ── Public interface ──────────────────────────

    @abstractmethod
    async def discover_bloggers(
        self,
        industry: IndustryConfig,
        *,
        max_authors: int = 12,
        content_age_days: int = 7,
    ) -> int:
        """Search for bloggers matching industry keywords. Return newly added count."""
        ...

    @abstractmethod
    async def collect_comments(
        self,
        industry: IndustryConfig,
    ) -> list[dict]:
        """For each active blogger, collect recent comments. Return normalized list."""
        ...

    async def run(
        self,
        industry: IndustryConfig,
        *,
        max_authors: int = 12,
        content_age_days: int = 7,
        skip_discover: bool = False,
    ) -> list[dict]:
        """Full pipeline: ensure session -> [discover] -> collect -> cleanup."""
        session_ok = await self._ensure_session()
        if not session_ok:
            log.error(f"  [{self.platform}] 登录/会话建立失败，终止采集")
            await self._cleanup()
            return []
        try:
            if skip_discover:
                log.info(f"  [{self.platform}] skip discover, incremental collect only")
            else:
                added = await self.discover_bloggers(
                    industry, max_authors=max_authors,
                    content_age_days=content_age_days,
                )
                log.info(f"  [{self.platform}] Phase 1: +{added} 博主")
            comments = await self.collect_comments(industry)
            log.info(f"  [{self.platform}] Phase 2: {len(comments)} 条候选")
            return comments
        except Exception:
            log.exception(f"  [{self.platform}] 采集异常")
            return []
        finally:
            await self._cleanup()

    # ── Internal lifecycle ────────────────────────

    @abstractmethod
    async def _ensure_session(self) -> bool:
        """Initialize browser / connection. Return True if ready."""
        ...

    @abstractmethod
    async def _cleanup(self):
        """Release browser, connections, file handles."""
        ...

    # ── Shared helpers ────────────────────────────

    def _normalize_comment(
        self,
        industry_slug: str,
        keyword: str,
        post_id: str,
        post_url: str,
        comment_id: str,
        content: str,
        nickname: str,
        user_id: str,
        extra: dict | None = None,
    ) -> dict:
        """Produce a dict compatible with enqueue_task() and classify_batch()."""
        result = {
            "industry_slug": industry_slug,
            "platform": self.platform,
            "keyword": keyword,
            "post_id": post_id,
            "post_url": post_url,
            "comment_id": comment_id,
            "content": content,
            "nickname": nickname,
            "user_id": user_id,
            "aweme_id": post_id,
            "video_url": post_url,
            "sec_uid": user_id,
            "fetched_at": datetime.now().isoformat(),
        }
        if extra:
            result.update(extra)
        return result


# ── Concrete intermediate bases ──────────────────────


class PlaywrightCollector(BaseCollector):
    """For platforms with internal JSON APIs reachable via page.evaluate()."""

    def __init__(self):
        self._playwright = None
        self._context = None
        self._page = None

    async def _init_playwright(
        self,
        profile_dir: Path,
        headless: bool = False,
        viewport: dict | None = None,
        user_agent: str | None = None,
    ):
        from playwright.async_api import async_playwright
        from playwright_stealth import Stealth

        profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=headless,
            viewport=viewport or {"width": 1920, "height": 1080},
            user_agent=user_agent or (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            ),
            locale="zh-CN",
        )
        stealth = Stealth()
        await stealth.apply_stealth_async(self._context)
        self._page = await self._context.new_page()

    async def _cleanup(self):
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass


class Crawl4AICollector(BaseCollector):
    """For platforms without public JSON APIs — Crawl4AI renders + extracts."""

    def __init__(self):
        self._crawler = None
        self._profile_dir: Path | None = None

    @staticmethod
    def _default_profile_dir() -> Path:
        """Override in subclass to set platform-specific profile name."""
        return PROFILES_DIR / "default"

    async def _start_crawler(
        self,
        headless: bool = False,
        **extra_browser_kwargs,
    ):
        from crawl4ai import AsyncWebCrawler, BrowserConfig

        self._profile_dir = self._default_profile_dir()
        self._profile_dir.mkdir(parents=True, exist_ok=True)

        config = BrowserConfig(
            browser_type="chromium",
            headless=headless,
            use_persistent_context=True,
            user_data_dir=str(self._profile_dir),
            viewport_width=1920,
            viewport_height=1080,
            locale="zh-CN",
            verbose=False,
            **extra_browser_kwargs,
        )
        self._crawler = AsyncWebCrawler(config=config)
        await self._crawler.start()

    async def _cleanup(self):
        if self._crawler:
            try:
                await self._crawler.close()
            except Exception:
                pass
