"""Tests for server.middleware bug fixes."""

import time
from collections import deque
from unittest.mock import MagicMock

from server.middleware import (
    InMemoryRateLimiter,
    RateLimitMiddleware,
    RedisRateLimiter,
)


class FakeRedis:
    """Minimal Redis fake that supports the Lua script used by RedisRateLimiter."""

    def __init__(self):
        self._data: dict[str, dict[str, float]] = {}

    def eval(self, script, num_keys, key, window, now, max_requests, member):
        store = self._data.setdefault(key, {})
        cutoff = now - window
        for m, score in list(store.items()):
            if score < cutoff:
                del store[m]
        if len(store) < max_requests:
            store[member] = now
            return 1
        return 0

    def pipeline(self):
        pipe = MagicMock()
        calls = []

        def zremrangebyscore(k, min_score, max_score):
            calls.append(("zremrangebyscore", k, min_score, max_score))

        def zcard(k):
            calls.append(("zcard", k))

        pipe.zremrangebyscore = zremrangebyscore
        pipe.zcard = zcard

        def execute():
            # Apply the recorded calls against the fake store.
            result = []
            for call in calls:
                name, k, *rest = call
                if name == "zremrangebyscore":
                    min_score, max_score = rest
                    store = self._data.setdefault(k, {})
                    for m, score in list(store.items()):
                        if min_score <= score <= max_score:
                            del store[m]
                    result.append(0)
                elif name == "zcard":
                    result.append(len(self._data.get(k, {})))
            return result

        pipe.execute = execute
        return pipe


def test_rate_limiter_uses_deque():
    """InMemoryRateLimiter should store timestamps in a deque for O(1) popleft."""
    limiter = InMemoryRateLimiter(max_requests=3, window_seconds=60)
    limiter.is_allowed("key1")
    assert isinstance(limiter._buckets["key1"], deque)


def test_rate_limiter_allows_within_limit():
    limiter = InMemoryRateLimiter(max_requests=2, window_seconds=60)
    assert limiter.is_allowed("key1") is True
    assert limiter.is_allowed("key1") is True
    assert limiter.is_allowed("key1") is False


def test_rate_limiter_resets_after_window():
    limiter = InMemoryRateLimiter(max_requests=1, window_seconds=0.1)
    assert limiter.is_allowed("key1") is True
    assert limiter.is_allowed("key1") is False
    time.sleep(0.15)
    assert limiter.is_allowed("key1") is True


def test_remaining_returns_zero_when_blocked():
    limiter = InMemoryRateLimiter(max_requests=1, window_seconds=60)
    limiter.is_allowed("key1")
    assert limiter.remaining("key1") == 0


def test_redis_rate_limiter_allows_within_limit():
    redis_client = FakeRedis()
    limiter = RedisRateLimiter(redis_client, max_requests=2, window_seconds=60)
    assert limiter.is_allowed("ip1") is True
    assert limiter.is_allowed("ip1") is True
    assert limiter.is_allowed("ip1") is False


def test_redis_rate_limiter_remaining():
    redis_client = FakeRedis()
    limiter = RedisRateLimiter(redis_client, max_requests=3, window_seconds=60)
    assert limiter.remaining("ip1") == 3
    limiter.is_allowed("ip1")
    assert limiter.remaining("ip1") == 2
    limiter.is_allowed("ip1")
    limiter.is_allowed("ip1")
    assert limiter.remaining("ip1") == 0


def test_rate_limit_middleware_falls_back_when_redis_unavailable(monkeypatch):
    """Middleware should use InMemoryRateLimiter when no Redis client is provided and Redis is unreachable."""
    monkeypatch.setattr("server.middleware.get_redis_client", lambda: None)
    app = MagicMock()
    middleware = RateLimitMiddleware(app, redis_client=None)
    assert isinstance(middleware.auth_limiter, InMemoryRateLimiter)
    assert isinstance(middleware.general_limiter, InMemoryRateLimiter)
    assert isinstance(middleware.monitor_limiter, InMemoryRateLimiter)


def test_rate_limit_middleware_uses_redis_when_available():
    """Middleware should use RedisRateLimiter when a Redis client is provided."""
    app = MagicMock()
    redis_client = FakeRedis()
    middleware = RateLimitMiddleware(app, redis_client=redis_client)
    assert isinstance(middleware.auth_limiter, RedisRateLimiter)
    assert isinstance(middleware.general_limiter, RedisRateLimiter)
    assert isinstance(middleware.monitor_limiter, RedisRateLimiter)
