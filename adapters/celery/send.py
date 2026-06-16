"""Celery tasks: DM sending pipeline.

Migration path from core/task/worker.py DeviceWorker.run():
  1. Replace threading.Thread per device with Celery worker per device
  2. Each device gets its own task queue (rate-limited)
  3. Built-in retry with exponential backoff replaces manual sleep loops
"""

from __future__ import annotations

import logging

from adapters.celery.app import app

log = logging.getLogger("thunder.celery.send")


@app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=90,  # 1.5 min base
    soft_time_limit=600,  # 10 min per device session
    rate_limit="15/h",  # Per-device daily limit via rate limiting
)
def send_dm_task(
    self,
    device_id: str,
    adb_serial: str,
    industry_slug: str,
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
    from core.task.worker import DeviceWorker

    db = SessionLocal()
    try:
        industry = db.query(Industry).filter(Industry.slug == industry_slug).first()
        if not industry:
            return {"ok": False, "error": f"Industry {industry_slug} not found"}
        if industry.compliance_mode:
            log.info("Compliance mode enabled for %s; skipping Celery DM send.", industry_slug)
            return {"ok": True, "skipped": True, "reason": "compliance_mode"}
        cfg = _to_industry_config(industry)
    finally:
        db.close()

    def should_stop():
        # Celery best-effort abort signal
        return self.is_aborted()

    worker = DeviceWorker(
        device_id=device_id,
        adb_serial=adb_serial,
        industry=cfg,
        daily_limit=task_data.get("daily_limit", cfg.daily_limit or 15),
        min_interval=task_data.get("min_interval_sec", 90),
        should_stop=should_stop,
        job_id=task_data.get("job_id", ""),
    )

    log.info("DeviceWorker session started: device=%s industry=%s", device_id, industry_slug)
    summary = worker.run()
    log.info("DeviceWorker session finished: device=%s summary=%s", device_id, summary)
    return summary


@app.task(bind=True, max_retries=1)
def run_send_batch(self, industry_slug: str, user_id: str = "", device_ids: list[str] = None):
    """Orchestrate batch sending across multiple devices using DB config."""
    from core.task.worker import run_senders
    from server.models import SessionLocal
    from server.models.industry import Industry
    from server.api.industries import _to_industry_config

    db = SessionLocal()
    try:
        if industry_slug == "__all_active__":
            industries = db.query(Industry).filter(Industry.is_active == True).all()
            results = []
            for ind in industries:
                cfg = _to_industry_config(ind)
                results.append(run_senders(cfg, device_ids))
            return {"ok": True, "mode": "all_active", "industries": len(industries), "results": results}

        industry = db.query(Industry).filter(
            Industry.slug == industry_slug,
            Industry.user_id == user_id,
        ).first()
        if not industry:
            return {"ok": False, "error": f"Industry {industry_slug} not found"}
        cfg = _to_industry_config(industry)
    finally:
        db.close()

    result = run_senders(cfg, device_ids)
    log.info(
        "Batch send done: skipped=%s sent=%d failed=%d devices=%d",
        result.get("skipped", False),
        result.get("sent_total", 0),
        result.get("failed_total", 0),
        result.get("devices_total", 0),
    )
    return result
