"""robots.txt compliance helper."""

from __future__ import annotations

import logging
import time
from typing import TypedDict, cast

log = logging.getLogger("thunder.robotstxt")

_ROBOTS_CACHE_TTL_SECONDS = 6 * 60 * 60
_ROBOTS_TXT_CACHE: dict[str, tuple[float, "RobotsRules"]] = {}


class RobotsRules(TypedDict):
    crawl_delay: float | None
    disallowed: list[str]
    fetch_error: bool


def _fetch_robots_txt(domain: str) -> str | None:
    """Fetch robots.txt; return None when access cannot be verified."""
    import requests

    robots_url = f"https://{domain}/robots.txt"
    try:
        resp = requests.get(
            robots_url,
            timeout=10,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            },
        )
        if resp.status_code == 200:
            return cast(str, resp.text)
        if resp.status_code in (401, 403, 429) or resp.status_code >= 500:
            log.warning(
                "robots.txt unavailable for %s: HTTP %s", domain, resp.status_code
            )
            return None
    except requests.RequestException as exc:
        log.warning("robots.txt fetch failed for %s: %s", domain, exc)
        return None
    return ""


def _parse_robots_txt(content: str) -> RobotsRules:
    crawl_delay: float | None = None
    disallowed: list[str] = []
    for line in content.splitlines():
        line = line.strip().lower()
        if line.startswith("crawl-delay:"):
            try:
                crawl_delay = float(line.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif line.startswith("disallow:"):
            path = line.split(":", 1)[1].strip()
            if path:
                disallowed.append(path)
    return {"crawl_delay": crawl_delay, "disallowed": disallowed, "fetch_error": False}


def _cache_entry_valid(entry: tuple[float, RobotsRules] | None) -> bool:
    if entry is None:
        return False
    cached_at, _ = entry
    return time.time() - cached_at < _ROBOTS_CACHE_TTL_SECONDS


def check_robots(
    domain: str, path: str = "/"
) -> dict[str, bool | float | None | list[str]]:
    """Check whether a path is allowed by robots.txt.

    Network errors and blocking status codes deny by default. That is safer
    than treating an unavailable robots.txt as a blanket allow.
    """
    entry = _ROBOTS_TXT_CACHE.get(domain)
    if not _cache_entry_valid(entry):
        content = _fetch_robots_txt(domain)
        rules: RobotsRules
        if content is None:
            rules = {"crawl_delay": None, "disallowed": ["/"], "fetch_error": True}
            log.warning("robots.txt unavailable; denying by default for %s", domain)
        else:
            rules = _parse_robots_txt(content)
            if content:
                log.info("robots.txt cached for %s", domain)
            else:
                log.debug("robots.txt absent for %s; allowing by default", domain)
        _ROBOTS_TXT_CACHE[domain] = (time.time(), rules)

    rules = _ROBOTS_TXT_CACHE[domain][1]
    allowed = True
    for disallowed in rules["disallowed"]:
        if path.startswith(disallowed):
            allowed = False
            break

    return {
        "allowed": allowed,
        "crawl_delay": rules["crawl_delay"],
        "disallowed": rules["disallowed"],
        "fetch_error": rules["fetch_error"],
    }


def get_crawl_delay(domain: str, default: float = 3.0) -> float:
    info = check_robots(domain)
    crawl_delay = info["crawl_delay"]
    if isinstance(crawl_delay, (int, float)):
        return max(default, float(crawl_delay))
    return default


def clear_cache() -> None:
    _ROBOTS_TXT_CACHE.clear()
