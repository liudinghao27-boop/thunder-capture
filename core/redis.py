"""Shared Redis helpers for broker, backend, caching, and rate limiting."""

import logging
import os
from typing import Any

try:
    import redis
except ImportError:  # pragma: no cover
    redis = None  # type: ignore[assignment]

logger = logging.getLogger("thunder.redis")


def get_redis_url() -> str:
    """Return the canonical Redis URL.

    ``THUNDER_REDIS_URL`` takes precedence over the legacy ``REDIS_URL``.
    """
    url = os.getenv("THUNDER_REDIS_URL")
    if not url:
        url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return url


def get_redis_client(**kwargs: Any) -> Any | None:
    """Create a Redis client and verify connectivity.

    Returns ``None`` when Redis is not installed or unreachable so callers can
    fall back to in-memory implementations.
    """
    if redis is None:
        logger.warning("redis package not installed; falling back to in-memory.")
        return None

    url = get_redis_url()
    try:
        client = redis.Redis.from_url(url, decode_responses=True, **kwargs)
        client.ping()
        return client
    except redis.exceptions.ConnectionError as e:
        logger.warning("Redis unavailable at %s: %s. Falling back to in-memory.", url, e)
        return None
