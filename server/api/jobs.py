"""Job management routes for collect/send execution."""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from server.auth import get_current_user
from server.models import get_db
from server.models.job import Job
from server.models.matrix import DeviceState, ExecutionLog, ScreenSnapshot
from server.models.user import User
from server.services.agent_decision import (
    extract_agent_decision,
    extract_agent_decisions,
)
from server.workers import (
    cancel_job,
    get_job_status,
    reconcile_orphaned_running_jobs,
    reconcile_stale_cancellations,
)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

_RAW_STATUS_LABELS = {
    "running": "执行中",
    "cancelling": "取消中",
    "cancelled": "已取消",
    "done": "已完成",
    "failed": "失败",
    "unknown": "未知",
}

_NORMALIZED_STATUS_LABELS = {
    "running": "执行中",
    "cancelling": "取消中",
    "cancelled": "已取消",
    "sent": "已发送",
    "restricted": "已确认受限",
    "unconfirmed": "未确认",
    "done": "已完成",
    "failed": "失败",
    "no_data": "完成但未采集到数据",
    "needs_attention": "完成但需关注",
}

_RESTRICTED_MARKERS = (
    "blocked",
    "captcha",
    "login_required",
    "real_name_verification",
    "risk_control",
    "对方回复后才能发消息",
    "实名认证",
    "刷脸",
    "人脸识别",
    "验证",
    "no_source_comments",
    "discovery_timeout",
    "collect_failed",
    "aweme_list",
    "account blocked",
)


def _isoformat(value) -> str | None:
    if not value:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _clean_text(value: str | None) -> str:
    return str(value or "").strip()


def _payload_summary(payload: dict | None, key: str) -> dict | None:
    summary = (payload or {}).get(key)
    return summary if isinstance(summary, dict) else None


def _serialize_snapshot(snapshot: ScreenSnapshot | None) -> dict | None:
    if snapshot is None:
        return None
    ui_tree = snapshot.ui_tree if isinstance(snapshot.ui_tree, dict) else {}
    return {
        "device_id": snapshot.device_id,
        "screen_name": snapshot.screen_name,
        "image_path": snapshot.image_path,
        "ocr_text": snapshot.ocr_text,
        "blocker": _clean_text(ui_tree.get("blocker") or snapshot.blocker),
        "confidence": ui_tree.get("confidence") or snapshot.confidence or 0,
        "captured_at": _isoformat(snapshot.captured_at),
    }


def _serialize_execution(log_row: ExecutionLog | None) -> dict | None:
    if log_row is None:
        return None
    payload = log_row.payload if isinstance(log_row.payload, dict) else {}
    agent_decisions = extract_agent_decisions(payload)
    agent_decision = extract_agent_decision(payload)
    return {
        "device_id": log_row.device_id,
        "action": log_row.action,
        "status": log_row.status,
        "detail": log_row.detail,
        "latency_ms": log_row.latency_ms,
        "payload": payload,
        "send_verification": payload.get("send_verification"),
        "agent_decision": agent_decision,
        "agent_decisions": agent_decisions,
        "created_at": _isoformat(log_row.created_at),
    }


def _serialize_device_state(state: DeviceState | None) -> dict | None:
    if state is None:
        return None
    return {
        "device_id": state.device_id,
        "job_id": state.job_id,
        "status": state.status,
        "current_app": state.current_app,
        "current_screen": state.current_screen,
        "health": state.health or {},
        "consecutive_failures": int(state.consecutive_failures or 0),
        "last_heartbeat": _isoformat(state.last_heartbeat),
        "updated_at": _isoformat(state.updated_at),
    }


def _extract_sent_count(send_summary: dict | None) -> int:
    if not send_summary:
        return 0
    direct = send_summary.get("sent_total")
    if direct is None:
        direct = send_summary.get("sent")
    if direct is not None:
        try:
            return int(direct)
        except (TypeError, ValueError):
            return 0
    devices = send_summary.get("devices") or []
    return sum(
        int(device.get("sent") or 0) for device in devices if isinstance(device, dict)
    )


