"""Thunder Capture SaaS — FastAPI entry point."""

import io
import sys
import logging
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
logger = logging.getLogger("thunder")
logger.setLevel(logging.INFO)
log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s")
if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(log_formatter)
    logger.addHandler(handler)

logs_dir = BASE_DIR / "logs"
logs_dir.mkdir(parents=True, exist_ok=True)
if not any(isinstance(h, logging.FileHandler) for h in logger.handlers):
    file_handler = logging.FileHandler(logs_dir / "thunder.log", encoding="utf-8")
    file_handler.setFormatter(log_formatter)
    logger.addHandler(file_handler)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.config import CORS_ORIGINS
from server.middleware import RateLimitMiddleware, SecurityHeadersMiddleware
from server.api import agent, auth, dashboard, devices, industries, jobs, leads, stats
import server.models  # noqa: F401 — ensure model imports resolve
from server.models import Base, engine
from server.services.migrations import initialize_database

initialize_database(Base, engine)

app = FastAPI(title="Thunder Capture", version="0.1.0")

# ── Security middleware (order matters: outermost first) ──
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Ensure static folder exists
static_dir = BASE_DIR / "server" / "static"
static_dir.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(agent.router)
app.include_router(leads.router)
app.include_router(industries.router)
app.include_router(devices.router)
app.include_router(jobs.router)
app.include_router(stats.router)

# Start auto-recovery background timer
from server.workers import start_auto_recovery
start_auto_recovery()


@app.get("/")
def root():
    return FileResponse(str(static_dir / "index.html"))
