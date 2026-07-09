import logging
import re
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
MAX_MEDIACRAWLER_KEYWORDS_PER_BATCH = 3


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


def _clean_keywords(values) -> list[str]:
    cleaned: list[str] = []
    seen = set()
    for value in values or []:
        item = str(value).strip()
        if not item:
            continue
        parts = [p.strip() for p in re.split(r"\s+", item) if p.strip()]
        candidates = parts if len(parts) >= 3 else [item]
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            cleaned.append(candidate)
    return cleaned


def _keyword_batches(keywords: list[str], batch_size: int | None) -> list[list[str]]:
    size = min(int(batch_size or 1), MAX_MEDIACRAWLER_KEYWORDS_PER_BATCH)
    if size <= 0:
        size = 1
    return [keywords[i : i + size] for i in range(0, len(keywords), size)]


def _collect_target_count(industry: IndustryConfig) -> int:
    try:
        target = int(getattr(industry, "collect_authors_per_run", 12) or 12)
    except (TypeError, ValueError):
        target = 12
    return max(target, 1)


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


def _append_deduped(
    comments: list[dict], candidates: list[dict], seen: dict[tuple, int]
) -> None:
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
    user_id: str | None = None,
):
    if skip_discover:
        return []

    workspace = prepare_mediacrawler_workspace()
    base_cfg_path = workspace / "config" / "base_config.py"
    configure_mediacrawler(base_cfg_path, max_comments=50)

    cookie_path = (
        BASE_DIR / "data" / "cookies" / str(user_id or "shared") / "douyin_cookies.json"
    )
    shadow_browser = ShadowBrowser(user_data_dir=str(BASE_DIR / "data" / "chrome_data"))
    try:
        shadow_browser.start()
        log.info(
            "[run_discovery] ShadowBrowser started on port %s", shadow_browser.port
        )
        # Inject dynamic CDP port and cookie login configuration into the isolated config.
        configure_mediacrawler(
            base_cfg_path, cdp_port=shadow_browser.port, cookie_path=cookie_path
        )
        log.info(
            "[run_discovery] Re-configured MediaCrawler for CDP port %s",
            shadow_browser.port,
        )

        configured_platforms = [
            str(p).strip()
            for p in (getattr(industry, "platforms", None) or ["douyin"])
            if str(p).strip()
        ]
        collect_target_count = _collect_target_count(industry)

        all_comments = []
        seen_comments: dict[tuple, int] = {}
        target_users = _unique_clean(getattr(industry, "target_users", []) or [])
        for p in configured_platforms:
            if should_stop and should_stop():
                log.info("Discovery cancelled for %s", p)
                break

            keywords = _clean_keywords(industry.keywords)
            keyword_normalized = []
            target_normalized = []

            if keywords:
                batch_size = getattr(industry, "keyword_batch_size", 1) or 1
                for keyword_batch in _keyword_batches(keywords, batch_size):
                    try:
                        keyword_comments = await run_platform(
                            p,
                            keyword_batch,
                            workspace=workspace,
                            target_users=target_users,
                            cdp_port=shadow_browser.port,
                            max_authors=getattr(industry, "collect_authors_per_run", 12)
                            or 12,
                            user_id=user_id,
                        )
                    except TimeoutError as exc:
                        log.warning(
                            "MediaCrawler keyword batch timed out and will be skipped: platform=%s keywords=%s error=%s",
                            p,
                            keyword_batch,
                            exc,
                        )
                        continue

                    keyword_normalized.extend(
                        _normalize_comment(
                            c,
                            industry_slug=industry.slug,
                            platform=p,
                            source_type="keyword",
                            source_keyword=str(
                                c.get("source_keyword") or ",".join(keyword_batch)
                            ),
                        )
                        for c in keyword_comments
                    )
                    if len(keyword_normalized) >= collect_target_count:
                        log.info(
                            "Discovery reached keyword source target: platform=%s collected=%s target=%s",
                            p,
                            len(keyword_normalized),
                            collect_target_count,
                        )
                        break
                    if should_stop and should_stop():
                        log.info("Discovery cancelled after keyword batch for %s", p)
                        break

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
                    cdp_port=shadow_browser.port,
                    user_id=user_id,
                )
                for c in target_comments:
                    creator = str(
                        c.get("source_creator") or c.get("source_sec_uid") or ""
                    ).strip()
                    target_normalized.append(
                        _normalize_comment(
                            c,
                            industry_slug=industry.slug,
                            platform=p,
                            source_type="target_account",
                            source_keyword=f"target:{creator}"
                            if creator
                            else str(c.get("source_keyword", "")),
                            source_creator=creator,
                        )
                    )

            if should_stop and should_stop():
                log.info(
                    "Discovery cancelled before appending target results for %s", p
                )
                _append_deduped(all_comments, keyword_normalized, seen_comments)
                break

            normalized_comments = keyword_normalized + target_normalized
            _append_deduped(all_comments, normalized_comments, seen_comments)

            log.info("Collected %d unique comments for %s.", len(all_comments), p)

    except Exception:
        if workspace.exists():
            debug_dir = BASE_DIR / "data" / "mc_failures"
            debug_dir.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(workspace), str(debug_dir / workspace.name))
                log.info(
                    "Preserved discover workspace for inspection: %s",
                    debug_dir / workspace.name,
                )
            except Exception as move_exc:
                log.warning(
                    "Failed to move workspace %s to debug dir: %s", workspace, move_exc
                )
                shutil.rmtree(workspace, ignore_errors=True)
        raise
    finally:
        shadow_browser.close()
        # Cleanup only happens on success path; except block above handles failures.
        if workspace.exists():
            shutil.rmtree(workspace, ignore_errors=True)

    return all_comments
