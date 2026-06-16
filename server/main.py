"""Thunder Capture SaaS — FastAPI entry point."""

import sys
from pathlib import Path

# Ensure project root is on path for engine imports
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.api import auth, devices, industries, stats
import server.models  # noqa: F401 — ensure model imports resolve
from server.models import Base, engine

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Thunder Capture", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(industries.router)
app.include_router(devices.router)
app.include_router(stats.router)


@app.get("/")
def root():
    return {"service": "Thunder Capture API", "version": "0.1.0"}