def _extract_failed_count(send_summary: dict | None) -> int:
    if not send_summary:
        return 0
    direct = send_summary.get("failed_total")
    if direct is None:
        direct = send_summary.get("failed")
    if direct is not None:
        try:
            return int(direct)
        except (TypeError, ValueError):
            return 0
    devices = send_summary.get("devices") or []
    return sum(
        int(device.get("failed") or 0) for device in devices if isinstance(device, dict)
    )


def _match_restricted_reason(*values: str | None) -> str:
    for value in values:
        text = _clean_text(value)
        lowered = text.casefold()
        if text and any(marker in lowered for marker in _RESTRICTED_MARKERS):
            return text
    return ""


def _normalize_job_status(
    *,
    job_type: str,
    raw_status: str,
    send_summary: dict | None,
    collect_summary: dict | None,
    error: str | None,
    latest_execution: dict | None,
    latest_snapshot: dict | None,
) -> tuple[str, str, str]:
    if raw_status in {"running", "cancelling", "cancelled"}:
        return raw_status, _NORMALIZED_STATUS_LABELS[raw_status], ""

    if job_type != "send":
        # Collect jobs: surface empty result / platform restriction explicitly.
        empty_reason = _clean_text((collect_summary or {}).get("empty_reason"))
        warning = _clean_text((collect_summary or {}).get("warning"))
        candidate_comments = int((collect_summary or {}).get("candidate_comments") or 0)
        enqueued = int((collect_summary or {}).get("enqueued") or 0)
        phase = _clean_text((collect_summary or {}).get("phase"))

        if raw_status == "failed":
            return (
                raw_status or "unknown",
                _RAW_STATUS_LABELS.get(raw_status or "unknown", "未知"),
                _clean_text(error)
                or warning
                or empty_reason
                or phase
                or "采集任务失败",
            )

        if raw_status == "done":
            if candidate_comments == 0:
                # Distinguish platform restriction from simple empty keyword.
                if (
                    empty_reason in ("no_source_comments", "discovery_timeout")
                    or "风控" in warning
                    or "验证码" in warning
                ):
                    return (
                        "needs_attention",
                        _NORMALIZED_STATUS_LABELS["needs_attention"],
                        warning
                        or empty_reason
                        or "平台未返回任何评论数据，建议检查登录态、网络/代理或目标站点风控状态",
                    )
                return (
                    "no_data",
                    _NORMALIZED_STATUS_LABELS["no_data"],
                    warning or empty_reason or "完成但未采集到匹配评论",
                )
            if enqueued == 0 and candidate_comments > 0:
                return (
                    "needs_attention",
                    _NORMALIZED_STATUS_LABELS["needs_attention"],
                    warning or "采集到候选评论但全部被过滤/重复",
                )
            return "done", _NORMALIZED_STATUS_LABELS["done"], ""

        return (
            raw_status or "unknown",
            _RAW_STATUS_LABELS.get(raw_status or "unknown", "未知"),
            _clean_text(error),
        )

    send_verification = (latest_execution or {}).get("send_verification") or {}
    verification_reason = _clean_text(send_verification.get("reason"))
    snapshot_blocker = _clean_text((latest_snapshot or {}).get("blocker"))
    execution_status = _clean_text((latest_execution or {}).get("status"))
    execution_detail = _clean_text((latest_execution or {}).get("detail"))
    restricted_reason = _match_restricted_reason(
        snapshot_blocker,
        verification_reason,
        execution_status,
        execution_detail,
        error,
    )
    sent_count = _extract_sent_count(send_summary)
    failed_count = _extract_failed_count(send_summary)
    verification_ok = bool(send_verification.get("ok"))

    if raw_status == "done":
        if sent_count > 0 or verification_ok:
            final_reason = "发送确认成功"
            if snapshot_blocker:
                final_reason = f"{final_reason}；后置页面提示：{snapshot_blocker}"
            return "sent", _NORMALIZED_STATUS_LABELS["sent"], final_reason
        if restricted_reason:
            return (
                "restricted",
                _NORMALIZED_STATUS_LABELS["restricted"],
                f"执行受限：{restricted_reason}",
            )
        if verification_reason == "unconfirmed_send":
            return (
                "unconfirmed",
                _NORMALIZED_STATUS_LABELS["unconfirmed"],
                "消息动作完成，但未能确认已发送",
            )
        return "done", _NORMALIZED_STATUS_LABELS["done"], ""

    if (
        verification_reason == "unconfirmed_send"
        or execution_status == "unconfirmed_send"
        or _clean_text(error) == "unconfirmed_send"
    ):
        return (
            "unconfirmed",
            _NORMALIZED_STATUS_LABELS["unconfirmed"],
            "消息动作已执行，但未能确认已发送",
        )
    if restricted_reason:
        return (
            "restricted",
            _NORMALIZED_STATUS_LABELS["restricted"],
            f"执行受限：{restricted_reason}",
        )
    if sent_count > 0 and failed_count == 0:
        return "sent", _NORMALIZED_STATUS_LABELS["sent"], "发送确认成功"
    return (
        "failed",
        _NORMALIZED_STATUS_LABELS["failed"],
        _clean_text(error) or execution_detail,
    )


