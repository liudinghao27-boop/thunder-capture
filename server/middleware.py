"""Rate-limiting and security middleware for Thunder Capture API."""

import logging
import threading
import time
import uuid
from collections import defaultdict, deque
from typing import Callable, cast

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from core.redis import get_redis_client

logger = logging.getLogger("thunder.middleware")


class InMemoryRateLimiter:
    """Simple sliding-window rate limiter (no Redis dependency).

    Suitable for single-process deployments. For multi-worker deployments,
    replace with Redis-backed rate limiter.
    """

    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._buckets: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._last_cleanup = time.monotonic()

    def _cleanup_old_locked(self, now: float):
        """Periodically purge expired entries to prevent memory leak. Caller must hold _lock."""
        if now - self._last_cleanup < 300:  # every 5 minutes
            return
        cutoff = now - self.window_seconds
        expired = [k for k, v in self._buckets.items()
                  if not v or v[-1] < cutoff]
        for k in expired:
            del self._buckets[k]
        # If still too many, clear everything
        if len(self._buckets) > 10000:
            self._buckets.clear()
        self._last_cleanup = now

    def is_allowed(self, key: str) -> bool:
        """Check if request is within rate limit. Thread-safe."""
        now = time.monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            self._cleanup_old_locked(now)
            bucket = self._buckets[key]
            # Remove expired timestamps
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self.max_requests:
                return False
            bucket.append(now)
            return True

    def remaining(self, key: str) -> int:
        """Return remaining requests in current window."""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            bucket = self._buckets[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            return max(0, self.max_requests - len(bucket))


class RedisRateLimiter:
    """Redis-backed sliding-window rate limiter.

    Shares state across API workers so a single client cannot exceed limits by
    hitting different processes. Falls back to the in-memory implementation when
    Redis is unavailable.
    """

    _ALLOW_SCRIPT = """
    local key = KEYS[1]
    local window = tonumber(ARGV[1])
    local now = tonumber(ARGV[2])
    local max_requests = tonumber(ARGV[3])
    local member = ARGV[4]
    local cutoff = now - window

    redis.call('ZREMRANGEBYSCORE', key, 0, cutoff)
    local count = redis.call('ZCARD', key)
    if count < max_requests then
        redis.call('ZADD', key, now, member)
        redis.call('EXPIRE', key, window)
        return 1
    else
        return 0
    end
    """

    def __init__(self, redis_client, max_requests: int = 60, window_seconds: int = 60):
        self._redis = redis_client
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    def _key(self, key: str) -> str:
        return f"thunder:ratelimit:{self.window_seconds}:{key}"

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        member = f"{now}:{uuid.uuid4().hex}"
        result = self._redis.eval(
            self._ALLOW_SCRIPT,
            1,
            self._key(key),
            self.window_seconds,
            now,
            self.max_requests,
            member,
        )
        return bool(result)

    def remaining(self, key: str) -> int:
        k = self._key(key)
        now = time.time()
        cutoff = now - self.window_seconds
        pipe = self._redis.pipeline()
        pipe.zremrangebyscore(k, 0, cutoff)
        pipe.zcard(k)
        results = pipe.execute()
        count = cast(int, results[1])
        return max(0, self.max_requests - count)


def _make_limiter(redis_client, max_requests: int, window_seconds: int):
    """Build the best available limiter for the current environment."""
    if redis_client is not None:
        return RedisRateLimiter(redis_client, max_requests, window_seconds)
    return InMemoryRateLimiter(max_requests, window_seconds)


# ── FastAPI middleware ──────────────────────────────────

class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP rate limiting middleware.

    Limits:
      - /api/auth/*     → 20 req/min (login/register)
      - /api/* (general) → 60 req/min
      - polling/status endpoints → 120 req/min

    Uses Redis when ``THUNDER_REDIS_URL``/``REDIS_URL`` is reachable, otherwise
    falls back to an in-memory limiter.
    """

    def __init__(self, app, redis_client=None):
        super().__init__(app)
        if redis_client is None:
            redis_client = get_redis_client()
        if redis_client is None:
            logger.info("Rate limiting: Redis unavailable, using in-memory limiter.")
        else:
            logger.info("Rate limiting: using Redis-backed limiter.")
        self.auth_limiter = _make_limiter(redis_client, 20, 60)
        self.general_limiter = _make_limiter(redis_client, 60, 60)
        self.monitor_limiter = _make_limiter(redis_client, 120, 60)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        method = request.method

        # Static files and GET status endpoints skip rate limiting
        if path.startswith("/static") or path == "/" or path == "/favicon.ico":
            return cast(Response, await call_next(request))

        # Get client IP (respect X-Forwarded-For if behind proxy)
        client_ip = (
            request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or request.client.host
            if request.client
            else "unknown"
        )

        # GET status/cancel-check endpoints — higher limit for dashboard polling
        if method == "GET" and (
            path.startswith("/api/jobs")
            or path.startswith("/api/stats")
            or path.startswith("/api/devices")
            or path.startswith("/api/dashboard")
            or path.startswith("/api/tasks/status")
        ):
            limiter = self.monitor_limiter
        # Select limiter based on path
        elif path.startswith("/api/auth"):
            limiter = self.auth_limiter
        else:
            limiter = self.general_limiter

        if not limiter.is_allowed(client_ip):
            retry_after = limiter.window_seconds
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Too many requests. Please slow down."},
                headers={"Retry-After": str(retry_after)},
            )

        response = cast(Response, await call_next(request))
        return response


# ── Security headers middleware ─────────────────────────

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add basic security headers to all responses."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = cast(Response, await call_next(request))
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Don't set HSTS here — let the reverse proxy (nginx/traefik) handle it
        return response
