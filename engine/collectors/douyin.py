"""Douyin collector — uses internal JSON APIs via Playwright page.evaluate()."""

import asyncio
import io
import os
import re
import sys
import random
import logging
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from engine.collectors.base import PlaywrightCollector, BASE_DIR
from engine.collectors import register
from engine.config import IndustryConfig
from engine.queue import (
    add_blogger,
    get_bloggers,
    is_video_collected,
    mark_video_collected,
)

log = logging.getLogger("thunder.collector.douyin")

DOUYIN_PROFILE = BASE_DIR / "data" / "chrome_profile"
MIN_COMMENT = 1
TOP_VIDEOS = 8


@register("douyin")
class DouyinCollector(PlaywrightCollector):
    platform = "douyin"

    # ── Lifecycle ──────────────────────────────────

    async def _ensure_session(self) -> bool:
        await self._init_playwright(DOUYIN_PROFILE, headless=False)
        return await self._check_login()

    # ── Public interface ───────────────────────────

    async def discover_bloggers(
        self,
        industry: IndustryConfig,
        *,
        max_authors: int = 12,
        content_age_days: int = 7,
    ) -> int:
        added = 0

        for kw in industry.keywords:
            blogs = get_bloggers(industry_slug=industry.slug)
            if len([b for b in blogs if b["status"] == "active"]) >= max_authors:
                break

            log.info(f"  [discover] {kw}")
            search_url = (
                f"https://www.douyin.com/search/{kw}"
                f"?type=general&publish_time={content_age_days}"
            )
            try:
                await self._page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            except Exception:
                continue
            await asyncio.sleep(5)

            # Random mouse move to simulate human behavior
            try:
                vp = self._page.viewport_size or {"width": 1920, "height": 1080}
                await self._page.mouse.move(
                    random.randint(100, vp["width"] - 100),
                    random.randint(100, vp["height"] - 100),
                )
            except Exception:
                pass

            card_idx = 0
            max_idx = 12
            while card_idx < max_idx:
                if len([b for b in get_bloggers(industry_slug=industry.slug)
                        if b["status"] == "active"]) >= max_authors:
                    break

                vid = await self._click_search_card(card_idx)
                card_idx += 1
                if not vid:
                    continue

                author = await self._api_author(vid)
                if author and author.get("sec_uid"):
                    ok = add_blogger(
                        sec_uid=author["sec_uid"],
                        nickname=author.get("nickname", ""),
                        uid=author.get("uid", ""),
                        industry_slug=industry.slug,
                        source_keyword=kw,
                        source_video_id=vid,
                    )
                    if ok:
                        added += 1
                        current = len([b for b in get_bloggers(industry_slug=industry.slug)
                                      if b["status"] == "active"])
                        log.info(f"    +{author['nickname']} ({current}/{max_authors})")

                await asyncio.sleep(3)

            # Random delay between keywords to avoid detection
            await asyncio.sleep(random.randint(10, 25))

        return added

    async def collect_comments(self, industry: IndustryConfig) -> list[dict]:
        bloggers = get_bloggers(industry_slug=industry.slug)
        if not bloggers:
            log.warning("没有活跃博主")
            return []

        now_ts = int(datetime.now().timestamp())
        video_cutoff = now_ts - industry.video_max_age_days * 86400
        comment_cutoff = now_ts - industry.comment_max_age_hours * 3600
        all_comments = []

        for b in bloggers:
            sec_uid = b["sec_uid"]
            nickname = b["nickname"]
            log.info(f"  [creator] {nickname}")

            try:
                videos = await self._api_creator_videos(sec_uid)
                videos = [v for v in videos
                         if v.get("create_time", 0) >= video_cutoff
                         and v.get("comment_count", 0) >= MIN_COMMENT]
                videos = self._filter_relevant_videos(videos, industry.keywords)
                videos = videos[:TOP_VIDEOS]

                if not videos:
                    log.info(f"    无符合条件的视频")
                    continue

                log.info(f"    候选: {len(videos)}")
                for v in videos:
                    aweme_id = v["aweme_id"]
                    if is_video_collected(aweme_id, sec_uid):
                        continue

                    log.info(f"    [{v['comment_count']}评] {v.get('desc','')[:60]}")
                    comments = await self._api_comments(aweme_id, comment_cutoff)

                    for c in comments:
                        nick = c.get("user_name", "")
                        if len(nick.strip()) < 2:
                            continue
                        all_comments.append(
                            self._normalize_comment(
                                industry_slug=industry.slug,
                                keyword=f"creator:{nickname}",
                                post_id=aweme_id,
                                post_url=f"https://www.douyin.com/video/{aweme_id}",
                                comment_id=c.get("comment_id", ""),
                                content=c.get("text", ""),
                                nickname=nick,
                                user_id=c.get("user_id", ""),
                                extra={
                                    "short_id": c.get("short_id", ""),
                                    "douyin_id": c.get("douyin_id", ""),
                                    "unique_id": c.get("unique_id", ""),
                                },
                            )
                        )

                    mark_video_collected(aweme_id, sec_uid, v.get("comment_count", 0))
                    await asyncio.sleep(2)

            except Exception as e:
                log.warning(f"    [{nickname}] 异常: {e}")
                continue

        return all_comments

    # ── Browser login ──────────────────────────────

    async def _check_login(self) -> bool:
        try:
            await self._page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(3)

            async def _has_session():
                cookies = await self._page.context.cookies()
                return any(c["name"] == "sessionid" for c in cookies)

            if await _has_session():
                log.info("  抖音已登录")
                return True

            log.warning("  未登录！请在浏览器中扫码登录抖音...")
            for sec in range(120, 0, -3):
                await asyncio.sleep(3)
                if await _has_session():
                    log.info("  登录成功！")
                    return True
                if sec % 20 == 0 or sec <= 10:
                    log.info(f"  等待登录... 剩余 {sec}s")

            log.error("登录超时")
            return False
        except Exception as e:
            log.error(f"  登录检查异常: {e}")
            return False

    # ── Card click ─────────────────────────────────

    async def _click_search_card(self, index: int) -> str:
        try:
            cards = self._page.locator(".search-result-card")
            count = await cards.count()
            if count == 0 or index >= count:
                return ""

            card = cards.nth(index)
            box = await card.bounding_box()
            if not box:
                return ""
            await self._page.mouse.click(
                box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            )

            await asyncio.sleep(3)
            try:
                await self._page.wait_for_url("**modal_id=**", timeout=8000)
            except Exception:
                try:
                    await self._page.wait_for_url("**/video/**", timeout=5000)
                except Exception:
                    pass

            new_url = self._page.url
            m = re.search(r"modal_id=(\d+)", new_url)
            if m:
                vid = m.group(1)
                await self._page.keyboard.press("Escape")
                await asyncio.sleep(1)
                return vid
            m = re.search(r"/video/(\d+)", new_url)
            if m:
                return m.group(1)
            return ""
        except Exception:
            return ""

    # ── Video relevance filter ─────────────────────

    def _filter_relevant_videos(self, videos: list[dict], keywords: list[str]) -> list[dict]:
        """Score videos by title keyword match. Keep videos with score > 0."""
        scored = []
        for v in videos:
            desc = v.get("desc", "")
            score = sum(1 for kw in keywords if kw in desc)
            scored.append((score, v))
        # Keep videos with any keyword match, sorted by score desc
        relevant = [v for s, v in scored if s > 0]
        if relevant:
            relevant.sort(key=lambda x: x.get("comment_count", 0), reverse=True)
            return relevant
        # If no match, return top by comment count as fallback
        log.info(f"    无关键词匹配视频，取评论最多")
        fallback = sorted(videos, key=lambda x: x.get("comment_count", 0), reverse=True)
        return fallback[:3]

    # ── Douyin internal APIs ───────────────────────

    async def _api_author(self, video_id: str) -> dict | None:
        try:
            return await self._page.evaluate("""async (awemeId) => {
                const url = '/aweme/v1/web/aweme/detail/?aweme_id=' + awemeId;
                const resp = await fetch(url, {credentials: 'include'});
                const data = await resp.json();
                const author = data.aweme_detail && data.aweme_detail.author;
                if (author) return {sec_uid: author.sec_uid || '', nickname: author.nickname || '', uid: author.uid || ''};
                return null;
            }""", video_id)
        except Exception:
            return None

    async def _api_creator_videos(self, sec_uid: str) -> list[dict]:
        try:
            videos = await self._page.evaluate("""async (secUid) => {
                const url = '/aweme/v1/web/aweme/post/?sec_user_id='
                          + secUid + '&count=36&max_cursor=0&aid=6383';
                const resp = await fetch(url, {
                    credentials: 'include',
                    headers: { 'Referer': 'https://www.douyin.com/user/' + secUid }
                });
                const data = await resp.json();
                return (data.aweme_list || []).map(v => ({
                    aweme_id: v.aweme_id || '',
                    desc: (v.desc || '').substring(0, 200),
                    comment_count: v.statistics && v.statistics.comment_count || 0,
                    create_time: v.create_time || 0,
                }));
            }""", sec_uid)
            if isinstance(videos, list):
                videos.sort(key=lambda v: v.get("comment_count", 0), reverse=True)
            return videos if isinstance(videos, list) else []
        except Exception:
            return []

    async def _api_comments(self, video_id: str, cutoff_ts: int) -> list[dict]:
        try:
            comments_raw = await self._page.evaluate("""async (awemeId) => {
                const allComments = [];
                let cursor = 0;
                const maxPages = 3;
                for (let p = 0; p < maxPages; p++) {
                    const url = '/aweme/v1/web/comment/list/?aweme_id='
                              + awemeId + '&cursor=' + cursor + '&count=20&item_type=0';
                    const resp = await fetch(url, {credentials: 'include'});
                    const data = await resp.json();
                    const page = data.comments || [];
                    allComments.push(...page.map(c => ({
                        comment_id: c.cid || '',
                        text: c.text || '',
                        user_name: (c.user && c.user.nickname) || '',
                        user_id: (c.user && c.user.sec_uid) || '',
                        short_id: (c.user && c.user.short_id) || '',
                        douyin_id: (c.user && c.user.uid) || '',
                        unique_id: (c.user && c.user.unique_id) || '',
                        create_time: c.create_time || 0,
                    })));
                    if (!data.has_more || page.length === 0) break;
                    cursor = data.cursor || 0;
                }
                return allComments;
            }""", video_id)
            if isinstance(comments_raw, list):
                return [c for c in comments_raw if c.get("create_time", 0) >= cutoff_ts]
            return []
        except Exception:
            return []