def _job_operational_flags(
    *,
    raw_status: str,
    normalized_status: str,
    error: str | None,
    final_reason: str | None,
) -> dict:
    retryable_statuses = {
        "failed",
        "cancelled",
        "restricted",
        "unconfirmed",
        "no_data",
        "needs_attention",
    }
    terminal_statuses = {
        "done",
        "failed",
        "cancelled",
        "sent",
        "restricted",
        "unconfirmed",
        "no_data",
        "needs_attention",
    }
    return {
        "can_cancel": raw_status in {"queued", "running", "cancelling"},
        "can_retry": raw_status in retryable_statuses
        or normalized_status in retryable_statuses,
        "failure_reason": _clean_text(final_reason) or _clean_text(error),
        "quota_released": raw_status in terminal_statuses
        or normalized_status in terminal_statuses,
    }


def _build_job_payload(
    *,
    job_id: str,
    job_type: str,
    raw_status: str,
    progress: int,
    industry_slug: str,
    industry_name: str,
    error: str | None,
    cancel_requested: bool,
    created_at,
    updated_at,
    completed_at,
    payload: dict | None,
    send_summary: dict | None,
    collect_summary: dict | None,
    latest_execution: dict | None = None,
    latest_snapshot: dict | None = None,
) -> dict:
    normalized_status, status_label, final_reason = _normalize_job_status(
        job_type=job_type,
        raw_status=raw_status,
        send_summary=send_summary,
        collect_summary=collect_summary,
        error=error,
        latest_execution=latest_execution,
        latest_snapshot=latest_snapshot,
    )
    operational_flags = _job_operational_flags(
        raw_status=raw_status,
        normalized_status=normalized_status,
        error=error,
        final_reason=final_reason,
    )
    active_device_ids = []
    for device in (send_summary or {}).get("devices") or []:
        if isinstance(device, dict) and device.get("device_id"):
            active_device_ids.append(str(device["device_id"]))
    return {
        "job_id": job_id,
        "type": job_type,
        "status": raw_status,
        "normalized_status": normalized_status,
        "status_label": status_label,
        "final_reason": final_reason or None,
        "progress": progress,
        "industry_slug": industry_slug,
        "industry_name": industry_name,
        "error": error,
        "cancel_requested": cancel_requested,
        "created_at": _isoformat(created_at),
        "updated_at": _isoformat(updated_at),
        "completed_at": _isoformat(completed_at),
        "payload": payload or {},
        "send_summary": send_summary,
        "collect_summary": collect_summary,
        "sent_count": _extract_sent_count(send_summary),
        "failed_count": _extract_failed_count(send_summary),
        "active_device_ids": active_device_ids,
        "latest_execution": latest_execution,
        "latest_snapshot": latest_snapshot,
        **operational_flags,
    }


class JobSummary(BaseModel):
    job_id: str
    type: str
    status: str
    normalized_status: str = "unknown"
    status_label: str = "未知"
    final_reason: str | None = None
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
    sent_count: int = 0
    failed_count: int = 0
    active_device_ids: list[str] = Field(default_factory=list)
    latest_execution: dict | None = None
    latest_snapshot: dict | None = None
    can_cancel: bool = False
    can_retry: bool = False
    failure_reason: str = ""
    quota_released: bool = False


