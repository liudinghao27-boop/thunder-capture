"""Rate-limiting and security middleware for Thunder Capture API."""

import time
import threading
from collections import defaultdict, deque
from typing import Callable

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


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


# ── FastAPI middleware ──────────────────────────────────

class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP rate limiting middleware.

    Limits:
      - /api/auth/*     → 20 req/min (login/register)
      - /api/* (general) → 60 req/min
    """

    def __init__(self, app):
        super().__init__(app)
        self.auth_limiter = InMemoryRateLimiter(max_requests=20, window_seconds=60)
        self.general_limiter = InMemoryRateLimiter(max_requests=60, window_seconds=60)
        self.monitor_limiter = InMemoryRateLimiter(max_requests=120, window_seconds=60)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        method = request.method

        # Static files and GET status endpoints skip rate limiting
        if path.startswith("/static") or path == "/" or path == "/favicon.ico":
            return await call_next(request)

        # Get client IP (respect X-Forwarded-For if behind proxy)
        client_ip = (
            request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or request.client.host
            if request.client
            else "unknown"
        )

        # GET status/cancel-check endpoints — 60 req/min (sufficient for dashboard polling)
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

        response = await call_next(request)
        return response


# ── Security headers middleware ─────────────────────────

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add basic security headers to all responses."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Don't set HSTS here — let the reverse proxy (nginx/traefik) handle it
        return response
