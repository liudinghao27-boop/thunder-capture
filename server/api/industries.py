"""Industry management routes."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from server.auth import get_current_user
from server.models import get_db
from server.models.industry import Industry
from server.models.user import User
from server.schemas.industry import (
    IndustryCreate, IndustryOut, IndustryStats, IndustryUpdate,
)
from server.workers import run_collect_job, run_send_job, get_job_status

router = APIRouter(prefix="/api/industries", tags=["industries"])


def _to_industry_config(industry: Industry):
    """Convert DB model to engine-compatible IndustryConfig."""
    from engine.config import IndustryConfig
    return IndustryConfig(
        name=industry.name,
        slug=industry.slug,
        keywords=industry.keywords or [],
        reply_tone=industry.reply_tone,
        reply_style=industry.reply_style,
        categories=industry.categories or [],
        daily_limit=industry.daily_limit,
        video_max_age_days=industry.video_max_age_days,
        comment_max_age_hours=industry.comment_max_age_hours,
        platforms=industry.platforms or ["douyin"],
        llm_provider=industry.llm_provider or "deepseek",
        llm_model=industry.llm_model or "deepseek-chat",
        intent_keywords=industry.intent_keywords or [],
        noise_keywords=industry.noise_keywords or [],
    )


@router.get("", response_model=list[IndustryOut])
def list_industries(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(Industry)
        .filter(Industry.user_id == current_user.id, Industry.is_active == True)
        .order_by(Industry.created_at.desc())
        .all()
    )


@router.post("", response_model=IndustryOut, status_code=201)
def create_industry(
    data: IndustryCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if db.query(Industry).filter(
        Industry.user_id == current_user.id, Industry.slug == data.slug
    ).first():
        raise HTTPException(status_code=400, detail="Slug already exists")
    industry = Industry(user_id=current_user.id, **data.model_dump())
    db.add(industry)
    db.commit()
    db.refresh(industry)
    return industry


@router.get("/{industry_id}", response_model=IndustryOut)
def get_industry(
    industry_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ind = _get_owned_industry(industry_id, current_user, db)
    return ind


@router.put("/{industry_id}", response_model=IndustryOut)
def update_industry(
    industry_id: str,
    data: IndustryUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ind = _get_owned_industry(industry_id, current_user, db)
    for key, val in data.model_dump(exclude_unset=True).items():
        setattr(ind, key, val)
    db.commit()
    db.refresh(ind)
    return ind


@router.delete("/{industry_id}")
def delete_industry(
    industry_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ind = _get_owned_industry(industry_id, current_user, db)
    ind.is_active = False
    db.commit()
    return {"ok": True}


@router.post("/{industry_id}/collect")
def trigger_collect(
    industry_id: str,
    skip_discover: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ind = _get_owned_industry(industry_id, current_user, db)
    cfg = _to_industry_config(ind)
    job_id = run_collect_job(cfg, skip_discover=skip_discover)
    return {"job_id": job_id}


class SendRequest(BaseModel):
    devices: list[str] | None = None


@router.post("/{industry_id}/send")
def trigger_send(
    industry_id: str,
    body: SendRequest = SendRequest(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ind = _get_owned_industry(industry_id, current_user, db)
    cfg = _to_industry_config(ind)
    job_id = run_send_job(cfg, device_ids=body.devices)
    return {"job_id": job_id}


@router.get("/{industry_id}/stats", response_model=IndustryStats)
def get_industry_stats(
    industry_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ind = _get_owned_industry(industry_id, current_user, db)
    from engine.queue import init as init_engine, queue_stats, blogger_stats
    init_engine()
    qs = queue_stats(ind.slug)
    bs = blogger_stats(ind.slug)
    total = qs.get("total", 0)
    done = qs.get("done", 0)
    failed = qs.get("failed", 0)
    return IndustryStats(
        total_tasks=total,
        pending=qs.get("pending", 0),
        done=done,
        failed=failed,
        active_bloggers=bs.get("active", 0),
        success_rate=round(done / max(done + failed, 1) * 100, 1),
    )


@router.get("/{industry_id}/tasks")
def get_industry_tasks(
    industry_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    status: str = None,
    limit: int = 50,
    offset: int = 0,
):
    ind = _get_owned_industry(industry_id, current_user, db)
    from engine.queue import init as init_engine, _conn
    init_engine()
    conn = _conn()
    conn.row_factory = None  # default tuple mode
    params = [ind.slug]
    query = "SELECT * FROM task_queue WHERE industry_slug=?"
    if status:
        query += " AND status=?"
        params.append(status)
    query += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    cur = conn.execute(query, params)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    conn.close()
    return [dict(zip(cols, r)) for r in rows]


@router.get("/{industry_id}/bloggers")
def get_industry_bloggers(
    industry_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ind = _get_owned_industry(industry_id, current_user, db)
    from engine.queue import init as init_engine, get_bloggers
    init_engine()
    bloggers = get_bloggers("all", ind.slug)
    return bloggers


def _get_owned_industry(industry_id: str, user: User, db: Session) -> Industry:
    ind = db.query(Industry).filter(Industry.id == industry_id).first()
    if not ind or ind.user_id != user.id:
        raise HTTPException(status_code=404, detail="Industry not found")
    return ind
