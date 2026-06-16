"""Xiaohongshu collector — Crawl4AI + LLM extraction for platforms without public APIs."""

import asyncio
import logging
import re
from datetime import datetime

from engine.collectors.base import Crawl4AICollector, PROFILES_DIR
from engine.collectors import register
from engine.config import IndustryConfig, load_system
from engine.queue import (
    add_blogger, get_bloggers, is_video_collected, mark_video_collected,
)

log = logging.getLogger("thunder.collector.xhs")
_sys = load_system()

XHS_BASE = "https://www.xiaohongshu.com"

NOTE_LIST_SCHEMA = {
    "type": "object",
    "properties": {
        "notes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "note_id":    {"type": "string"},
                    "title":      {"type": "string"},
                    "author_name":{"type": "string"},
                    "author_id":  {"type": "string"},
                    "like_count": {"type": "integer"},
                },
                "required": ["note_id", "title", "author_name", "author_id"],
            },
        },
    },
    "required": ["notes"],
}

COMMENT_LIST_SCHEMA = {
    "type": "object",
    "properties": {
        "comments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "comment_id":  {"type": "string"},
                    "content":     {"type": "string"},
                    "nickname":    {"type": "string"},
                    "user_id":     {"type": "string"},
                },
                "required": ["comment_id", "content", "nickname"],
            },
        },
    },
    "required": ["comments"],
}


