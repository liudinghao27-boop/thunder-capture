"""Background job manager — lightweight, no Celery."""

import asyncio
import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

# ── Import engine modules at module level (fail-fast on startup) ──
from core.discover import run_discovery
from core.classify import classify_batch, enqueue_classified
from core.task.worker import run_senders
from server.services.llm import get_llm_client

log = logging.getLogger("thunder.workers")
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()

# Maximum number of completed/failed jobs to keep in memory
_MAX_JOB_HISTORY = 200
_CANCELLING_GRACE_SECONDS = 120
_COLLECT_HEARTBEAT_SECONDS = 20


def _now():
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _as_aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _is_stale_cancelling_snapshot(job: dict, now: datetime | None = None) -> bool:
    if job.get("status") != "cancelling" or not job.get("cancel_requested"):
        return False
    requested_at = _as_aware_utc(
        _parse_dt(job.get("cancel_requested_at"))
        or _parse_dt(job.get("updated_at"))
        or _parse_dt(job.get("created_at"))
    )
    if requested_at is None:
        return False
    now = now or datetime.now(timezone.utc)
    return now - requested_at > timedelta(seconds=_CANCELLING_GRACE_SECONDS)


def _job_in_memory(job_id: str) -> bool:
    with _jobs_lock:
        return job_id in _jobs


def _release_claimed_tasks_for_job(job: dict) -> int:
    """Release queue rows claimed by a send job that no longer has a worker."""
    if job.get("type") != "send":
        return 0
    industry_slug = job.get("industry_slug", "")
    devices = job.get("devices") or (job.get("payload") or {}).get("devices") or []
    devices = [str(d).strip() for d in devices if str(d).strip()]
    try:
        from server.models import SessionLocal
        from server.models.task import TaskQueue
    except Exception as e:
        log.debug("Queue unavailable for claim release: %s", e)
        return 0

    job_id = job.get("job_id") or job.get("id", "")
    db = SessionLocal()
    released = 0
    try:
        if job_id:
            released = db.query(TaskQueue).filter(
                TaskQueue.status == "claimed",
                TaskQueue.claim_token.like(f"{job_id}:%")
            ).update({
                TaskQueue.status: "pending",
                TaskQueue.consumer_id: None,
                TaskQueue.claim_token: None,
                TaskQueue.claimed_at: None,
                TaskQueue.retry_after: None,
                TaskQueue.error: None
            }, synchronize_session=False)
            db.commit()
            if released:
                log.warning("Released %s claimed task(s) for cancelled/orphaned job %s", released, job_id)
                return released

        if industry_slug and devices:
            released = db.query(TaskQueue).filter(
                TaskQueue.status == "claimed",
                TaskQueue.industry_slug == industry_slug,
                TaskQueue.consumer_id.in_(devices)
            ).update({
                TaskQueue.status: "pending",
                TaskQueue.consumer_id: None,
                TaskQueue.claim_token: None,
                TaskQueue.claimed_at: None,
                TaskQueue.retry_after: None,
                TaskQueue.error: None
            }, synchronize_session=False)
            db.commit()
            if released:
                log.warning("Released %s claimed task(s) for cancelled/orphaned job %s", released, job.get("job_id") or job.get("id", ""))
    finally:
        db.close()
    return released


