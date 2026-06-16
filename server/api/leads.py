"""Lead pool management routes — CRUD, filter, retry."""

import re
import urllib.parse
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_
from sqlalchemy.orm import Session

from server.auth import get_current_user
from server.models import get_db
from server.models.task import TaskQueue
from server.models.user import User
from server.services.effect_webhook import push_effect_event
from server.services.export import DEFAULT_EXPORT_FIELDS, generate_csv, generate_xlsx

router = APIRouter(prefix="/api/leads", tags=["leads"])


# ── Models ────────────────────────────────────────

class LeadSummary(BaseModel):
    id: int
    status: str
    status_label: str = ""
    platform: str = ""
    keyword: str = ""
    video_id: str = ""
    user_name: str = ""
    text: str = ""
    ai_reply: str = ""
    error: str = ""
    retry_count: int = 0
    fetched_at: str = ""
    processed_at: str = ""
    claimed_at: str = ""


class LeadExportRequest(BaseModel):
    industry_slug: str
    status: str | None = None
    format: Literal["csv", "xlsx"] = "xlsx"
    limit: int = Field(default=5000, ge=1, le=10000)
    fields: list[str] | None = None

    @field_validator("industry_slug")
    @classmethod
    def validate_industry_slug(cls, value: str) -> str:
        if value and re.search(r"[^a-z0-9_-]", value):
            raise ValueError("industry_slug must contain only lowercase letters, numbers, underscores, and hyphens")
        return value


class MarkRepliedRequest(BaseModel):
    reply_text: str = ""


class MarkConvertedRequest(BaseModel):
    conversion_value: str = ""


TASK_STATUS_LABELS = {
    "pending": "待发送",
    "claimed": "执行中",
    "done": "已发送",
    "failed": "失败",
}


def _task_label(status: str) -> str:
    return TASK_STATUS_LABELS.get(status, status)


def _taskqueue_row_to_dict(row) -> dict:
    d = {c.name: getattr(row, c.name) for c in TaskQueue.__table__.columns}
    d["matched_categories"] = d.get("matched_categories", "")
    return d


def _lead_from_row(row: dict) -> dict:
    return {
        "id": row["id"],
        "status": row.get("status", ""),
        "status_label": _task_label(row.get("status", "")),
        "platform": row.get("platform", ""),
        "keyword": row.get("keyword", ""),
        "video_id": row.get("video_id", ""),
        "user_name": row.get("user_name", ""),
        "text": row.get("text", ""),
        "ai_reply": row.get("ai_reply", ""),
        "error": row.get("error", ""),
        "retry_count": int(row.get("retry_count", 0) or 0),
        "fetched_at": row.get("fetched_at", ""),
        "processed_at": row.get("processed_at", ""),
        "claimed_at": row.get("claimed_at", ""),
    }


def _owner_filter(current_user: User):
    """Return an OR filter matching rows owned by the current user or unowned."""
    return or_(
        TaskQueue.owner_user_id == current_user.id,
        TaskQueue.owner_user_id == "",
        TaskQueue.owner_user_id.is_(None),
    )


# ── Routes ────────────────────────────────────────

