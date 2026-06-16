"""RobotsTxtManager — robots.txt 合规检查，参考 Scrapling 设计"""

import logging

log = logging.getLogger("thunder.robotstxt")

# 已知平台的 robots.txt 位置
_ROBOTS_TXT_CACHE: dict[str, dict] = {}


def _fetch_robots_txt(domain: str) -> str:
    """同步获取 robots.txt 内容"""
    import requests  # noqa: F811

    robots_url = f"https://{domain}/robots.txt"
    try:
        resp = requests.get(robots_url, timeout=10, headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        })
        if resp.status_code == 200:
            return resp.text
    except Exception as e:
        log.debug(f"获取 robots.txt 失败 ({domain}): {e}")
    return ""


def _parse_robots_txt(content: str) -> dict:
    """简易 robots.txt 解析 — 提取 Crawl-delay 和 Disallow 规则。

    不依赖第三方库（protego），只提取我们需要的字段。
    """
    result = {"crawl_delay": None, "disallowed": []}
    for line in content.splitlines():
        line = line.strip().lower()
        if line.startswith("crawl-delay:"):
            try:
                result["crawl_delay"] = float(line.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif line.startswith("disallow:"):
            path = line.split(":", 1)[1].strip()
            if path:
                result["disallowed"].append(path)
    return result


def check_robots(domain: str, path: str = "/") -> dict:
    """检查给定域名和路径的 robots.txt 规则。

    Returns:
        {
            "allowed": bool,       # 是否允许访问
            "crawl_delay": float,  # 建议延迟（秒），None 表示无限制
            "disallowed": list,    # 禁止的路径列表
        }
    """
    if domain not in _ROBOTS_TXT_CACHE:
        content = _fetch_robots_txt(domain)
        _ROBOTS_TXT_CACHE[domain] = _parse_robots_txt(content)
        if content:
            log.info(f"robots.txt 已缓存: {domain}")
        else:
            log.debug(f"robots.txt 不可用，允许所有: {domain}")

    rules = _ROBOTS_TXT_CACHE[domain]

    # 检查 path 是否在 disallowed 列表中
    allowed = True
    for disallowed in rules["disallowed"]:
        if path.startswith(disallowed):
            allowed = False
            break

    return {
        "allowed": allowed,
        "crawl_delay": rules["crawl_delay"],
        "disallowed": rules["disallowed"],
    }


def get_crawl_delay(domain: str, default: float = 3.0) -> float:
    """获取域名的建议爬取延迟"""
    info = check_robots(domain)
    if info["crawl_delay"] is not None:
        return max(default, info["crawl_delay"])
    return default


def clear_cache():
    """清除 robots.txt 缓存（用于测试或手动刷新）"""
    _ROBOTS_TXT_CACHE.clear()
