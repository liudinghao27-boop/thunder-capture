"""Celery application configuration.

Usage:
    celery -A adapters.celery.app worker -l info -Q collect,classify,send -c 4
"""

from __future__ import annotations

import os
from celery import Celery

# Redis URL — default for local dev
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

app = Celery(
    "thunder",
    broker=REDIS_URL,
    backend=REDIS_URL,  # Store results in Redis too
    include=[
        "adapters.celery.collect",
        "adapters.celery.classify",
        "adapters.celery.send",
    ],
)

# ── Celery config ──
app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,  # Re-deliver on worker crash
    worker_prefetch_multiplier=1,  # One task at a time per worker
    task_queues={
        "collect": {"exchange": "thunder", "routing_key": "collect"},
        "classify": {"exchange": "thunder", "routing_key": "classify"},
        "send": {"exchange": "thunder", "routing_key": "send"},
    },
    task_routes={
        "adapters.celery.collect.*": {"queue": "collect"},
        "adapters.celery.classify.*": {"queue": "classify"},
        "adapters.celery.send.*": {"queue": "send"},
    },
    # ── Retry policy ──
    task_default_retry_delay=60,  # 1 min base
    task_max_retries=5,
    task_retry_backoff=True,  # Exponential: 1m, 2m, 4m, 8m, 16m
    task_retry_backoff_max=1800,  # Cap at 30 min
)
