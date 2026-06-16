"""Background job manager — lightweight, no Celery."""

import asyncio
import logging
import threading
import uuid
from datetime import datetime, timezone

log = logging.getLogger("thunder.workers")
_jobs: dict[str, dict] = {}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _run_async(coro):
    """Run an async coroutine in a background thread with its own event loop."""
    def _runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(coro)
        finally:
            loop.close()
    t = threading.Thread(target=_runner, daemon=True)
    t.start()


def run_collect_job(industry_cfg, skip_discover: bool = False) -> str:
    """Trigger a background collection job. Returns job_id."""
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "running", "progress": 0, "created_at": _now(),
                     "type": "collect", "skip_discover": skip_discover}

    async def _collect():
        try:
            from engine.discover import run_discovery
            from engine.classify import classify_batch, enqueue_classified

            client = None
            intent_words = None
            noise_words = None

            try:
                from server.services.llm import get_llm_client
                provider = getattr(industry_cfg, 'llm_provider', 'deepseek')
                client = get_llm_client(provider,
                                       getattr(industry_cfg, 'llm_model', 'deepseek-chat'))
                intent_words = getattr(industry_cfg, 'intent_keywords', None) or None
                noise_words = getattr(industry_cfg, 'noise_keywords', None) or None
            except Exception:
                pass

            _jobs[job_id]["progress"] = 10
            comments = await run_discovery(industry_cfg, skip_discover=skip_discover)
            _jobs[job_id]["progress"] = 50
            if comments:
                passed = classify_batch(comments, industry_cfg,
                                       llm_client=client,
                                       intent_words=intent_words,
                                       noise_words=noise_words)
                _jobs[job_id]["progress"] = 80
                enqueue_classified(passed)
            _jobs[job_id] = {"status": "done", "progress": 100, "completed_at": _now(),
                             "type": "collect"}
        except Exception as e:
            log.exception(f"Collect job {job_id} failed")
            _jobs[job_id] = {"status": "failed", "error": str(e), "completed_at": _now(),
                             "type": "collect"}

    _run_async(_collect())
    return job_id


def run_send_job(industry_cfg, device_ids: list[str] = None) -> str:
    """Trigger a background send job. Returns job_id."""
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "running", "progress": 0, "created_at": _now(),
                     "type": "send", "devices": device_ids}

    def _send():
        try:
            from engine.sender import run_senders
            run_senders(industry_cfg, device_ids)
            _jobs[job_id] = {"status": "done", "progress": 100, "completed_at": _now(),
                             "type": "send"}
        except Exception as e:
            log.exception(f"Send job {job_id} failed")
            _jobs[job_id] = {"status": "failed", "error": str(e), "completed_at": _now(),
                             "type": "send"}

    threading.Thread(target=_send, daemon=True).start()
    return job_id


def get_job_status(job_id: str) -> dict | None:
    """Poll job status. Returns None if job not found."""
    return _jobs.get(job_id)