def reconcile_stale_cancellations(user_id: str = "") -> int:
    """Mark long-running cancelling jobs as cancelled for UI/API consistency."""
    try:
        from server.models import SessionLocal
        from server.models.job import Job
    except Exception:
        return 0

    now = datetime.now(timezone.utc)
    db = SessionLocal()
    changed = 0
    changed_ids: list[str] = []
    try:
        query = db.query(Job).filter(
            Job.status == "cancelling",
            Job.cancel_requested == True,
        )
        if user_id:
            query = query.filter(Job.user_id == user_id)
        for job in query.all():
            payload = job.payload or {}
            requested_at = _as_aware_utc(
                _parse_dt(payload.get("cancel_requested_at"))
                or job.updated_at
                or job.created_at
            )
            if not requested_at or now - requested_at <= timedelta(seconds=_CANCELLING_GRACE_SECONDS):
                continue
            snapshot = {
                **payload,
                "job_id": job.id,
                "type": job.type,
                "industry_slug": job.industry_slug,
                "payload": payload,
            }
            released = _release_claimed_tasks_for_job(snapshot)
            job.status = "cancelled"
            job.progress = max(int(job.progress or 0), 100)
            job.completed_at = now
            if not job.error:
                job.error = "Cancellation timed out; marked cancelled."
            if released:
                payload = dict(payload)
                payload["released_claimed_tasks"] = (
                    int(payload.get("released_claimed_tasks") or 0) + released
                )
                job.payload = payload
            changed += 1
            changed_ids.append(job.id)
        if changed:
            db.commit()
    except Exception as e:
        db.rollback()
        log.warning("Failed to reconcile stale cancellations: %s", e)
        return 0
    finally:
        db.close()

    if changed_ids:
        completed_at = now.isoformat()
        with _jobs_lock:
            for job_id in changed_ids:
                if job_id in _jobs:
                    _jobs[job_id].update(
                        status="cancelled",
                        progress=max(int(_jobs[job_id].get("progress") or 0), 100),
                        completed_at=completed_at,
                        error=_jobs[job_id].get("error")
                        or "Cancellation timed out; marked cancelled.",
                    )
    return changed


def _fail_orphaned_running_snapshot(job_id: str, job: dict) -> dict:
    """Mark a DB running job failed when no in-memory worker owns it."""
    released = _release_claimed_tasks_for_job(job)
    completed_at = _now()
    error = job.get("error") or "Worker is no longer active; marked failed."
    snapshot = dict(job)
    snapshot.update(
        status="failed",
        progress=max(int(snapshot.get("progress") or 0), 100),
        updated_at=completed_at,
        completed_at=completed_at,
        error=error,
    )
    if released:
        snapshot["released_claimed_tasks"] = (
            int(snapshot.get("released_claimed_tasks") or 0) + released
        )
    fields = dict(snapshot)
    fields.pop("job_id", None)
    _set_job(job_id, **fields)
    return snapshot


def reconcile_orphaned_running_jobs(user_id: str = "") -> int:
    """Fail DB running jobs that survived their owning worker process/thread."""
    try:
        from server.models import SessionLocal
        from server.models.job import Job
    except Exception:
        return 0

    db = SessionLocal()
    changed = 0
    try:
        query = db.query(Job).filter(Job.status == "running")
        if user_id:
            query = query.filter(Job.user_id == user_id)
        for job in query.all():
            if _job_in_memory(job.id):
                continue
            snapshot = {
                **(job.payload or {}),
                "job_id": job.id,
                "user_id": job.user_id,
                "type": job.type,
                "industry_slug": job.industry_slug,
                "industry_name": job.industry_name,
                "status": job.status,
                "progress": job.progress,
                "error": job.error,
                "cancel_requested": job.cancel_requested,
            }
            _fail_orphaned_running_snapshot(job.id, snapshot)
            changed += 1
    finally:
        db.close()
    return changed


def _reconcile_snapshot(job_id: str, job: dict) -> dict:
    snapshot = dict(job)
    if not _is_stale_cancelling_snapshot(snapshot):
        return snapshot
    released = _release_claimed_tasks_for_job(snapshot)
    completed_at = _now()
    snapshot.update(
        status="cancelled",
        progress=max(int(snapshot.get("progress") or 0), 100),
        completed_at=completed_at,
        error=snapshot.get("error") or "Cancellation timed out; marked cancelled.",
    )
    if released:
        snapshot["released_claimed_tasks"] = (
            int(snapshot.get("released_claimed_tasks") or 0) + released
        )
    fields = dict(snapshot)
    fields.pop("job_id", None)
    _set_job(job_id, **fields)
    return snapshot


