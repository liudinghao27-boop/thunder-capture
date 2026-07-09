"""MediaCrawler subprocess runner.

Extracted from core/discover.py to provide a clean adapter interface.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import time
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
_DEFAULT_PROCESS_TIMEOUT_SECONDS = 90
_ASCII_ACCOUNT_RE = re.compile(r"^[\x21-\x7e]+$")

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


class MediaCrawlerProcessError(RuntimeError):
    """MediaCrawler exited unsuccessfully, possibly after writing JSONL output."""

    def __init__(
        self,
        message: str,
        *,
        workspace: Path,
        stdout_text: str = "",
        stderr_text: str = "",
    ) -> None:
        super().__init__(message)
        self.workspace = workspace
        self.stdout_text = stdout_text
        self.stderr_text = stderr_text


class MediaCrawlerTimeoutError(TimeoutError):
    """MediaCrawler timed out, with workspace retained for partial-output parsing."""

    def __init__(
        self,
        message: str,
        *,
        workspace: Path,
        stdout_text: str = "",
        stderr_text: str = "",
    ) -> None:
        super().__init__(message)
        self.workspace = workspace
        self.stdout_text = stdout_text
        self.stderr_text = stderr_text


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
    max_notes: int = 0,
    cookie_path: Path | None = None,
) -> None:
    """Update a MediaCrawler base_config.py copy with runtime settings.

    Args:
        base_config_path: Path to the isolated ``base_config.py`` to rewrite.
        cdp_port: Chrome DevTools Protocol port (0 = leave unchanged).
        max_comments: Max comments per post.
        max_notes: Max videos/posts per author or creator (0 = leave unchanged).
        cookie_path: Optional path to a Playwright-style cookies JSON file.
            When provided, LOGIN_TYPE is switched to "cookie" and the cookies
            file is referenced from the isolated workspace.
    """
    if not base_config_path.exists():
        raise FileNotFoundError(f"MediaCrawler config not found at {base_config_path}")

    workspace = base_config_path.parent.parent
    cookies_in_workspace: Path | None = None
    log.info(
        "[configure_mediacrawler] workspace=%s cookie_path=%s exists=%s",
        workspace,
        cookie_path,
        bool(cookie_path and cookie_path.exists()),
    )
    if cookie_path and cookie_path.exists():
        target = workspace / "cookies.json"
        shutil.copy(str(cookie_path), str(target))
        cookies_in_workspace = target
        log.info("[configure_mediacrawler] copied cookies to %s", target)

    with open(base_config_path, "r", encoding="utf-8") as f:
        content = f.read()

    content = re.sub(
        r'SAVE_DATA_OPTION\s*=\s*".*?"', 'SAVE_DATA_OPTION = "jsonl"', content
    )
    content = re.sub(
        r"ENABLE_GET_COMMENTS\s*=\s*(True|False)", "ENABLE_GET_COMMENTS = True", content
    )
    content = re.sub(
        r"CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES\s*=\s*\d+",
        f"CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES = {max_comments}",
        content,
    )
    if max_notes > 0:
        content = re.sub(
            r"CRAWLER_MAX_NOTES_COUNT\s*=\s*\d+",
            f"CRAWLER_MAX_NOTES_COUNT = {max_notes}",
            content,
        )
    content = re.sub(
        r"ENABLE_CDP_MODE\s*=\s*(True|False)", "ENABLE_CDP_MODE = True", content
    )

    # When a CDP port is supplied, instruct MediaCrawler to connect to an
    # existing browser on that port (launched by the caller, e.g. ShadowBrowser).
    # The hard-coded /devtools/browser endpoint was fixed in cdp_browser.py to
    # fetch the real WebSocket URL from /json/version, so this works on current
    # Chrome versions.
    if cdp_port > 0:
        content = re.sub(
            r"CDP_CONNECT_EXISTING\s*=\s*(True|False)",
            "CDP_CONNECT_EXISTING = True",
            content,
        )
        log.info(
            "[configure_mediacrawler] Set CDP_CONNECT_EXISTING=True for port %s",
            cdp_port,
        )
    else:
        log.info(
            "[configure_mediacrawler] cdp_port=%s, leaving CDP_CONNECT_EXISTING unchanged",
            cdp_port,
        )

    # Prefer cookie login when a cookie file is available to avoid QR-code
    # login timeouts in unattended environments.
    if cookies_in_workspace:
        content = re.sub(r'LOGIN_TYPE\s*=\s*".*?"', 'LOGIN_TYPE = "cookie"', content)
        # Escape backslashes in the Windows path for the generated Python string.
        cookie_ref = str(cookies_in_workspace).replace("\\", "/")
        content = re.sub(r'COOKIES\s*=\s*".*?"', f'COOKIES = "{cookie_ref}"', content)
        log.info("[configure_mediacrawler] set COOKIES=%s", cookie_ref)

    if cdp_port > 0:
        content = re.sub(
            r"CDP_DEBUG_PORT\s*=\s*\d+", f"CDP_DEBUG_PORT = {cdp_port}", content
        )

    # When a proxy pool is configured, inject it into MediaCrawler so that
    # browser and HTTP requests are routed through residential IPs. This helps
    # bypass platform-level IP/risk control. The static proxy URL is expected to
    # point to the local proxy pool server (e.g. http://127.0.0.1:3128).
    proxy_url = os.environ.get("THUNDER_MEDIACRAWLER_PROXY_URL", "")
    if proxy_url:
        content = re.sub(
            r"ENABLE_IP_PROXY\s*=\s*(True|False)", "ENABLE_IP_PROXY = True", content
        )
        content = re.sub(
            r"IP_PROXY_PROVIDER_NAME\s*=\s*\".*?\"",
            'IP_PROXY_PROVIDER_NAME = "static"',
            content,
        )
        content = re.sub(
            r'STATIC_PROXY_URL\s*=\s*".*?"',
            f'STATIC_PROXY_URL = "{proxy_url}"',
            content,
        )

    with open(base_config_path, "w", encoding="utf-8") as f:
        f.write(content)


def _mediacrawler_timeout_seconds() -> float:
    raw = os.getenv("THUNDER_MEDIACRAWLER_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return float(_DEFAULT_PROCESS_TIMEOUT_SECONDS)
    try:
        return max(float(raw), 1.0)
    except ValueError:
        log.warning(
            "Invalid THUNDER_MEDIACRAWLER_TIMEOUT_SECONDS=%r; using %ss",
            raw,
            _DEFAULT_PROCESS_TIMEOUT_SECONDS,
        )
        return float(_DEFAULT_PROCESS_TIMEOUT_SECONDS)


def _valid_target_account_id(value: str) -> bool:
    text = value.strip()
    if not text or any(ch.isspace() for ch in text):
        return False
    # MediaCrawler creator mode expects a platform account identifier or URL,
    # not an audience description such as "关注征兵的人".
    # We allow any non-empty, non-whitespace-only string that has at least
    # one ASCII alphanumeric character or looks like a URL, so real URLs and
    # sec_user_ids are accepted while plain Chinese descriptions are rejected.
    if text.startswith("http://") or text.startswith("https://"):
        return True
    if re.search(r"[a-zA-Z0-9]", text):
        return True
    return False


def _keep_failed_workspace(mc_dir: Path, reason: str) -> Path:
    """Preserve a failed workspace for post-mortem analysis.

    Moves the temporary workspace to a deterministic debug directory so logs
    and JSONL outputs are not lost when a subprocess fails or times out. The
    shared MediaCrawler source tree is never moved.
    """
    if str(mc_dir) == str(MC_DIR):
        log.warning("Shared MediaCrawler directory failed, not moving: %s", mc_dir)
        return mc_dir
    debug_dir = BASE_DIR / "data" / "mc_failures"
    debug_dir.mkdir(parents=True, exist_ok=True)
    timestamp = int(time.time())
    target = debug_dir / f"{mc_dir.name}_{timestamp}_{reason}"
    try:
        shutil.move(str(mc_dir), str(target))
        log.warning("Preserved failed MediaCrawler workspace: %s", target)
        return target
    except Exception as exc:
        log.error("Failed to preserve workspace %s: %s", mc_dir, exc)
        return mc_dir


def _decode_process_output(data: bytes) -> str:
    """Decode subprocess output from common Windows/Python encodings."""
    if not data:
        return ""
    for encoding in ("utf-8", "gb18030"):
        try:
            return data.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace").strip()


async def _run_mediacrawler_process_with_retry(
    cmd: list[str],
    *,
    mc_dir: Path,
    platform: str,
    timeout_seconds: float | None = None,
    max_retries: int = 1,
    configure_kwargs: dict | None = None,
    preserve_failed_workspace: bool = True,
) -> tuple[str, str]:
    """Run MediaCrawler with optional retry and workspace preservation on failure.

    On failure the workspace is moved to ``data/mc_failures/`` for post-mortem
    analysis.  When ``mc_dir`` is an isolated, self-prepared workspace (not the
    shared ``deps/MediaCrawler`` directory), retries are performed by creating a
    fresh workspace copy from the original MediaCrawler tree.  This avoids
    reusing a corrupted failed workspace state.
    """
    last_error: Exception | None = None
    original_mc_dir = mc_dir
    configure_kwargs = configure_kwargs or {}
    for attempt in range(max_retries + 1):
        # Re-configure the workspace at the start of every attempt. On retry,
        # a fresh workspace copy is prepared and must be re-injected with runtime
        # settings (cookie login, proxy, CDP port, etc.).
        base_config_path = mc_dir / "config" / "base_config.py"
        log.info(
            "[_run_mediacrawler_process_with_retry] attempt=%d mc_dir=%s configure_kwargs=%r",
            attempt,
            mc_dir,
            configure_kwargs,
        )
        if base_config_path.exists():
            configure_mediacrawler(base_config_path, **configure_kwargs)
            cfg_lines = base_config_path.read_text(encoding="utf-8").splitlines()
            for line in cfg_lines:
                if "CDP_CONNECT_EXISTING" in line or "CDP_DEBUG_PORT" in line:
                    log.info(
                        "[_run_mediacrawler_process_with_retry] config line: %s",
                        line.strip(),
                    )
        else:
            log.warning(
                "[_run_mediacrawler_process_with_retry] base_config.py not found at %s",
                base_config_path,
            )

        try:
            return await _run_mediacrawler_process(
                cmd, mc_dir=mc_dir, platform=platform, timeout_seconds=timeout_seconds
            )
        except (MediaCrawlerTimeoutError, MediaCrawlerProcessError) as exc:
            last_error = exc
            reason = "timeout" if isinstance(exc, TimeoutError) else "error"
            preserved_dir = mc_dir
            if preserve_failed_workspace:
                preserved_dir = _keep_failed_workspace(
                    mc_dir, f"{reason}_attempt{attempt}"
                )
                exc.workspace = preserved_dir
            if attempt < max_retries:
                log.warning(
                    "MediaCrawler %s failed on attempt %d, retrying... (preserved %s)",
                    platform,
                    attempt,
                    preserved_dir,
                )
                # Re-prepare a fresh workspace from the original MediaCrawler tree.
                # If the caller supplied an external workspace, we cannot safely
                # recreate it; abort retries early.
                if str(original_mc_dir) == str(MC_DIR):
                    log.warning(
                        "MediaCrawler %s uses shared workspace, no retry workspace recreation possible.",
                        platform,
                    )
                    raise last_error
                try:
                    mc_dir = prepare_mediacrawler_workspace()
                except Exception as prep_exc:
                    log.error(
                        "Failed to re-prepare MediaCrawler workspace: %s", prep_exc
                    )
                    raise last_error from prep_exc
            else:
                log.error(
                    "MediaCrawler %s failed after %d attempts, giving up.",
                    platform,
                    max_retries + 1,
                )
                raise last_error
    raise last_error or RuntimeError("Unexpected empty retry loop")


async def _run_mediacrawler_process(
    cmd: list[str],
    *,
    mc_dir: Path,
    platform: str,
    timeout_seconds: float | None = None,
) -> tuple[str, str]:
    timeout = float(timeout_seconds or _mediacrawler_timeout_seconds())
    started_at = asyncio.get_running_loop().time()
    process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(mc_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError as exc:
        elapsed = asyncio.get_running_loop().time() - started_at
        process.kill()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except Exception:
            log.warning(
                "MediaCrawler %s process did not exit cleanly after kill", platform
            )
        message = (
            f"MediaCrawler {platform} timed out after {timeout:.0f}s "
            f"(elapsed={elapsed:.1f}s, workspace={mc_dir}, cmd={' '.join(cmd)})"
        )
        log.error(message)
        raise MediaCrawlerTimeoutError(message, workspace=mc_dir) from exc
    stdout_text = _decode_process_output(stdout)
    stderr_text = _decode_process_output(stderr)

    if process.returncode != 0:
        raise MediaCrawlerProcessError(
            f"MediaCrawler {platform} failed: {stderr_text[-2000:]}",
            workspace=mc_dir,
            stdout_text=stdout_text,
            stderr_text=stderr_text,
        )

    log.info(
        "MediaCrawler %s exited in %.1fs workspace=%s stdout_tail=%r stderr_tail=%r",
        platform,
        asyncio.get_running_loop().time() - started_at,
        mc_dir,
        stdout_text[-_LOG_TAIL_CHARS:],
        stderr_text[-_LOG_TAIL_CHARS:],
    )
    return stdout_text, stderr_text


def _log_empty_output(
    reason: str,
    *,
    platform: str,
    mc_dir: Path,
    stdout_text: str,
    stderr_text: str,
) -> None:
    output_roots = (
        [
            str(path.relative_to(mc_dir))
            for path in (mc_dir / "data").rglob("*")
            if path.is_file()
        ]
        if (mc_dir / "data").exists()
        else []
    )
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
    delete_after_parse: bool = True,
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

    if delete_after_parse:
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


def _parse_partial_jsonl_comments_from_failure(
    exc: MediaCrawlerProcessError | MediaCrawlerTimeoutError,
    *,
    mc_platform: str,
    platform: str,
    source_keyword: str,
    source_creator: str = "",
) -> list[dict]:
    comments = _parse_jsonl_comments(
        mc_dir=exc.workspace,
        mc_platform=mc_platform,
        platform=platform,
        source_keyword=source_keyword,
        source_creator=source_creator,
        stdout_text=exc.stdout_text,
        stderr_text=exc.stderr_text,
        delete_after_parse=False,
    )
    if comments:
        log.warning(
            "MediaCrawler %s failed after producing %d JSONL comments; "
            "salvaging partial output from %s. error=%s",
            platform,
            len(comments),
            exc.workspace,
            str(exc)[-_LOG_TAIL_CHARS:],
        )
    return comments


async def run_platform(
    platform: str,
    keywords: list[str],
    *,
    max_authors: int = 12,
    workspace: Path | None = None,
    target_users: list[str] | None = None,
    cdp_port: int = 61850,
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
        cdp_port: Chrome DevTools Protocol port. Use 0 to let MediaCrawler
            launch its own browser on a default port. A positive value means
            MediaCrawler should connect to an existing browser on that port
            (e.g. one started by ShadowBrowser).

    Returns:
        List of comment dicts ready for classification.
    """
    mc_platform = PLATFORM_MAP.get(platform, "dy")
    keywords_str = ",".join(keywords)
    # Create an isolated workspace when the caller does not provide one. This
    # keeps per-job JSONL output separate and avoids mutating the shared
    # deps/MediaCrawler tree.
    mc_dir = workspace
    if mc_dir is None:
        mc_dir = prepare_mediacrawler_workspace()
    cleaned_targets = [str(u).strip() for u in (target_users or []) if str(u).strip()]

    cmd = [
        sys.executable,
        "main.py",
        "--platform",
        mc_platform,
        "--type",
        "search",
        "--keywords",
        keywords_str,
        "--headless",
        "true",
    ]

    log.info(
        "MediaCrawler: %s keywords=%s targets=%s workspace=%s",
        platform,
        keywords_str,
        len(cleaned_targets),
        mc_dir,
    )

    configure_kwargs = {
        "max_comments": 50,
        "max_notes": 8,
        "cdp_port": cdp_port,
        "cookie_path": BASE_DIR / "data" / "douyin_cookies.json",
    }
    log.info(
        "[run_platform] cdp_port=%s configure_kwargs=%r", cdp_port, configure_kwargs
    )
    try:
        stdout_text, stderr_text = await _run_mediacrawler_process_with_retry(
            cmd,
            mc_dir=mc_dir,
            platform=platform,
            max_retries=1,
            configure_kwargs=configure_kwargs,
            preserve_failed_workspace=workspace is None,
        )
        comments = _parse_jsonl_comments(
            mc_dir=mc_dir,
            mc_platform=mc_platform,
            platform=platform,
            source_keyword=keywords_str,
            stdout_text=stdout_text,
            stderr_text=stderr_text,
        )
    except (MediaCrawlerProcessError, MediaCrawlerTimeoutError) as exc:
        comments = _parse_partial_jsonl_comments_from_failure(
            exc,
            mc_platform=mc_platform,
            platform=platform,
            source_keyword=keywords_str,
        )
        if not comments:
            raise

    log.info("MediaCrawler %s: %d comments parsed", platform, len(comments))
    return comments


