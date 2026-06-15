"""Job management routes — standardized REST API for send/collect jobs."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from server.auth import get_current_user
from server.models import get_db
from server.models.job import Job
from server.models.user import User
from server.workers import (
    cancel_job,
    get_job_status,
    reconcile_orphaned_running_jobs,
    reconcile_stale_cancellations,
)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

# ── Response models ──────────────────────────────


class JobSummary(BaseModel):
    job_id: str
    type: str
    status: str
    progress: int = 0
    industry_slug: str = ""
    industry_name: str = ""
    error: str | None = None
    cancel_requested: bool = False
    created_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None
    payload: dict = Field(default_factory=dict)
    send_summary: dict | None = None
    collect_summary: dict | None = None


class JobDetail(JobSummary):
    """Full job status including live state from in-memory workers."""
    worker_alive: bool = True
    released_claimed_tasks: int = 0


# ── Routes ───────────────────────────────────────


@router.get("", response_model=list[JobSummary])
def list_jobs(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    status: str = Query(default=""),
    job_type: str = Query(default=""),
):
    """List background jobs with optional filters. Reconciles stale states on read."""
    reconcile_stale_cancellations(current_user.id)
    reconcile_orphaned_running_jobs(current_user.id)

    query = db.query(Job).filter(Job.user_id == current_user.id)
    if status:
        query = query.filter(Job.status == status)
    if job_type:
        query = query.filter(Job.type == job_type)

    jobs = query.order_by(Job.created_at.desc()).limit(limit).all()
    return [
        JobSummary(
            job_id=j.id,
            type=j.type,
            status=j.status,
            progress=j.progress or 0,
            industry_slug=j.industry_slug or "",
            industry_name=j.industry_name or "",
            error=j.error,
            cancel_requested=bool(j.cancel_requested),
            created_at=j.created_at.isoformat() if j.created_at else None,
            updated_at=j.updated_at.isoformat() if j.updated_at else None,
            completed_at=j.completed_at.isoformat() if j.completed_at else None,
            payload=j.payload or {},
            send_summary=(j.payload or {}).get("send_summary"),
            collect_summary=(j.payload or {}).get("collect_summary"),
        )
        for j in jobs
    ]


@router.get("/{job_id}", response_model=JobDetail)
def get_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
):
    """Get live job status (in-memory + DB)."""
    status = get_job_status(job_id, current_user.id)
    if status is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobDetail(
        job_id=job_id,
        type=status.get("type", "unknown"),
        status=status.get("status", "unknown"),
        progress=status.get("progress", 0),
        industry_slug=status.get("industry_slug", ""),
        industry_name=status.get("industry_name", ""),
        error=status.get("error"),
        cancel_requested=bool(status.get("cancel_requested")),
        created_at=status.get("created_at"),
        updated_at=status.get("updated_at"),
        completed_at=status.get("completed_at"),
        payload=status.get("payload", {}),
        send_summary=status.get("send_summary"),
        collect_summary=status.get("collect_summary"),
        worker_alive=bool(status.get("_worker_alive", True)),
        released_claimed_tasks=int(status.get("released_claimed_tasks", 0)),
    )


@router.post("/{job_id}/cancel", response_model=JobSummary)
def cancel_running_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
):
    """Request cancellation of a running job. Non-blocking — status may be 'cancelling' initially."""
    status = cancel_job(job_id, current_user.id)
    if status is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobSummary(
        job_id=job_id,
        type=status.get("type", "unknown"),
        status=status.get("status", "unknown"),
        progress=status.get("progress", 0),
        industry_slug=status.get("industry_slug", ""),
        industry_name=status.get("industry_name", ""),
        error=status.get("error"),
        cancel_requested=bool(status.get("cancel_requested")),
        created_at=status.get("created_at"),
        updated_at=status.get("updated_at"),
        completed_at=status.get("completed_at"),
        payload=status.get("payload", {}),
    )


@router.get("/{job_id}/devices")
def get_job_devices(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get device statuses associated with a job."""
    from server.models.matrix import DeviceState

    status = get_job_status(job_id, current_user.id)
    if status is None:
        raise HTTPException(status_code=404, detail="Job not found")

    devices = (
        db.query(DeviceState)
        .filter(
            DeviceState.user_id == current_user.id,
            DeviceState.job_id == job_id,
        )
        .order_by(DeviceState.updated_at.desc())
        .all()
    )
    return {"job_id": job_id, "job_status": status.get("status"), "devices": [
            {
                "device_id": d.device_id,
                "status": d.status,
                "current_screen": d.current_screen,
                "health": d.health or {},
                "consecutive_failures": d.consecutive_failures,
                "last_heartbeat": d.last_heartbeat.isoformat() if d.last_heartbeat else None,
            }
            for d in devices
        ],
    }


# ── Start endpoints ────────────────────────────────

class StartCollectRequest(BaseModel):
    industry_slug: str
    skip_discover: bool = False


@router.post("/collect/start")
def start_collect_job(
    body: StartCollectRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from server.models.industry import Industry
    industry = db.query(Industry).filter(
        Industry.slug == body.industry_slug, Industry.user_id == current_user.id
    ).first()
    if not industry:
        raise HTTPException(status_code=404, detail="Industry not found")
    from server.workers import run_collect_job
    job_id = run_collect_job(industry, skip_discover=body.skip_discover)
    status = get_job_status(job_id, current_user.id)
    return {"ok": True, "job_id": job_id, "status": status.get("status") if status else "unknown"}


class StartSendRequest(BaseModel):
    industry_slug: str
    device_ids: list[str] | None = None


@router.post("/send/start")
def start_send_job(
    body: StartSendRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from server.models.device import Device
    from server.models.industry import Industry
    from server.models.job import Job as JobModel

    industry = db.query(Industry).filter(
        Industry.slug == body.industry_slug, Industry.user_id == current_user.id
    ).first()
    if not industry:
        raise HTTPException(status_code=404, detail="Industry not found")

    try:
        from server.services.task_stats import queue_stats
        if queue_stats(body.industry_slug).get("pending", 0) == 0:
            raise HTTPException(status_code=400, detail="No pending leads")
    except HTTPException:
        raise
    except Exception:
        pass

    idle_count = db.query(Device).filter(
        Device.user_id == current_user.id, Device.runtime_status == "idle"
    ).count()
    if idle_count == 0:
        raise HTTPException(status_code=400, detail="No available devices")

    active = db.query(JobModel).filter(
        JobModel.user_id == current_user.id, JobModel.type == "send",
        JobModel.status.in_(["running", "cancelling"])
    ).first()
    if active:
        raise HTTPException(status_code=409, detail="Send job already running")

    from server.workers import run_send_job
    job_id = run_send_job(industry, body.device_ids)
    status = get_job_status(job_id, current_user.id)
    return {"ok": True, "job_id": job_id, "status": status.get("status") if status else "unknown"}
