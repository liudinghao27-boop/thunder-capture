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
    max_retries=5,
    default_retry_delay=90,  # 1.5 min base
    soft_time_limit=300,  # 5 min per send
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
    """Send a single DM via AutoGLM PhoneAgent.

    This replaces the inner loop of DeviceWorker.run().

    Args:
        device_id: Device identifier
        adb_serial: ADB serial number
        industry_slug: Target industry slug
        task_data: Task dict with source_sec_uid, source_name, etc.
        reply_msg: Generated reply message text
    """
    # TODO: Call core/agent/executor.py PhoneAgentExecutor
    # Currently wraps DeviceWorker logic
    log.info(
        "Sending DM: device=%s, industry=%s, target=%s",
        device_id, industry_slug, task_data.get("source_sec_uid", "")[:20],
    )

    try:
        # Stub: actual send logic from core/task/worker.py DeviceWorker
        # In production, this imports and calls PhoneAgentExecutor
        pass
    except Exception as exc:
        log.error("DM send failed: %s", exc)
        raise self.retry(exc=exc)


@app.task(bind=True, max_retries=1)
def run_send_batch(self, industry_slug: str, user_id: str = "", device_ids: list[str] = None):
    """Orchestrate batch sending across multiple devices using DB config."""
    from core.task.worker import run_senders
    from server.models import SessionLocal
    from server.models.industry import Industry
    from server.api.industries import _to_industry_config

    db = SessionLocal()
    try:
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
