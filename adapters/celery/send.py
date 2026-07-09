"""Celery tasks: DM sending pipeline.

Migration path from core/task/worker.py DeviceWorker.run():
  1. Replace threading.Thread per device with Celery worker per device
  2. Each device gets its own task queue (rate-limited)
  3. Built-in retry with exponential backoff replaces manual sleep loops
"""

from __future__ import annotations

import logging

from adapters.celery.app import app
from core.constants import DEFAULT_DAILY_LIMIT, DEFAULT_MIN_INTERVAL_SEC

log = logging.getLogger("thunder.celery.send")


@app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=90,  # 1.5 min base
    soft_time_limit=600,  # 10 min per device session
    # Per-device rate limiting is enforced inside DeviceWorker via min_interval
    # and daily_limit. A global Celery rate_limit would throttle the whole
    # cluster, so we intentionally do not set it here.
)
def send_dm_task(
    self,
    device_id: str,
    adb_serial: str,
    industry_slug: str,
    user_id: str,
    task_data: dict,
    reply_msg: str,
):
    """Run one device sending session via DeviceWorker.

    Replaces the per-device threading loop in core/task/worker.py.
    Celery handles concurrency, retry and rate limiting.
    """
    from server.models import SessionLocal
    from server.models.industry import Industry
    from server.api.industries import _to_industry_config

    db = SessionLocal()
    try:
        industry = (
            db.query(Industry)
            .filter(
                Industry.slug == industry_slug,
                Industry.user_id == user_id,
            )
            .first()
        )
        if not industry:
            return {"ok": False, "error": f"Industry {industry_slug} not found"}
        if industry.compliance_mode:
            log.info(
                "Compliance mode enabled for %s; skipping Celery DM send.",
                industry_slug,
            )
            return {"ok": True, "skipped": True, "reason": "compliance_mode"}
        cfg = _to_industry_config(industry)
    finally:
        db.close()

    def should_stop():
        # Celery best-effort abort signal
        is_aborted = getattr(self, "is_aborted", None)
        return bool(is_aborted and is_aborted())

    from core.task.worker import DeviceWorker

    worker = DeviceWorker(
        device_id=device_id,
        adb_serial=adb_serial,
        industry=cfg,
        daily_limit=task_data.get(
            "daily_limit", cfg.daily_limit or DEFAULT_DAILY_LIMIT
        ),
        min_interval=task_data.get("min_interval_sec", DEFAULT_MIN_INTERVAL_SEC),
        should_stop=should_stop,
        job_id=task_data.get("job_id", ""),
    )

    log.info(
        "DeviceWorker session started: device=%s industry=%s", device_id, industry_slug
    )
    summary = worker.run()
    log.info("DeviceWorker session finished: device=%s summary=%s", device_id, summary)
    return summary


@app.task(bind=True, max_retries=1)
def run_send_batch(
    self, industry_slug: str, user_id: str, device_ids: list[str] | None = None
):
    """Orchestrate batch sending across multiple devices using DB config."""
    from core.task.worker import run_senders
    from server.models import SessionLocal
    from server.models.industry import Industry
    from server.api.industries import _to_industry_config

    if not user_id:
        return {"ok": False, "error": "user_id is required"}

    db = SessionLocal()
    try:
        industry = (
            db.query(Industry)
            .filter(
                Industry.slug == industry_slug,
                Industry.user_id == user_id,
            )
            .first()
        )
        if not industry:
            return {"ok": False, "error": f"Industry {industry_slug} not found"}
        cfg = _to_industry_config(industry)
    finally:
        db.close()

    return run_senders(cfg, device_ids)