async def run_target_accounts(
    platform: str,
    target_users: list[str],
    *,
    keywords: list[str] | None = None,
    max_videos: int | None = None,
    workspace: Path | None = None,
    cdp_port: int = 61850,
) -> list[dict]:
    """Collect comments from configured target accounts.

    This is a stable adapter boundary. Platform-specific account crawling can
    replace this fallback later without changing discovery, classification, or
    queue insertion.

    Args:
        cdp_port: Chrome DevTools Protocol port. Use 0 to let MediaCrawler
            launch its own browser; a positive value connects to an existing
            browser on that port.
    """
    cleaned_targets = []
    invalid_targets = []
    seen = set()
    for target in target_users or []:
        value = str(target).strip()
        if not value or value in seen:
            continue
        if not _valid_target_account_id(value):
            invalid_targets.append(value)
            continue
        seen.add(value)
        cleaned_targets.append(value)

    if invalid_targets:
        log.warning(
            "Ignored invalid target account identifiers for %s: %s",
            platform,
            invalid_targets[:10],
        )

    if not cleaned_targets:
        log.warning(
            "No valid target account identifiers for %s; skip target account collection",
            platform,
        )
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

    # Create an isolated workspace when the caller does not provide one.
    mc_dir = workspace
    if mc_dir is None:
        mc_dir = prepare_mediacrawler_workspace()
    max_notes = max(1, int(max_videos or 8))
    creator_id = ",".join(cleaned_targets)
    source_creator = cleaned_targets[0] if len(cleaned_targets) == 1 else ""
    source_keyword = (
        f"target:{source_creator}"
        if source_creator
        else f"target:{len(cleaned_targets)}accounts"
    )
    cmd = [
        sys.executable,
        "main.py",
        "--platform",
        mc_platform,
        "--type",
        "creator",
        "--creator_id",
        creator_id,
        "--get_comment",
        "true",
        "--save_data_option",
        "jsonl",
        "--crawler_max_notes_count",
        str(max_notes),
        "--headless",
        "true",
    ]

    log.info(
        "MediaCrawler target accounts: %s targets=%s max_videos=%s workspace=%s",
        platform,
        len(cleaned_targets),
        max_notes,
        mc_dir,
    )

    configure_kwargs = {
        "max_comments": 50,
        "max_notes": max_notes,
        "cdp_port": cdp_port,
        "cookie_path": BASE_DIR / "data" / "douyin_cookies.json",
    }
    try:
        stdout_text, stderr_text = await _run_mediacrawler_process_with_retry(
            cmd,
            mc_dir=mc_dir,
            platform=platform,
            max_retries=1,
            configure_kwargs=configure_kwargs,
            preserve_failed_workspace=workspace is None,
        )
        comments = _parse_jsonl_comments(
            mc_dir=mc_dir,
            mc_platform=mc_platform,
            platform=platform,
            source_keyword=source_keyword,
            source_creator=source_creator,
            stdout_text=stdout_text,
            stderr_text=stderr_text,
        )
    except (MediaCrawlerProcessError, MediaCrawlerTimeoutError) as exc:
        comments = _parse_partial_jsonl_comments_from_failure(
            exc,
            mc_platform=mc_platform,
            platform=platform,
            source_keyword=source_keyword,
            source_creator=source_creator,
        )
        if not comments:
            raise
    log.info(
        "MediaCrawler target accounts %s: %d comments parsed", platform, len(comments)
    )
    return comments