def _persist_job(job_id: str, fields: dict):
    """Persist job state to the server database best-effort."""
    try:
        from server.models import SessionLocal
        from server.models.job import Job
    except Exception as e:
        log.debug("Job persistence unavailable: %s", e)
        return

    user_id = fields.get("user_id", "")
    if not user_id:
        return

    db = SessionLocal()
    try:
        Job.__table__.create(bind=db.get_bind(), checkfirst=True)
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            job = Job(
                id=job_id,
                user_id=user_id,
                type=fields.get("type", "unknown"),
                status=fields.get("status", "running"),
                created_at=_parse_dt(fields.get("created_at")) or datetime.now(timezone.utc),
            )
            db.add(job)

        for attr in (
            "user_id", "type", "status", "progress", "industry_slug",
            "industry_name", "error", "cancel_requested",
        ):
            if attr in fields:
                setattr(job, attr, fields[attr])
        if "completed_at" in fields:
            job.completed_at = _parse_dt(fields.get("completed_at"))
        job.updated_at = datetime.now(timezone.utc)

        payload = dict(job.payload or {})
        for key, value in fields.items():
            if key not in {
                "user_id", "type", "status", "progress", "industry_slug",
                "industry_name", "error", "created_at", "updated_at",
                "completed_at", "cancel_requested", "job_id", "payload",
            }:
                payload[key] = value
        job.payload = payload
        db.commit()
    except Exception as e:
        db.rollback()
        log.warning("Failed to persist job %s: %s", job_id, e)
    finally:
        db.close()


def _set_job(job_id: str, **fields):
    """Thread-safe job state update with atomic prune."""
    fields.setdefault("job_id", job_id)
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id].update(fields)
        else:
            _jobs[job_id] = fields

        # Prune old jobs to prevent memory leak (inside same critical section)
        if len(_jobs) > _MAX_JOB_HISTORY + 50:
            finished = [
                jid for jid, j in _jobs.items()
                if j.get("status") in ("done", "failed", "cancelled")
            ]
            if finished:
                finished.sort(
                    key=lambda jid: _jobs[jid].get("completed_at", ""),
                    reverse=True,
                )
                for old_jid in finished[_MAX_JOB_HISTORY:]:
                    del _jobs[old_jid]
        snapshot = dict(_jobs.get(job_id, {}))

    _persist_job(job_id, snapshot)


def _is_cancel_requested(job_id: str) -> bool:
    with _jobs_lock:
        if _jobs.get(job_id, {}).get("cancel_requested"):
            return True
    try:
        from server.models import SessionLocal
        from server.models.job import Job
    except Exception:
        return False

    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        return bool(job and job.cancel_requested)
    finally:
        db.close()


def cancel_job(job_id: str, user_id: str) -> dict | None:
    """Mark a job as cancellation requested. Running workers check cooperatively."""
    job = get_job_status(job_id, user_id)
    if not job:
        return None
    if job.get("status") in ("done", "failed", "cancelled"):
        return job
    if job.get("status") == "cancelling":
        return job
    cancel_requested_at = job.get("cancel_requested_at") or _now()
    released = _release_claimed_tasks_for_job({**dict(job), "job_id": job_id})
    if not _job_in_memory(job_id):
        job = dict(job)
        job["cancel_requested_at"] = cancel_requested_at
        _set_job(
            job_id,
            user_id=user_id,
            type=job.get("type", "unknown"),
            industry_slug=job.get("industry_slug", ""),
            industry_name=job.get("industry_name", ""),
            cancel_requested=True,
            cancel_requested_at=cancel_requested_at,
            status="cancelled",
            progress=100,
            completed_at=_now(),
            error=job.get("error") or "Cancelled after worker was no longer active.",
            released_claimed_tasks=released,
        )
        return get_job_status(job_id, user_id)
    _set_job(
        job_id,
        user_id=user_id,
        type=job.get("type", "unknown"),
        industry_slug=job.get("industry_slug", ""),
        industry_name=job.get("industry_name", ""),
        cancel_requested=True,
        cancel_requested_at=cancel_requested_at,
        status="cancelling",
        progress=job.get("progress", 0),
        released_claimed_tasks=released,
    )
    return get_job_status(job_id, user_id)


def _run_async(coro):
    """Run an async coroutine in a background thread with its own event loop."""
    def _runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(coro)
        except Exception as e:
            log.exception(f"Background async task failed: {e}")
        finally:
            loop.close()
    t = threading.Thread(target=_runner, daemon=True)
    t.start()