class JobDetail(JobSummary):
    worker_alive: bool = True
    released_claimed_tasks: int = 0
    latest_execution: dict | None = None
    latest_snapshot: dict | None = None
    latest_device_state: dict | None = None


class StartJobResponse(BaseModel):
    ok: bool
    job_id: str
    status: str


class JobDeviceState(BaseModel):
    device_id: str
    job_id: str | None = None
    status: str | None = None
    current_app: str | None = None
    current_screen: str | None = None
    health: dict = Field(default_factory=dict)
    consecutive_failures: int = 0
    last_heartbeat: str | None = None
    updated_at: str | None = None


class JobDevicesResponse(BaseModel):
    job_id: str
    job_status: str | None = None
    devices: list[JobDeviceState] = Field(default_factory=list)


@router.get("", response_model=list[JobSummary])
def list_jobs(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    status: str = Query(default=""),
    job_type: str = Query(default=""),
):
    reconcile_stale_cancellations(current_user.id)
    reconcile_orphaned_running_jobs(current_user.id)

    normalized_status_filter = status in {"sent", "restricted", "unconfirmed"}
    query = db.query(Job).filter(Job.user_id == current_user.id)
    if status and not normalized_status_filter:
        query = query.filter(Job.status == status)
    if job_type:
        query = query.filter(Job.type == job_type)

    jobs_query = query.order_by(Job.created_at.desc())
    jobs = (
        jobs_query.all() if normalized_status_filter else jobs_query.limit(limit).all()
    )
    rows = []
    for job in jobs:
        latest_execution = _serialize_execution(
            db.query(ExecutionLog)
            .filter(
                ExecutionLog.user_id == current_user.id, ExecutionLog.job_id == job.id
            )
            .order_by(ExecutionLog.created_at.desc())
            .first()
        )
        latest_snapshot = _serialize_snapshot(
            db.query(ScreenSnapshot)
            .filter(
                ScreenSnapshot.user_id == current_user.id,
                ScreenSnapshot.job_id == job.id,
            )
            .order_by(
                ScreenSnapshot.captured_at.desc(), ScreenSnapshot.created_at.desc()
            )
            .first()
        )
        rows.append(
            JobSummary(
                **_build_job_payload(
                    job_id=job.id,
                    job_type=job.type,
                    raw_status=job.status,
                    progress=int(job.progress or 0),
                    industry_slug=job.industry_slug or "",
                    industry_name=job.industry_name or "",
                    error=job.error,
                    cancel_requested=bool(job.cancel_requested),
                    created_at=job.created_at,
                    updated_at=job.updated_at,
                    completed_at=job.completed_at,
                    payload=job.payload or {},
                    send_summary=_payload_summary(job.payload, "send_summary"),
                    collect_summary=_payload_summary(job.payload, "collect_summary"),
                    latest_execution=latest_execution,
                    latest_snapshot=latest_snapshot,
                )
            )
        )
        if normalized_status_filter and rows[-1].normalized_status != status:
            rows.pop()
            continue
        if normalized_status_filter and len(rows) >= limit:
            break
    return rows


@router.get("/{job_id}", response_model=JobDetail)
def get_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    status = get_job_status(job_id, current_user.id)
    if status is None:
        raise HTTPException(status_code=404, detail="Job not found")

    latest_execution = _serialize_execution(
        db.query(ExecutionLog)
        .filter(ExecutionLog.user_id == current_user.id, ExecutionLog.job_id == job_id)
        .order_by(ExecutionLog.created_at.desc())
        .first()
    )
    latest_snapshot = _serialize_snapshot(
        db.query(ScreenSnapshot)
        .filter(
            ScreenSnapshot.user_id == current_user.id, ScreenSnapshot.job_id == job_id
        )
        .order_by(ScreenSnapshot.captured_at.desc(), ScreenSnapshot.created_at.desc())
        .first()
    )
    latest_device_state = _serialize_device_state(
        db.query(DeviceState)
        .filter(DeviceState.user_id == current_user.id, DeviceState.job_id == job_id)
        .order_by(DeviceState.updated_at.desc())
        .first()
    )
    return JobDetail(
        **_build_job_payload(
            job_id=job_id,
            job_type=status.get("type", "unknown"),
            raw_status=status.get("status", "unknown"),
            progress=int(status.get("progress", 0) or 0),
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
            latest_execution=latest_execution,
            latest_snapshot=latest_snapshot,
        ),
        worker_alive=bool(status.get("_worker_alive", True)),
        released_claimed_tasks=int(status.get("released_claimed_tasks", 0)),
        latest_device_state=latest_device_state,
    )


