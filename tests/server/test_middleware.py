"""Tests for server.middleware bug fixes."""

import time
from collections import deque

from server.middleware import InMemoryRateLimiter


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
