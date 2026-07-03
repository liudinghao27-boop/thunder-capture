import logging
import shutil
from pathlib import Path

from adapters.mediacrawler.runner import (
    configure_mediacrawler,
    prepare_mediacrawler_workspace,
    run_platform,
    run_target_accounts,
)
from core.browser_orchestrator import ShadowBrowser
from core.config import IndustryConfig

log = logging.getLogger("thunder.discover")
BASE_DIR = Path(__file__).resolve().parent.parent


def _unique_clean(values) -> list[str]:
    cleaned: list[str] = []
    seen = set()
    for value in values or []:
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        cleaned.append(item)
    return cleaned


def _dedupe_key(comment: dict) -> tuple[str, str, str] | tuple[str, str, str, str]:
    platform = str(comment.get("source_platform", "")).strip()
    video_id = str(comment.get("source_video_id", "")).strip()
    comment_id = str(comment.get("source_short_id", "")).strip()
    if video_id and comment_id:
        return ("stable", platform, video_id, comment_id)
    return (
        "fallback",
        platform,
        str(comment.get("source_sec_uid", "")).strip(),
        str(comment.get("text", "")).strip(),
    )


def _normalize_comment(
    comment: dict,
    *,
    industry_slug: str,
    platform: str,
    source_type: str,
    source_keyword: str,
    source_creator: str = "",
) -> dict:
    normalized = dict(comment)
    normalized["industry_slug"] = industry_slug
    if not normalized.get("source_platform"):
        normalized["source_platform"] = platform
    normalized["source_type"] = source_type
    if source_keyword:
        normalized["source_keyword"] = source_keyword
    if source_creator:
        normalized["source_creator"] = source_creator
    return normalized


def _append_deduped(comments: list[dict], candidates: list[dict], seen: dict[tuple, int]) -> None:
    for candidate in candidates:
        key = _dedupe_key(candidate)
        existing_index = seen.get(key)
        if existing_index is None:
            seen[key] = len(comments)
            comments.append(candidate)
            continue
        if candidate.get("source_type") == "target_account":
            comments[existing_index] = candidate


async def run_discovery(
    industry: IndustryConfig,
    max_authors=None,
    video_age_days=7,
    skip_discover=False,
    crawldir: str | None = None,
    should_stop=None,
):
    if skip_discover:
        return []

    workspace = prepare_mediacrawler_workspace()
    base_cfg_path = workspace / "config" / "base_config.py"
    configure_mediacrawler(base_cfg_path, max_comments=50)

    shadow_browser = ShadowBrowser(user_data_dir=str(BASE_DIR / "data" / "chrome_data"))
    try:
        shadow_browser.start()
        # Inject dynamic CDP port into the isolated config.
        configure_mediacrawler(base_cfg_path, cdp_port=shadow_browser.port)

        configured_platforms = [
            str(p).strip()
            for p in (getattr(industry, "platforms", None) or ["douyin"])
            if str(p).strip()
        ]

        all_comments = []
        seen_comments: dict[tuple, int] = {}
        target_users = _unique_clean(getattr(industry, "target_users", []) or [])
        for p in configured_platforms:
            if should_stop and should_stop():
                log.info("Discovery cancelled for %s", p)
                break

            keywords = _unique_clean(industry.keywords)
            keyword_normalized = []
            target_normalized = []

            if keywords:
                keyword_comments = await run_platform(
                    p,
                    keywords if isinstance(keywords, list) else [str(keywords)],
                    workspace=workspace,
                    target_users=target_users,
                )

                keyword_normalized = [
                    _normalize_comment(
                        c,
                        industry_slug=industry.slug,
                        platform=p,
                        source_type="keyword",
                        source_keyword=str(c.get("source_keyword") or ",".join(keywords)),
                    )
                    for c in keyword_comments
                ]

            if should_stop and should_stop():
                log.info("Discovery cancelled after keyword collection for %s", p)
                _append_deduped(all_comments, keyword_normalized, seen_comments)
                break

            if target_users:
                target_comments = await run_target_accounts(
                    p,
                    target_users,
                    keywords=keywords,
                    max_videos=getattr(industry, "collect_video_limit", None),
                    workspace=workspace,
                )
                for c in target_comments:
                    creator = str(c.get("source_creator") or c.get("source_sec_uid") or "").strip()
                    target_normalized.append(
                        _normalize_comment(
                            c,
                            industry_slug=industry.slug,
                            platform=p,
                            source_type="target_account",
                            source_keyword=f"target:{creator}" if creator else str(c.get("source_keyword", "")),
                            source_creator=creator,
                        )
                    )

            if should_stop and should_stop():
                log.info("Discovery cancelled before appending target results for %s", p)
                _append_deduped(all_comments, keyword_normalized, seen_comments)
                break

            normalized_comments = keyword_normalized + target_normalized
            _append_deduped(all_comments, normalized_comments, seen_comments)

            log.info("Collected %d unique comments for %s.", len(all_comments), p)

    finally:
        shadow_browser.close()
        shutil.rmtree(workspace, ignore_errors=True)

    return all_comments