@router.post("/{job_id}/cancel", response_model=JobSummary)
def cancel_running_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
):
    status = cancel_job(job_id, current_user.id)
    if status is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobSummary(
        **_build_job_payload(
            job_id=job_id,
            job_type=status.get("type", "unknown"),
            raw_status=status.get("status", "unknown"),
            progress=int(status.get("progress", 0) or 0),
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
        )
    )


@router.get("/{job_id}/devices", response_model=JobDevicesResponse)
def get_job_devices(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    status = get_job_status(job_id, current_user.id)
    if status is None:
        raise HTTPException(status_code=404, detail="Job not found")

    devices = (
        db.query(DeviceState)
        .filter(DeviceState.user_id == current_user.id, DeviceState.job_id == job_id)
        .order_by(DeviceState.updated_at.desc())
        .all()
    )
    return {
        "job_id": job_id,
        "job_status": status.get("status"),
        "devices": [
            {
                "device_id": device.device_id,
                "job_id": device.job_id,
                "status": device.status,
                "current_app": device.current_app,
                "current_screen": device.current_screen,
                "health": device.health or {},
                "consecutive_failures": int(device.consecutive_failures or 0),
                "last_heartbeat": _isoformat(device.last_heartbeat),
                "updated_at": _isoformat(device.updated_at),
            }
            for device in devices
        ],
    }


class StartCollectRequest(BaseModel):
    industry_slug: str
    skip_discover: bool = False


@router.post("/collect/start", response_model=StartJobResponse)
def start_collect_job(
    body: StartCollectRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from server.models.industry import Industry
    from server.workers import run_collect_job

    industry = (
        db.query(Industry)
        .filter(
            Industry.slug == body.industry_slug,
            Industry.user_id == current_user.id,
        )
        .first()
    )
    if not industry:
        raise HTTPException(status_code=404, detail="Industry not found")

    job_id = run_collect_job(industry, skip_discover=body.skip_discover)
    status = get_job_status(job_id, current_user.id)
    return {
        "ok": True,
        "job_id": job_id,
        "status": status.get("status") if status else "unknown",
    }


class StartSendRequest(BaseModel):
    industry_slug: str
    device_ids: list[str] | None = None


@router.post("/send/start", response_model=StartJobResponse)
def start_send_job(
    body: StartSendRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from server.models.device import Device
    from server.models.industry import Industry
    from server.models.job import Job as JobModel
    from server.services.task_stats import queue_stats
    from server.workers import run_send_job

    industry = (
        db.query(Industry)
        .filter(
            Industry.slug == body.industry_slug,
            Industry.user_id == current_user.id,
        )
        .first()
    )
    if not industry:
        raise HTTPException(status_code=404, detail="Industry not found")

    try:
        if (
            queue_stats(body.industry_slug, owner_user_id=current_user.id).get(
                "pending", 0
            )
            == 0
        ):
            raise HTTPException(status_code=400, detail="No pending leads")
    except HTTPException:
        raise
    except Exception as exc:
        logging.getLogger("thunder.api.jobs").debug("Queue stats check failed: %s", exc)

    idle_count = (
        db.query(Device)
        .filter(
            Device.user_id == current_user.id,
            Device.runtime_status == "idle",
        )
        .count()
    )
    if idle_count == 0:
        raise HTTPException(status_code=400, detail="No available devices")

    active = (
        db.query(JobModel)
        .filter(
            JobModel.user_id == current_user.id,
            JobModel.type == "send",
            JobModel.status.in_(["running", "cancelling"]),
        )
        .first()
    )
    if active:
        raise HTTPException(status_code=409, detail="Send job already running")

    job_id = run_send_job(industry, body.device_ids)
    status = get_job_status(job_id, current_user.id)
    return {
        "ok": True,
        "job_id": job_id,
        "status": status.get("status") if status else "unknown",
    }