@register("xiaohongshu")
class XHSCollector(Crawl4AICollector):
    platform = "xiaohongshu"

    @staticmethod
    def _default_profile_dir():
        return PROFILES_DIR / "xiaohongshu"

    # ── Lifecycle ──────────────────────────────────

    async def _ensure_session(self) -> bool:
        await self._start_crawler(headless=False)
        return await self._check_login()

    async def _check_login(self) -> bool:
        url = f"{XHS_BASE}/explore"
        result = await self._crawler.arun(url=url, config={"page_timeout": 20000})
        md = result.markdown or ""
        if "登录" in md[:300]:
            log.warning("  XHS 未登录！请在浏览器中扫码...")
            for sec in range(120, 0, -5):
                await asyncio.sleep(5)
                r = await self._crawler.arun(url=url, config={"page_timeout": 10000})
                if "登录" not in (r.markdown or "")[:300]:
                    log.info("  XHS 登录成功！")
                    return True
                if sec % 20 == 0 or sec <= 10:
                    log.info(f"    等待登录... 剩余 {sec}s")
            log.error("XHS 登录超时")
            return False
        log.info("  XHS 已登录")
        return True

    # ── Blogger discovery ──────────────────────────

    async def discover_bloggers(
        self, industry: IndustryConfig, *,
        max_authors: int = 12, content_age_days: int = 7,
    ) -> int:
        from crawl4ai import CrawlerRunConfig, LLMConfig, LLMExtractionStrategy

        added = 0
        llm_cfg = LLMConfig(
            provider="deepseek/deepseek-chat",
            api_token=_sys["api_keys"]["deepseek"],
        )

        for kw in industry.keywords:
            blogs = get_bloggers(industry_slug=industry.slug)
            active = [b for b in blogs if b["status"] == "active"]
            if len(active) >= max_authors:
                break

            log.info(f"  [xhs:discover] {kw}")
            try:
                result = await self._crawler.arun(
                    url=f"{XHS_BASE}/search_result?keyword={kw}&type=51",
                    config=CrawlerRunConfig(
                        extraction_strategy=LLMExtractionStrategy(
                            llm_config=llm_cfg,
                            instruction=(
                                f"Extract up to 10 note entries from XHS search results "
                                f"for keyword '{kw}'. Each entry must have note_id, title, "
                                f"author_name, and author_id."
                            ),
                            schema=NOTE_LIST_SCHEMA,
                            extraction_type="schema",
                        ),
                        js_code="window.scrollTo(0, 800);",
                        page_timeout=30000,
                    ),
                )
                notes_data = result.extracted_content
                if not notes_data or not isinstance(notes_data, dict):
                    continue

                seen_authors = set()
                for note in notes_data.get("notes", []):
                    aid = note.get("author_id", "")
                    aname = note.get("author_name", "")
                    if not aid or aid in seen_authors:
                        continue
                    seen_authors.add(aid)
                    ok = add_blogger(
                        sec_uid=aid, nickname=aname,
                        industry_slug=industry.slug,
                        source_keyword=kw,
                        source_video_id=note.get("note_id", ""),
                    )
                    if ok:
                        added += 1
                        current = len([
                            b for b in get_bloggers(industry_slug=industry.slug)
                            if b["status"] == "active"
                        ])
                        log.info(f"    + {aname} ({current}/{max_authors})")

                await asyncio.sleep(4)
            except Exception as e:
                log.warning(f"    [xhs:discover] {kw} 异常: {e}")
                continue

        return added

    # ── Comment collection ─────────────────────────

    async def collect_comments(self, industry: IndustryConfig) -> list[dict]:
        from crawl4ai import CrawlerRunConfig, LLMConfig, LLMExtractionStrategy

        bloggers = get_bloggers(industry_slug=industry.slug)
        if not bloggers:
            log.warning("[xhs] 没有活跃博主")
            return []

        comment_cutoff = int(datetime.now().timestamp()) - industry.comment_max_age_hours * 3600
        all_comments = []

        for b in bloggers:
            sec_uid = b["sec_uid"]
            nickname = b["nickname"]
            log.info(f"  [xhs:creator] {nickname}")

            try:
                profile_url = f"{XHS_BASE}/user/profile/{sec_uid}"
                result = await self._crawler.arun(
                    url=profile_url,
                    config=CrawlerRunConfig(
                        js_code=[
                            "window.scrollTo(0, 500);",
                            "await new Promise(r => setTimeout(r, 1500));",
                            "window.scrollTo(0, 1200);",
                        ],
                        page_timeout=30000,
                    ),
                )
                note_ids = self._extract_note_ids(result.markdown or "")
                log.info(f"    找到 {len(note_ids)} 篇笔记")

                for nid in note_ids[:8]:
                    if is_video_collected(nid, sec_uid):
                        continue

                    note_url = f"{XHS_BASE}/explore/{nid}"
                    note_result = await self._crawler.arun(
                        url=note_url,
                        config=CrawlerRunConfig(
                            extraction_strategy=LLMExtractionStrategy(
                                llm_config=LLMConfig(
                                    provider="deepseek/deepseek-chat",
                                    api_token=_sys["api_keys"]["deepseek"],
                                ),
                                instruction=(
                                    "Extract all visible comment data from this XHS note page. "
                                    "For each comment capture comment_id, content text, "
                                    "nickname, and user_id."
                                ),
                                schema=COMMENT_LIST_SCHEMA,
                                extraction_type="schema",
                            ),
                            js_code="window.scrollTo(0, document.body.scrollHeight * 0.5);",
                            page_timeout=30000,
                        ),
                    )
                    comments_data = note_result.extracted_content
                    if not comments_data or not isinstance(comments_data, dict):
                        mark_video_collected(nid, sec_uid, 0)
                        continue

                    for c in comments_data.get("comments", []):
                        nick = c.get("nickname", "").strip()
                        if len(nick) < 2:
                            continue
                        all_comments.append(
                            self._normalize_comment(
                                industry_slug=industry.slug,
                                keyword=b.get("source_keyword", ""),
                                post_id=nid,
                                post_url=note_url,
                                comment_id=c.get("comment_id", ""),
                                content=c.get("content", ""),
                                nickname=nick,
                                user_id=c.get("user_id", ""),
                            )
                        )

                    mark_video_collected(nid, sec_uid, len(comments_data.get("comments", [])))
                    await asyncio.sleep(2)

            except Exception as e:
                log.warning(f"    [xhs] {nickname} 异常: {e}")
                continue

        return all_comments

    # ── Helpers ────────────────────────────────────

    @staticmethod
    def _extract_note_ids(md: str) -> list[str]:
        """Parse markdown for XHS note URLs: /explore/<24-char-hex>"""
        pattern = r"/explore/([a-f0-9]{24})"
        seen = set()
        ids = []
        for m in re.finditer(pattern, md):
            nid = m.group(1)
            if nid not in seen:
                seen.add(nid)
                ids.append(nid)
        return ids
