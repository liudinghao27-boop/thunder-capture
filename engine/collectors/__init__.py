"""Collector registry — maps platform slugs to collector classes."""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.collectors.base import BaseCollector

_registry: dict[str, type[BaseCollector]] = {}
_registry_loaded: bool = False


def register(platform: str):
    """Decorator: register a collector class for a platform slug."""

    def decorator(cls: type[BaseCollector]) -> type[BaseCollector]:
        _registry[platform] = cls
        return cls

    return decorator


def get_collector(platform: str) -> type[BaseCollector]:
    """Look up a collector class by platform slug."""
    if platform not in _registry:
        _discover_collectors()
    if platform not in _registry:
        available = ", ".join(sorted(_registry.keys()))
        raise ValueError(
            f"Unknown platform '{platform}'. Available: {available}"
        )
    return _registry[platform]


def list_platforms() -> list[str]:
    """Return all registered platform slugs."""
    _discover_collectors()
    return sorted(_registry.keys())


def _discover_collectors():
    """Import collector modules so @register decorators fire."""
    global _registry_loaded
    if _registry_loaded:
        return
    # Register built-in collectors
    from engine.collectors.douyin import DouyinCollector  # noqa: F401
    from engine.collectors.xiaohongshu import XHSCollector  # noqa: F401
    _registry_loaded = True
