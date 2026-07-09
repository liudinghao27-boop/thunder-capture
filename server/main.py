"""Thunder Capture SaaS — FastAPI entry point."""

import io
import logging
import sys
from pathlib import Path

# Ensure project root is on path for core imports
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "deps" / "crawl4ai"))  # Vendored Crawl4AI

if sys.platform == "win32":
    # Global UTF-8 — prevents subprocess/thread encoding crashes
    import os as _os

    _os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    _os.environ.setdefault("PYTHONUTF8", "1")
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name)
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            if hasattr(stream, "buffer"):
                setattr(
                    sys,
                    stream_name,
                    io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace"),
                )

# Setup logging for thunder package
from server.logging_config import setup_logging  # noqa: E402

logger = setup_logging()

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from server.config import CORS_ORIGINS  # noqa: E402
from server.errors import AppError, ErrorCode, serialize_error  # noqa: E402
from server.middleware import RateLimitMiddleware, SecurityHeadersMiddleware  # noqa: E402
from server.api import (  # noqa: E402
    agent,
    auth,
    dashboard,
    devices,
    industries,
    jobs,
    leads,
    stats,
    system,
)
import server.models  # noqa: F401,E402 — ensure model imports resolve
from server.models import Base, engine  # noqa: E402
from server.services.migrations import initialize_database  # noqa: E402

initialize_database(Base, engine)

app = FastAPI(title="Thunder Capture", version="0.2.0")
error_log = logging.getLogger("thunder.api.errors")

# Optional Prometheus metrics instrumentation (production dependency)
try:
    from prometheus_fastapi_instrumentator import Instrumentator

    Instrumentator().instrument(app).expose(app, endpoint="/api/system/metrics")
except Exception:  # pragma: no cover - optional dependency for local dev
    logger.info("Prometheus instrumentation not available; metrics endpoint disabled.")


def _request_correlation_id(request: Request) -> str:
    return (
        str(getattr(request.state, "correlation_id", "") or "")
        or request.headers.get("X-Request-ID", "")
        or request.headers.get("X-Correlation-ID", "")
    )


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    correlation_id = _request_correlation_id(request)
    return JSONResponse(
        status_code=exc.http_status,
        content=serialize_error(exc, correlation_id=correlation_id),
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    correlation_id = _request_correlation_id(request)
    error_log.exception("Unhandled request error correlation_id=%s", correlation_id)
    error = AppError(
        code=ErrorCode.INTERNAL_ERROR,
        message="Internal server error",
        detail="Unexpected server error",
        http_status=500,
    )
    return JSONResponse(
        status_code=500,
        content=serialize_error(error, correlation_id=correlation_id),
    )


# ── Security middleware (order matters: outermost first) ──
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)

if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    logger.warning(
        "CORS disabled. Set THUNDER_CORS_ORIGINS to enable cross-origin access."
    )

from fastapi.staticfiles import StaticFiles  # noqa: E402
from fastapi.responses import FileResponse, Response  # noqa: E402

# Ensure static folder exists
static_dir = BASE_DIR / "server" / "static"
static_dir.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

app.include_router(auth.router)
app.include_router(system.router)
app.include_router(dashboard.router)
app.include_router(agent.router)
app.include_router(leads.router)
app.include_router(industries.router)
app.include_router(devices.router)
app.include_router(jobs.router)
app.include_router(stats.router)

# Start auto-recovery background timer
from server.workers import start_auto_recovery  # noqa: E402

start_auto_recovery()


@app.get("/")
def root():
    return FileResponse(str(static_dir / "index.html"))


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)
