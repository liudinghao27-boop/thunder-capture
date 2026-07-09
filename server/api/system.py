"""System-level endpoints: health, readiness, and metadata."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from core.redis import get_redis_client, get_redis_url
from server.models import SessionLocal

logger = logging.getLogger("thunder.api.system")
router = APIRouter(prefix="/api/system", tags=["system"])


def _check_database() -> dict[str, Any]:
    """Check PostgreSQL/SQLite connectivity."""
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
            return {
                "status": "ok",
                "url": _mask_url(os.getenv("THUNDER_DATABASE_URL", "")),
            }
    except SQLAlchemyError as exc:
        logger.warning("Database health check failed: %s", exc)
        return {"status": "error", "detail": str(exc)}


def _check_redis() -> dict[str, Any]:
    """Check Redis connectivity (optional dependency)."""
    try:
        client = get_redis_client()
        if client is None:
            return {
                "status": "skipped",
                "detail": "Redis not configured or unreachable",
            }
        info = client.info(section="server") or {}
        return {
            "status": "ok",
            "url": _mask_url(get_redis_url()),
            "version": info.get("redis_version", "unknown"),
        }
    except (
        Exception
    ) as exc:  # pragma: no cover - Redis failures should not crash health endpoint
        logger.warning("Redis health check failed: %s", exc)
        return {"status": "error", "detail": str(exc)}


def _mask_url(url: str) -> str:
    """Redact credentials from database/Redis URLs for health responses."""
    if not url or "://" not in url:
        return url
    try:
        scheme, rest = url.split("://", 1)
        if "@" in rest:
            creds, hostpart = rest.split("@", 1)
            return f"{scheme}://***@{hostpart}"
    except ValueError:
        pass
    return url


@router.get("/live")
def liveness_check() -> dict[str, Any]:
    """Lightweight liveness probe for load balancers and orchestrators.

    Returns 200 if the API process is running. Individual dependency statuses
    are included in the response body so operators can see which component is
    unhealthy without causing the probe itself to fail.
    """
    db_status = _check_database()
    redis_status = _check_redis()

    all_ok = db_status.get("status") == "ok" and redis_status.get("status") in (
        "ok",
        "skipped",
    )

    return {
        "status": "healthy" if all_ok else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "0.2.0",
        "environment": os.getenv("THUNDER_ENV", "development"),
        "dependencies": {
            "database": db_status,
            "redis": redis_status,
        },
    }


@router.get("/info")
def system_info() -> dict[str, str]:
    """Public metadata about the running application."""
    return {
        "name": "Thunder Capture",
        "version": "0.2.0",
        "docs": "/docs",
    }
