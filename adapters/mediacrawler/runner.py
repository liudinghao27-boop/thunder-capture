"""MediaCrawler subprocess runner.

Extracted from core/discover.py to provide a clean adapter interface.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import sys
import tempfile
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
    "bili": "bilibili",
    "weibo": "weibo",
    "zhihu": "zhihu",
}

_LOG_TAIL_CHARS = 4000

# Directories that do not need to be copied into a per-job workspace.
_IGNORED_WORKSPACE_DIRS = {
    "data",
    "browser_data",
    "__pycache__",
    ".git",
    ".venv",
    "node_modules",
    "test",
    "tests",
    "docs",
}


def prepare_mediacrawler_workspace() -> Path:
    """Create an isolated copy of MediaCrawler for a single job.

    Copying the whole project avoids concurrent writes to the shared
    ``deps/MediaCrawler/config/base_config.py`` and keeps per-job JSONL
    output separated. Large/derived directories are skipped.
    """
    if not MC_DIR.exists():
        raise FileNotFoundError(f"MediaCrawler not found at {MC_DIR}")

    workspace = Path(tempfile.mkdtemp(prefix="thunder_mc_"))
    log.info("MediaCrawler workspace: %s", workspace)

    def _ignore(src: str, names: list[str]) -> set[str]:
        # Skip directories/files that are job-specific, cached, or large.
        ignored = set(_IGNORED_WORKSPACE_DIRS)
        ignored.update(n for n in names if n.endswith(".pyc") or n.endswith(".pyo"))
        return ignored

    shutil.copytree(MC_DIR, workspace, ignore=_ignore, dirs_exist_ok=True)
    return workspace


def configure_mediacrawler(
    base_config_path: Path,
    *,
    cdp_port: int = 0,
    max_comments: int = 50,
) -> None:
    """Update a MediaCrawler base_config.py copy with runtime settings.

    Args:
        base_config_path: Path to the isolated ``base_config.py`` to rewrite.
        cdp_port: Chrome DevTools Protocol port (0 = leave unchanged).
        max_comments: Max comments per post.
    """
    if not base_config_path.exists():
        raise FileNotFoundError(f"MediaCrawler config not found at {base_config_path}")

    with open(base_config_path, "r", encoding="utf-8") as f:
        content = f.read()

    content = re.sub(r'SAVE_DATA_OPTION\s*=\s*".*?"', 'SAVE_DATA_OPTION = "jsonl"', content)
    content = re.sub(r'ENABLE_GET_COMMENTS\s*=\s*(True|False)', 'ENABLE_GET_COMMENTS = True', content)
    content = re.sub(
        r'CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES\s*=\s*\d+',
        f'CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES = {max_comments}',
        content,
    )
    content = re.sub(r'ENABLE_CDP_MODE\s*=\s*(True|False)', 'ENABLE_CDP_MODE = True', content)

    if cdp_port > 0:
        content = re.sub(r'CDP_DEBUG_PORT\s*=\s*\d+', f'CDP_DEBUG_PORT = {cdp_port}', content)

    with open(base_config_path, "w", encoding="utf-8") as f:
        f.write(content)


async def _run_mediacrawler_process(cmd: list[str], *, mc_dir: Path, platform: str) -> tuple[str, str]:
    process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(mc_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    stdout_text = stdout.decode("utf-8", errors="ignore").strip()
    stderr_text = stderr.decode("utf-8", errors="ignore").strip()

    if process.returncode != 0:
        raise RuntimeError(f"MediaCrawler {platform} failed: {stderr_text[-2000:]}")

    return stdout_text, stderr_text


def _log_empty_output(
    reason: str,
    *,
    platform: str,
    mc_dir: Path,
    stdout_text: str,
    stderr_text: str,
) -> None:
    output_roots = [
        str(path.relative_to(mc_dir))
        for path in (mc_dir / "data").rglob("*")
        if path.is_file()
    ] if (mc_dir / "data").exists() else []
    log.warning(
        "%s platform=%s workspace=%s output_files=%s stdout_tail=%r stderr_tail=%r",
        reason,
        platform,
        mc_dir,
        output_roots[-20:],
        stdout_text[-_LOG_TAIL_CHARS:],
        stderr_text[-_LOG_TAIL_CHARS:],
    )


def _parse_jsonl_comments(
    *,
    mc_dir: Path,
    mc_platform: str,
    platform: str,
    source_keyword: str,
    stdout_text: str,
    stderr_text: str,
    source_creator: str = "",
) -> list[dict]:
    folder = RESULT_FOLDER_MAP.get(mc_platform, mc_platform)
    data_dir = mc_dir / "data" / folder / "jsonl"

    if not data_dir.exists():
        _log_empty_output(
            "No JSONL output",
            platform=platform,
            mc_dir=mc_dir,
            stdout_text=stdout_text,
            stderr_text=stderr_text,
        )
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
                    item = {
                        "text": text,
                        "source_name": c.get("nickname", "user"),
                        "source_sec_uid": c.get("sec_uid") or c.get("user_id", ""),
                        "source_short_id": c.get("short_id") or c.get("comment_id", ""),
                        "source_video_id": c.get("aweme_id") or c.get("note_id", ""),
                        "source_keyword": source_keyword,
                        "source_platform": platform,
                    }
                    if source_creator:
                        item["source_creator"] = source_creator
                    comments.append(item)
        except Exception as exc:
            log.error("Failed parsing %s: %s", file.name, exc)

    for file in data_dir.glob("*.jsonl"):
        file.unlink(missing_ok=True)

    if not comments:
        _log_empty_output(
            "JSONL output contained no usable comments",
            platform=platform,
            mc_dir=mc_dir,
            stdout_text=stdout_text,
            stderr_text=stderr_text,
        )

    return comments


async def run_platform(
    platform: str,
    keywords: list[str],
    *,
    max_authors: int = 12,
    workspace: Path | None = None,
    target_users: list[str] | None = None,
) -> list[dict]:
    """Run MediaCrawler for one platform and parse JSONL results.

    Args:
        platform: 'douyin' | 'xiaohongshu' | 'kuaishou' | ...
        keywords: Search keywords
        max_authors: Max content authors to discover (currently unused by MC).
        workspace: Isolated MediaCrawler directory. Defaults to the shared
            ``deps/MediaCrawler`` for backward compatibility.
        target_users: Persisted competitor account identifiers. Platform
            account crawling is implemented behind MediaCrawler, but keeping
            this parameter in the adapter contract lets the discovery layer
            always pass target context alongside keyword search.

    Returns:
        List of comment dicts ready for classification.
    """
    mc_platform = PLATFORM_MAP.get(platform, "dy")
    keywords_str = ",".join(keywords)
    mc_dir = workspace or MC_DIR
    cleaned_targets = [str(u).strip() for u in (target_users or []) if str(u).strip()]

    cmd = [
        sys.executable, "main.py",
        "--platform", mc_platform,
        "--type", "search",
        "--keywords", keywords_str,
    ]

    log.info(
        "MediaCrawler: %s keywords=%s targets=%s workspace=%s",
        platform,
        keywords_str,
        len(cleaned_targets),
        mc_dir,
    )

    stdout_text, stderr_text = await _run_mediacrawler_process(cmd, mc_dir=mc_dir, platform=platform)
    comments = _parse_jsonl_comments(
        mc_dir=mc_dir,
        mc_platform=mc_platform,
        platform=platform,
        source_keyword=keywords_str,
        stdout_text=stdout_text,
        stderr_text=stderr_text,
    )

    log.info("MediaCrawler %s: %d comments parsed", platform, len(comments))
    return comments


async def run_target_accounts(
    platform: str,
    target_users: list[str],
    *,
    keywords: list[str] | None = None,
    max_videos: int | None = None,
    workspace: Path | None = None,
) -> list[dict]:
    """Collect comments from configured target accounts.

    This is a stable adapter boundary. Platform-specific account crawling can
    replace this fallback later without changing discovery, classification, or
    queue insertion.
    """
    cleaned_targets = []
    seen = set()
    for target in target_users or []:
        value = str(target).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        cleaned_targets.append(value)

    if not cleaned_targets:
        return []

    mc_platform = PLATFORM_MAP.get(platform)
    if mc_platform != "dy":
        log.info(
            "target account collection unsupported: platform=%s targets=%s workspace=%s",
            platform,
            len(cleaned_targets),
            workspace or MC_DIR,
        )
        return []

    mc_dir = workspace or MC_DIR
    max_notes = max(1, int(max_videos or 8))
    creator_id = ",".join(cleaned_targets)
    source_creator = cleaned_targets[0] if len(cleaned_targets) == 1 else ""
    source_keyword = f"target:{source_creator}" if source_creator else f"target:{len(cleaned_targets)}accounts"
    cmd = [
        sys.executable, "main.py",
        "--platform", mc_platform,
        "--type", "creator",
        "--creator_id", creator_id,
        "--get_comment", "true",
        "--save_data_option", "jsonl",
        "--crawler_max_notes_count", str(max_notes),
    ]

    log.info(
        "MediaCrawler target accounts: %s targets=%s max_videos=%s workspace=%s",
        platform,
        len(cleaned_targets),
        max_notes,
        mc_dir,
    )

    stdout_text, stderr_text = await _run_mediacrawler_process(cmd, mc_dir=mc_dir, platform=platform)
    comments = _parse_jsonl_comments(
        mc_dir=mc_dir,
        mc_platform=mc_platform,
        platform=platform,
        source_keyword=source_keyword,
        source_creator=source_creator,
        stdout_text=stdout_text,
        stderr_text=stderr_text,
    )
    log.info("MediaCrawler target accounts %s: %d comments parsed", platform, len(comments))
    return comments