def _trigger_auto_export(slug: str, user_id: str, passed: list[dict]) -> None:
    """Push classified leads to webhook when auto_export_enabled is set.

    Runs the blocking HTTP push in a background thread so the collect job
    is not delayed. Errors are swallowed and logged.
    """
    if not passed or not slug or not user_id:
        return
    try:
        from server.services.webhook import push_leads_to_webhook
        from server.models import SessionLocal
        from server.models.industry import Industry

        db = SessionLocal()
        try:
            industry = db.query(Industry).filter(
                Industry.slug == slug,
                Industry.user_id == user_id,
            ).first()
            if not industry or not industry.auto_export_enabled or not industry.webhook_url:
                return
            threading.Thread(
                target=push_leads_to_webhook,
                kwargs={
                    "webhook_url": industry.webhook_url,
                    "industry_slug": industry.slug,
                    "industry_name": industry.name,
                    "leads": passed[:500],
                },
                daemon=True,
            ).start()
        finally:
            db.close()
    except Exception as e:
        log.warning("Auto-export webhook failed for %s: %s", slug, e)


def run_collect_job(industry_cfg, skip_discover: bool = False) -> str:
    """Trigger a background collection job. Returns job_id."""
    # Merge YAML config for richer keywords/tuning
    slug = getattr(industry_cfg, "slug", "")
    try:
        from core.config import load_industry
        yaml_cfg = load_industry(slug)
        for field in ("keywords", "reply_tone", "reply_style", "categories",
                      "video_max_age_days", "comment_max_age_hours",
                      "intent_keywords", "noise_keywords"):
            yaml_val = getattr(yaml_cfg, field, None)
            db_val = getattr(industry_cfg, field, None)
            # Always sync keywords and categories (critical for classification)
            if yaml_val and (not db_val or field in ("keywords", "categories", "intent_keywords", "noise_keywords")):
                setattr(industry_cfg, field, yaml_val)
    except Exception:
        pass

    job_id = str(uuid.uuid4())
    _set_job(job_id, status="running", progress=0, created_at=_now(),
             type="collect", skip_discover=skip_discover,
             user_id=getattr(industry_cfg, "user_id", ""),
             industry_slug=slug,
             industry_name=getattr(industry_cfg, "name", ""))

    async def _collect():
        job_id_local = job_id  # capture for closure safety
        heartbeat_task = None

        async def _discovery_heartbeat():
            progress = 10
            while True:
                await asyncio.sleep(_COLLECT_HEARTBEAT_SECONDS)
                if _is_cancel_requested(job_id_local):
                    return
                progress = min(progress + 2, 49)
                _set_job(
                    job_id_local,
                    progress=progress,
                    phase="discover",
                    heartbeat_at=_now(),
                )

        try:
            client = None
            intent_words: Optional[list] = None
            noise_words: Optional[list] = None

            if _is_cancel_requested(job_id_local):
                _set_job(job_id_local, status="cancelled", progress=0,
                         completed_at=_now(), type="collect")
                return

            try:
                provider = getattr(industry_cfg, 'llm_provider', 'deepseek')
                api_key_override = ""
                if provider == "deepseek":
                    api_key_override = getattr(industry_cfg, "deepseek_key", "") or ""
                elif provider == "zhipu":
                    api_key_override = getattr(industry_cfg, "zhipu_key", "") or ""
                elif provider == "openai":
                    api_key_override = getattr(industry_cfg, "openai_key", "") or ""
                client = get_llm_client(
                    provider,
                    model=getattr(industry_cfg, 'llm_model', 'deepseek-chat'),
                    api_key=api_key_override or None,
                )
                intent_words = getattr(industry_cfg, 'intent_keywords', None) or None
                noise_words = getattr(industry_cfg, 'noise_keywords', None) or None
            except Exception as e:
                log.warning(f"LLM client init failed for job {job_id_local}: {e}")
                # Continue without LLM hints — classify_batch can still do regex pre-filter

            _set_job(job_id_local, progress=10, phase="init")
            if _is_cancel_requested(job_id_local):
                _set_job(job_id_local, status="cancelled", completed_at=_now())
                return
            heartbeat_task = asyncio.create_task(_discovery_heartbeat())
            _set_job(job_id_local, progress=12, phase="discover")
            comments = await run_discovery(
                industry_cfg,
                skip_discover=skip_discover,
                should_stop=lambda: _is_cancel_requested(job_id_local),
            )
            owner_user_id = getattr(industry_cfg, "user_id", "") or ""
            if owner_user_id:
                for comment in comments or []:
                    comment.setdefault("owner_user_id", owner_user_id)
            if heartbeat_task:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
                heartbeat_task = None
            _set_job(job_id_local, progress=50)
            if _is_cancel_requested(job_id_local):
                _set_job(job_id_local, status="cancelled", completed_at=_now())
                return
            if comments:
                def _classify_progress(done_batches, total_batches):
                    pct = 50 + int(30 * done_batches / max(total_batches, 1))
                    _set_job(job_id_local, progress=min(pct, 80),
                             phase="classify")

                passed = classify_batch(comments, industry_cfg,
                                       llm_client=client,
                                       intent_words=intent_words,
                                       noise_words=noise_words,
                                       progress_callback=_classify_progress)
                _set_job(job_id_local, progress=80)
                enqueued = enqueue_classified(passed)
                # Auto-export high-intent leads to webhook if enabled
                if passed and getattr(industry_cfg, "auto_export_enabled", False) and getattr(industry_cfg, "webhook_url", ""):
                    _trigger_auto_export(
                        slug,
                        getattr(industry_cfg, "user_id", ""),
                        passed,
                    )
            else:
                passed = []
                enqueued = 0
            collect_summary = {
                "candidate_comments": len(comments or []),
                "classified_passed": len(passed),
                "enqueued": enqueued,
                "platforms": list(getattr(industry_cfg, "platforms", []) or []),
                "target_user_count": len(getattr(industry_cfg, "target_users", []) or []),
                "keyword_count": len(getattr(industry_cfg, "keywords", []) or []),
            }
            _set_job(job_id_local, status="done", progress=100,
                     completed_at=_now(), type="collect",
                     collect_summary=collect_summary)
        except Exception as e:
            log.exception(f"Collect job {job_id_local} failed")
            _set_job(job_id_local, status="failed", error=str(e),
                     completed_at=_now(), type="collect")
        finally:
            if heartbeat_task:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

    _run_async(_collect())
    return job_id


