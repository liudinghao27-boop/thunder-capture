"""MediaCrawler subprocess runner.

Extracted from core/discover.py to provide a clean adapter interface.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path

log = logging.getLogger("thunder.mediacrawler")

BASE_DIR = Path(__file__).resolve().parent.parent.parent
MC_DIR = BASE_DIR / "deps" / "MediaCrawler"

PLATFORM_MAP = {
    "douyin": "dy",
    "xiaohongshu": "xhs",
    "kuaishou": "ks",
    "bilibili": "bili",
    "weibo": "weibo",
    "zhihu": "zhihu",
}

RESULT_FOLDER_MAP = {
    "dy": "douyin",
    "xhs": "xhs",
    "ks": "kuaishou",
}


def configure_mediacrawler(*, cdp_port: int = 0, max_comments: int = 50) -> None:
    """Update MediaCrawler base_config.py with runtime settings.

    Args:
        cdp_port: Chrome DevTools Protocol port (0 = auto)
        max_comments: Max comments per post
    """
    base_cfg = MC_DIR / "config" / "base_config.py"
    if not base_cfg.exists():
        raise FileNotFoundError(f"MediaCrawler not found at {MC_DIR}")

    with open(base_cfg, "r", encoding="utf-8") as f:
        content = f.read()

    content = re.sub(r'SAVE_DATA_OPTION\s*=\s*".*?"', 'SAVE_DATA_OPTION = "jsonl"', content)
    content = re.sub(r'ENABLE_GET_COMMENTS\s*=\s*(True|False)', 'ENABLE_GET_COMMENTS = True', content)
    content = re.sub(r'CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES\s*=\s*\d+',
                     f'CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES = {max_comments}', content)
    content = re.sub(r'ENABLE_CDP_MODE\s*=\s*(True|False)', 'ENABLE_CDP_MODE = True', content)

    if cdp_port > 0:
        content = re.sub(r'CDP_DEBUG_PORT\s*=\s*\d+', f'CDP_DEBUG_PORT = {cdp_port}', content)

    with open(base_cfg, "w", encoding="utf-8") as f:
        f.write(content)


async def run_platform(
    platform: str,
    keywords: list[str],
    *,
    max_authors: int = 12,
) -> list[dict]:
    """Run MediaCrawler for one platform and parse JSONL results.

    Args:
        platform: 'douyin' | 'xiaohongshu' | 'kuaishou'
        keywords: Search keywords
        max_authors: Max content authors to discover

    Returns:
        List of comment dicts ready for classification
    """
    mc_platform = PLATFORM_MAP.get(platform, "dy")
    keywords_str = ",".join(keywords)

    cmd = [
        "python", "main.py",
        "--platform", mc_platform,
        "--type", "search",
        "--keywords", keywords_str,
    ]

    log.info("MediaCrawler: %s keywords=%s", platform, keywords_str)

    process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(MC_DIR),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        err = stderr.decode("utf-8", errors="ignore")
        raise RuntimeError(f"MediaCrawler {platform} failed: {err[:200]}")

    # Parse JSONL output
    folder = RESULT_FOLDER_MAP.get(mc_platform, mc_platform)
    data_dir = MC_DIR / "data" / folder / "jsonl"

    if not data_dir.exists():
        log.warning("No JSONL output for platform=%s", platform)
        return []

    comments = []
    for file in data_dir.glob("*_comments_*.jsonl"):
        try:
            with open(file, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    c = json.loads(line)
                    text = c.get("content") or c.get("text", "")
                    if not text:
                        continue
                    comments.append({
                        "text": text,
                        "source_name": c.get("nickname", "user"),
                        "source_sec_uid": c.get("sec_uid") or c.get("user_id", ""),
                        "source_short_id": c.get("short_id") or "",
                        "source_video_id": c.get("aweme_id") or c.get("note_id", ""),
                        "source_keyword": keywords_str,
                        "source_platform": platform,
                    })
        except Exception as exc:
            log.error("Failed parsing %s: %s", file.name, exc)

    # Clean up JSONL to prevent re-processing
    for file in data_dir.glob("*.jsonl"):
        file.unlink(missing_ok=True)

    log.info("MediaCrawler %s: %d comments parsed", platform, len(comments))
    return comments
