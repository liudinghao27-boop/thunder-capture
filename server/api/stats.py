"""Global overview routes."""

import os
import shutil
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from server.auth import get_current_user
from server.models import engine as server_engine, get_db
from server.models.industry import Industry
from server.models.job import Job
from server.models.task import TaskQueue
from server.models.user import User
from server.secret_store import has_secret
from server.services.analytics import (
    aggregate_by_keyword,
    aggregate_by_device,
    query_task_rows,
)
from server.services.migrations import verify_matrix_schema
from server.workers import (
    cancel_job,
    get_job_status,
    reconcile_orphaned_running_jobs,
    reconcile_stale_cancellations,
)

router = APIRouter(prefix="/api", tags=["stats"])


@router.get("/stats/overview")
def overview(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    industries = (
        db.query(Industry)
        .filter(Industry.user_id == current_user.id, Industry.is_active.is_(True))
        .all()
    )
    return {
        "industry_count": len(industries),
        "industries": [
            {"id": i.id, "name": i.name, "slug": i.slug, "platforms": i.platforms}
            for i in industries
        ],
    }


@router.get("/stats/effects")
def get_effect_stats(
    industry_slug: str,
    days: int = Query(7, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    base_query = db.query(TaskQueue).filter(
        TaskQueue.industry_slug == industry_slug,
        TaskQueue.owner_user_id == current_user.id,
        TaskQueue.fetched_at >= since,
    )
    sent = base_query.filter(
        TaskQueue.status.in_(["sent", "done", "replied", "converted"])
    ).count()
    replied = base_query.filter(TaskQueue.status.in_(["replied", "converted"])).count()
    converted = base_query.filter(TaskQueue.status == "converted").count()

    reply_rate = round(replied / sent, 4) if sent else 0.0
    conversion_rate = round(converted / sent, 4) if sent else 0.0

    return {
        "industry_slug": industry_slug,
        "days": days,
        "sent": sent,
        "replied": replied,
        "converted": converted,
        "reply_rate": reply_rate,
        "conversion_rate": conversion_rate,
    }


@router.get("/stats/keywords")
def get_keyword_stats(
    industry_slug: str,
    days: int = Query(7, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    rows = query_task_rows(db, industry_slug, days, owner_user_id=current_user.id)
    return {
        "industry_slug": industry_slug,
        "days": days,
        "keywords": aggregate_by_keyword(industry_slug, rows),
    }


@router.get("/stats/devices")
def get_device_stats(
    industry_slug: str,
    days: int = Query(7, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    rows = query_task_rows(db, industry_slug, days, owner_user_id=current_user.id)
    return {
        "industry_slug": industry_slug,
        "days": days,
        "devices": aggregate_by_device(industry_slug, rows),
    }


@router.get("/tasks/status/{job_id}")
def job_status(
    job_id: str,
    current_user: User = Depends(get_current_user),
):
    """Poll a background job's status."""
    status = get_job_status(job_id, current_user.id)
    if status is None:
        return {"status": "not_found"}
    return status


@router.post("/tasks/status/{job_id}/cancel")
def cancel_task_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
):
    """Request cancellation for a running background job."""
    status = cancel_job(job_id, current_user.id)
    if status is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return status


@router.get("/stats/jobs", include_in_schema=False)
def list_jobs(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = 50,
):
    limit = max(1, min(limit, 200))
    reconcile_stale_cancellations(current_user.id)
    reconcile_orphaned_running_jobs(current_user.id)
    jobs = (
        db.query(Job)
        .filter(Job.user_id == current_user.id)
        .order_by(Job.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "job_id": j.id,
            "type": j.type,
            "status": j.status,
            "progress": j.progress,
            "industry_slug": j.industry_slug,
            "industry_name": j.industry_name,
            "error": j.error,
            "cancel_requested": j.cancel_requested,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "updated_at": j.updated_at.isoformat() if j.updated_at else None,
            "completed_at": j.completed_at.isoformat() if j.completed_at else None,
            "payload": j.payload or {},
            "send_summary": (j.payload or {}).get("send_summary", {}),
            "collect_summary": (j.payload or {}).get("collect_summary", {}),
        }
        for j in jobs
    ]


@router.get("/system/health")
def system_health(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return local runtime readiness checks for the dashboard."""
    checks = []

    def add(name: str, ok: bool, detail: str = ""):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    try:
        db.execute(Job.__table__.select().limit(1)).fetchall()
        add("server_db", True, "业务数据库可访问")
    except Exception as e:
        add("server_db", False, str(e)[:200])

    try:
        Job.__table__.create(bind=server_engine, checkfirst=True)
        add("jobs_table", True, "后台任务表可用")
    except Exception as e:
        add("jobs_table", False, str(e)[:200])

    try:
        matrix = verify_matrix_schema(server_engine)
        detail = (
            "matrix/agent tables ready"
            if matrix["ok"]
            else "missing: " + ", ".join(matrix["missing_tables"])
        )
        add("matrix_schema", matrix["ok"], detail)
    except Exception as e:
        add("matrix_schema", False, str(e)[:200])

    try:
        from server.models.task import TaskQueue
        from server.models import SessionLocal

        health_db = SessionLocal()
        health_db.query(TaskQueue).first()
        health_db.close()
        add("engine_db", True, "PostgreSQL queue schema active")
    except Exception as e:
        add("engine_db", False, str(e)[:200])

    adb_path = shutil.which("adb")
    add("adb", bool(adb_path), adb_path or "未在 PATH 中找到 adb")

    llm_keys = {
        "deepseek": bool(os.getenv("THUNDER_DEEPSEEK_KEY"))
        or has_secret(current_user.deepseek_key),
        "zhipu": bool(os.getenv("THUNDER_ZHIPU_KEY"))
        or has_secret(current_user.zhipu_key),
        "openai": bool(os.getenv("THUNDER_OPENAI_KEY"))
        or has_secret(current_user.openai_key),
    }
    add(
        "llm_keys",
        any(llm_keys.values()),
        ", ".join(k for k, v in llm_keys.items() if v) or "未配置 LLM Key",
    )

    all_ok = all(
        c["ok"]
        for c in checks
        if c["name"] in {"server_db", "jobs_table", "matrix_schema", "engine_db"}
    )
    return {"ok": all_ok, "checks": checks}