def run_send_job(industry_cfg, device_ids: list[str] = None) -> str:
    """Trigger a background send job. Returns job_id."""
    job_id = str(uuid.uuid4())
    _set_job(job_id, status="running", progress=0, created_at=_now(),
             type="send", devices=device_ids,
             user_id=getattr(industry_cfg, "user_id", ""),
             industry_slug=getattr(industry_cfg, "slug", ""),
             industry_name=getattr(industry_cfg, "name", ""))

    def _maybe_auto_replenish(send_summary: dict | None) -> dict | None:
        if not bool(getattr(industry_cfg, "auto_replenish_enabled", False)):
            return None
        if not send_summary or not send_summary.get("replenish_recommended"):
            return None
        try:
            from server.services.task_stats import replenishment_plan
            plan = replenishment_plan(
                getattr(industry_cfg, "slug", ""),
                target_devices=int(getattr(industry_cfg, "matrix_target_devices", 30) or 30),
                per_device_daily_limit=int(getattr(industry_cfg, "daily_limit", 15) or 15),
                inventory_days=int(getattr(industry_cfg, "lead_inventory_days", 3) or 3),
                global_daily_limit=int(getattr(industry_cfg, "global_daily_limit", 0) or 0),
                threshold_days=int(getattr(industry_cfg, "replenish_threshold_days", 1) or 1),
            )
            if not plan.get("should_replenish"):
                return {"started": False, "reason": "库存充足", "plan": plan}
            collect_job_id = run_collect_job(
                industry_cfg,
                skip_discover=bool(plan.get("skip_discover")),
            )
            return {
                "started": True,
                "job_id": collect_job_id,
                "skip_discover": bool(plan.get("skip_discover")),
                "mode": plan.get("mode"),
                "plan": plan,
            }
        except Exception as e:
            log.warning("Auto replenishment failed for %s: %s", getattr(industry_cfg, "slug", ""), e)
            return {"started": False, "error": str(e)[:500]}

    def _send():
        job_id_local = job_id
        try:
            if _is_cancel_requested(job_id_local):
                _set_job(job_id_local, status="cancelled", progress=0,
                         completed_at=_now(), type="send")
                return
            send_summary = run_senders(
                industry_cfg,
                device_ids,
                should_stop=lambda: _is_cancel_requested(job_id_local),
                job_id=job_id_local,
            )
            if isinstance(send_summary, dict) and not _is_cancel_requested(job_id_local):
                auto_replenish = _maybe_auto_replenish(send_summary)
                if auto_replenish:
                    send_summary = dict(send_summary)
                    send_summary["auto_replenish"] = auto_replenish
            if _is_cancel_requested(job_id_local):
                if isinstance(send_summary, dict):
                    send_summary = dict(send_summary)
                    send_summary["status"] = "cancelled"
                    send_summary["cancel_requested"] = True
                _set_job(job_id_local, status="cancelled", progress=100,
                         completed_at=_now(), type="send",
                         send_summary=send_summary)
            elif not send_summary or not send_summary.get("ok"):
                _set_job(
                    job_id_local,
                    status="failed",
                    progress=100,
                    error=(send_summary or {}).get("error") or "Send job did not execute on any device.",
                    completed_at=_now(),
                    type="send",
                    send_summary=send_summary,
                )
            else:
                _set_job(job_id_local, status="done", progress=100,
                         completed_at=_now(), type="send",
                         send_summary=send_summary)
        except Exception as e:
            log.exception(f"Send job {job_id_local} failed")
            _set_job(job_id_local, status="failed", error=str(e),
                     completed_at=_now(), type="send")

    threading.Thread(target=_send, daemon=True).start()
    return job_id