@router.get("")
def list_leads(
    current_user: User = Depends(get_current_user),
    industry_slug: str = Query(default=""),
    status: str = Query(default=""),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List leads with optional filtering by status and industry."""
    try:
        from server.models import SessionLocal
        db = SessionLocal()
    except Exception:
        return {"leads": [], "total": 0}

    try:
        query = db.query(TaskQueue).filter(_owner_filter(current_user))
        if industry_slug:
            query = query.filter(TaskQueue.industry_slug == industry_slug)
        if status:
            query = query.filter(TaskQueue.status == status)

        total = query.count()
        rows = query.order_by(TaskQueue.fetched_at.desc()).limit(limit).offset(offset).all()

        leads = [_lead_from_row(_taskqueue_row_to_dict(r)) for r in rows]
    finally:
        db.close()

    return {"leads": leads, "total": total, "limit": limit, "offset": offset}


@router.get("/stats")
def lead_stats(
    current_user: User = Depends(get_current_user),
    industry_slug: str = Query(default=""),
):
    """Get lead pool statistics by status."""
    try:
        from server.services.task_stats import queue_stats
        stats = queue_stats(industry_slug, owner_user_id=current_user.id)
        return {
            "total": stats.get("total", 0),
            "pending": stats.get("pending", 0),
            "claimed": stats.get("claimed", 0),
            "done": stats.get("done", 0),
            "failed": stats.get("failed", 0),
        }
    except Exception:
        return {"total": 0, "pending": 0, "claimed": 0, "done": 0, "failed": 0}


@router.post("/retry-failed")
def retry_failed_leads(
    current_user: User = Depends(get_current_user),
    industry_slug: str = Query(default=""),
):
    """Reset all failed leads in an industry back to pending for retry."""
    try:
        from server.models import SessionLocal
        db = SessionLocal()
    except Exception:
        raise HTTPException(status_code=500, detail="Queue unavailable")

    try:
        query = db.query(TaskQueue).filter(
            TaskQueue.status == 'failed',
            _owner_filter(current_user),
        )
        if industry_slug:
            query = query.filter(TaskQueue.industry_slug == industry_slug)
        n = query.update({
            TaskQueue.status: 'pending',
            TaskQueue.consumer_id: None,
            TaskQueue.claim_token: None,
            TaskQueue.claimed_at: None,
            TaskQueue.error: ''
        })
        db.commit()
        return {"ok": True, "retried": n}
    finally:
        db.close()


@router.post("/export")
def export_leads(
    req: LeadExportRequest,
    current_user = Depends(get_current_user),
):
    """Export leads as CSV or XLSX."""
    from server.models import SessionLocal

    db = SessionLocal()
    try:
        query = db.query(TaskQueue).filter(
            TaskQueue.industry_slug == req.industry_slug,
            _owner_filter(current_user),
        )
        if req.status:
            query = query.filter(TaskQueue.status == req.status)

        total = query.count()
        if total > req.limit:
            raise HTTPException(
                status_code=400,
                detail=f"结果 {total} 条超过限制 {req.limit}，请缩小筛选范围",
            )

        rows = query.order_by(TaskQueue.fetched_at.desc()).limit(req.limit).offset(0).all()
        fields = req.fields or DEFAULT_EXPORT_FIELDS

        lead_rows = [_taskqueue_row_to_dict(r) for r in rows]

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"leads_{req.industry_slug}_{timestamp}"
        quoted_filename = urllib.parse.quote(filename, safe='')

        if req.format == "csv":
            return StreamingResponse(
                generate_csv(lead_rows, fields=fields),
                media_type="text/csv; charset=utf-8-sig",
                headers={"Content-Disposition": f"attachment; filename=\"{quoted_filename}.csv\""},
            )
        elif req.format == "xlsx":
            buffer = generate_xlsx(lead_rows, fields=fields)
            return StreamingResponse(
                buffer,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f"attachment; filename=\"{quoted_filename}.xlsx\""},
            )
        else:
            raise HTTPException(status_code=400, detail="format 必须是 csv 或 xlsx")
    finally:
        db.close()


@router.post("/{lead_id}/mark-replied")
def mark_lead_replied(
    lead_id: int,
    body: MarkRepliedRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from server.models.task import TaskQueue
    lead = db.query(TaskQueue).filter(
        TaskQueue.id == lead_id,
        TaskQueue.owner_user_id == current_user.id,
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="线索不存在")
    if lead.status not in ("done", "replied", "converted"):
        raise HTTPException(status_code=400, detail="只能标记已发送的线索")

    lead.status = "replied"
    lead.replied_at = datetime.now(timezone.utc)
    lead.reply_text = body.reply_text
    db.commit()

    if lead.industry_slug:
        from server.models.industry import Industry
        industry = db.query(Industry).filter(
            Industry.slug == lead.industry_slug,
            Industry.user_id == current_user.id,
        ).first()
        if industry and industry.effect_webhook_url:
            push_effect_event(
                "lead.replied",
                lead.industry_slug,
                {"id": lead.id, "reply_text": lead.reply_text},
                industry.effect_webhook_url,
            )

    return {"ok": True, "lead_id": lead_id, "status": "replied"}


@router.post("/{lead_id}/mark-converted")
def mark_lead_converted(
    lead_id: int,
    body: MarkConvertedRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from server.models.task import TaskQueue
    lead = db.query(TaskQueue).filter(
        TaskQueue.id == lead_id,
        TaskQueue.owner_user_id == current_user.id,
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="线索不存在")
    if lead.status not in ("sent", "replied", "done"):
        raise HTTPException(status_code=400, detail="只能标记已发送或已回复的线索")

    lead.status = "converted"
    lead.converted_at = datetime.now(timezone.utc)
    lead.conversion_value = body.conversion_value
    db.commit()

    if lead.industry_slug:
        from server.models.industry import Industry
        industry = db.query(Industry).filter(
            Industry.slug == lead.industry_slug,
            Industry.user_id == current_user.id,
        ).first()
        if industry and industry.effect_webhook_url:
            push_effect_event(
                "lead.converted",
                lead.industry_slug,
                {"id": lead.id, "conversion_value": lead.conversion_value},
                industry.effect_webhook_url,
            )

    return {"ok": True, "lead_id": lead_id, "status": "converted"}


@router.post("/{lead_id}/unmark-converted")
def unmark_lead_converted(
    lead_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from server.models.task import TaskQueue
    lead = db.query(TaskQueue).filter(
        TaskQueue.id == lead_id,
        TaskQueue.owner_user_id == current_user.id,
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="线索不存在")
    if lead.status != "converted":
        raise HTTPException(status_code=400, detail="只能撤销已转化标记")

    lead.status = "replied" if lead.replied_at else "done"
    lead.converted_at = None
    lead.conversion_value = ""
    db.commit()
    return {"ok": True, "lead_id": lead_id, "status": lead.status}