def get_job_status(job_id: str, user_id: str = "") -> dict | None:
    """Poll job status. Returns None if not found or not owned by user_id."""
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job:
            owner_id = job.get("user_id", "")
            if user_id and owner_id and owner_id != user_id:
                return None
            snapshot = dict(job)
            snapshot.setdefault("job_id", job_id)
    if "snapshot" in locals():
        return _reconcile_snapshot(job_id, snapshot)

    try:
        from server.models import SessionLocal
        from server.models.job import Job
    except Exception:
        return None

    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job or (user_id and job.user_id != user_id):
            return None
        snapshot = {
            **(job.payload or {}),
            "job_id": job.id,
            "user_id": job.user_id,
            "industry_slug": job.industry_slug,
            "industry_name": job.industry_name,
            "type": job.type,
            "status": job.status,
            "progress": job.progress,
            "error": job.error,
            "cancel_requested": job.cancel_requested,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        }
        if snapshot.get("status") == "running" and not _job_in_memory(job.id):
            return _fail_orphaned_running_snapshot(job.id, snapshot)
        return _reconcile_snapshot(job.id, snapshot)
    finally:
        db.close()


# ── Auto-recovery background timer ──────────────────

_auto_recovery_started = False
_auto_recovery_lock = threading.Lock()
_AUTO_RECOVERY_INTERVAL_SEC = 60


def _auto_recovery_loop():
    """Periodically reconcile stale cancellations and orphaned running jobs."""
    while True:
        try:
            reconcile_stale_cancellations("")
            reconcile_orphaned_running_jobs("")
        except Exception:
            pass
        import time
        time.sleep(_AUTO_RECOVERY_INTERVAL_SEC)


def start_auto_recovery():
    """Start the background auto-recovery timer (idempotent)."""
    global _auto_recovery_started
    with _auto_recovery_lock:
        if _auto_recovery_started:
            return
        _auto_recovery_started = True
    t = threading.Thread(target=_auto_recovery_loop, name="auto-recovery", daemon=True)
    t.start()
    log.info("Auto-recovery background timer started (%ss interval)", _AUTO_RECOVERY_INTERVAL_SEC)
