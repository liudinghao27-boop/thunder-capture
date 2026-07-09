"""Dashboard aggregation endpoint — single source of truth for the frontend.

GET /api/dashboard/state returns everything the UI needs to render:
project status, lead inventory, device matrix, active jobs, next_action.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from server.auth import get_current_user
from server.models import get_db
from server.models.device import Device
from server.models.industry import Industry
from server.models.job import Job
from server.models.user import User
from server.secret_store import has_secret
from server.services.agent_decision import (
    decision_reason,
    decision_screenshot,
    extract_agent_decision,
    extract_decision_from_health,
    extract_decision_from_snapshot,
)
from server.workers import (
    reconcile_orphaned_running_jobs,
    reconcile_stale_cancellations,
)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


class DashboardProject(BaseModel):
    industry_count: int
    active_industry_slug: str
    active_industry_name: str


class DashboardFunnel(BaseModel):
    intent_pass_rate: float | None = None
    success_rate: float | None = None
    inventory_days_remaining: float | None = None


class DashboardLeadInventory(BaseModel):
    pending: int
    claimed: int
    done: int
    failed: int
    total: int
    funnel: DashboardFunnel


class DashboardDevice(BaseModel):
    id: str
    name: str
    adb_serial: str
    status: str
    status_label: str
    keyboard_ready: bool
    health_score: int
    consecutive_failures: int
    daily_limit: int = 0
    daily_sent: int = 0
    daily_remaining: int = 0
    hourly_sent: int = 0
    hourly_window_started_at: str = ""
    cooldown_active: bool = False
    cooldown_remaining_seconds: int = 0
    last_error: str
    cooldown_until: str | None = None
    last_heartbeat: str | None = None


class DashboardDeviceMatrix(BaseModel):
    total: int
    available: int
    offline: int
    isolated: int
    cooldown: int
    devices: list[DashboardDevice] = Field(default_factory=list)


class DashboardJob(BaseModel):
    job_id: str
    type: str
    status: str
    status_label: str
    progress: int
    industry_slug: str
    error: str | None = None
    cancel_requested: bool
    created_at: str | None = None
    send_summary: dict[str, Any] | None = None
    collect_summary: dict[str, Any] | None = None


class DashboardStateResponse(BaseModel):
    project: DashboardProject
    has_llm: bool
    can_collect: bool
    can_send: bool
    next_action: str
    lead_inventory: DashboardLeadInventory
    device_matrix: DashboardDeviceMatrix
    active_jobs: list[DashboardJob] = Field(default_factory=list)
    has_active_job: bool
    warnings: list[str] = Field(default_factory=list)


# ── Status translation: technical → human ───────────────

DEVICE_STATUS_LABELS = {
    "idle": "可用",
    "running": "执行中",
    "offline": "设备离线",
    "keyboard_error": "ADB键盘异常",
    "cooldown": "冷却中",
    "isolated": "需人工处理",
    "error": "执行异常",
    "cancelled_timeout": "取消超时(需人工处理)",
}

JOB_STATUS_LABELS = {
    "running": "执行中",
    "cancelling": "正在停止",
    "cancelled": "已停止",
    "done": "已完成",
    "failed": "执行失败",
}

TASK_STATUS_LABELS = {
    "pending": "待发送",
    "claimed": "执行中",
    "done": "已发送",
    "failed": "失败",
}


def _device_label(status: str) -> str:
    return DEVICE_STATUS_LABELS.get(status, status)


def _job_label(status: str) -> str:
    return JOB_STATUS_LABELS.get(status, status)


def _as_aware_utc(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _cooldown_remaining_seconds(cooldown_until) -> int:
    dt = _as_aware_utc(cooldown_until)
    if dt is None:
        return 0
    return max(0, int((dt - datetime.now(timezone.utc)).total_seconds()))


def _has_llm_configured(user: User | None) -> bool:
    if any(
        (
            bool(os.getenv("THUNDER_DEEPSEEK_KEY")),
            bool(os.getenv("THUNDER_ZHIPU_KEY")),
            bool(os.getenv("THUNDER_OPENAI_KEY")),
        )
    ):
        return True

    if user and any(
        (
            has_secret(getattr(user, "deepseek_key", "")),
            has_secret(getattr(user, "zhipu_key", "")),
            has_secret(getattr(user, "openai_key", "")),
        )
    ):
        return True

    try:
        from core.config import load_system

        api_keys = load_system().get("api_keys", {})
        return bool(
            api_keys.get("deepseek") or api_keys.get("zhipu") or api_keys.get("openai")
        )
    except Exception as exc:
        logging.getLogger("thunder.api.dashboard").debug(
            "_has_llm_configured system.yaml check failed: %s",
            exc,
        )
        return False


def _next_action(
    lead_pending: int,
    available_devices: int,
    active_job: bool,
    offline_devices: int,
    isolated_devices: int,
) -> str:
    if isolated_devices > 0:
        return f"请先处理 {isolated_devices} 台需人工处理的设备"
    if offline_devices > 0:
        return f"请先检查 {offline_devices} 台离线设备"
    if available_devices == 0:
        return "没有可用设备，请检查设备连接和键盘状态"
    if lead_pending == 0:
        return "没有待发送线索，请先采集"
    if active_job:
        return "发送任务正在执行中"
    return "可以发送"


@router.get("/state", response_model=DashboardStateResponse)
def dashboard_state(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    uid = current_user.id
    has_llm = _has_llm_configured(current_user)

    # ── Active industries ──────────────────────────
    industries = (
        db.query(Industry)
        .filter(Industry.user_id == uid, Industry.is_active.is_(True))
        .all()
    )
    active_slug = industries[0].slug if industries else ""

    # ── Lead inventory ─────────────────────────────
    try:
        from server.services.task_stats import queue_stats, funnel_stats

        queue = (
            queue_stats(active_slug, owner_user_id=uid)
            if active_slug
            else {"total": 0, "pending": 0, "claimed": 0, "done": 0, "failed": 0}
        )
        funnel_raw = funnel_stats(active_slug, owner_user_id=uid) if active_slug else {}
    except Exception as exc:
        logging.getLogger("thunder.api.dashboard").warning(
            "Overview stats failed: %s", exc
        )
        queue = {"total": 0, "pending": 0, "claimed": 0, "done": 0, "failed": 0}
        funnel_raw = {}

    lead_inventory = {
        "pending": queue.get("pending", 0),
        "claimed": queue.get("claimed", 0),
        "done": queue.get("done", 0),
        "failed": queue.get("failed", 0),
        "total": queue.get("total", 0),
        "funnel": {
            "intent_pass_rate": funnel_raw.get("intent_pass_rate"),
            "success_rate": funnel_raw.get("success_rate"),
            "inventory_days_remaining": funnel_raw.get("inventory_days_remaining"),
        },
    }

    # ── Device matrix ──────────────────────────────
    from core.device.manager import load_active_devices
    from server.models.task import ConsumerState

    reconcile_stale_cancellations(uid)
    reconcile_orphaned_running_jobs(uid)

    all_devices = (
        db.query(Device).filter(Device.user_id == uid).order_by(Device.name).all()
    )
    _ = load_active_devices(user_id=uid) if uid else []
    device_ids = [d.id for d in all_devices]
    device_states = {
        row.consumer_id: row
        for row in (
            db.query(ConsumerState)
            .filter(ConsumerState.consumer_id.in_(device_ids))
            .all()
            if device_ids
            else []
        )
    }

    device_matrix = []
    available_count = 0
    offline_count = 0
    isolated_count = 0
    cooldown_count = 0

    for d in all_devices:
        status = d.runtime_status or "idle"
        label = _device_label(status)
        state = device_states.get(d.id)
        daily_limit = int(d.daily_limit or (state.daily_limit if state else 0) or 0)
        daily_sent = int((state.daily_sent if state else 0) or 0)
        cooldown_remaining = _cooldown_remaining_seconds(d.cooldown_until)
        device_matrix.append(
            {
                "id": d.id,
                "name": d.name,
                "adb_serial": d.adb_serial,
                "status": status,
                "status_label": label,
                "keyboard_ready": bool(d.keyboard_ready),
                "health_score": d.health_score or 100,
                "consecutive_failures": d.consecutive_failures or 0,
                "daily_limit": daily_limit,
                "daily_sent": daily_sent,
                "daily_remaining": max(daily_limit - daily_sent, 0)
                if daily_limit > 0
                else 0,
                "hourly_sent": int((state.wave_sent if state else 0) or 0),
                "hourly_window_started_at": str(
                    (state.rate_limited_at if state else "") or ""
                ),
                "cooldown_active": cooldown_remaining > 0,
                "cooldown_remaining_seconds": cooldown_remaining,
                "last_error": d.last_error or "",
                "cooldown_until": d.cooldown_until.isoformat()
                if d.cooldown_until
                else None,
                "last_heartbeat": d.last_heartbeat.isoformat()
                if d.last_heartbeat
                else None,
            }
        )
        if status == "idle":
            available_count += 1
        elif status == "offline":
            offline_count += 1
        elif status == "isolated":
            isolated_count += 1
        elif status == "cooldown":
            cooldown_count += 1

    # ── Active jobs ────────────────────────────────
    active_jobs = (
        db.query(Job)
        .filter(Job.user_id == uid, Job.status.in_(["running", "cancelling"]))
        .order_by(Job.created_at.desc())
        .limit(5)
        .all()
    )
    active_job = bool(active_jobs)
    jobs_data = [
        {
            "job_id": j.id,
            "type": j.type,
            "status": j.status,
            "status_label": _job_label(j.status),
            "progress": j.progress or 0,
            "industry_slug": j.industry_slug or "",
            "error": j.error,
            "cancel_requested": bool(j.cancel_requested),
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "send_summary": (j.payload or {}).get("send_summary"),
            "collect_summary": (j.payload or {}).get("collect_summary"),
        }
        for j in active_jobs
    ]

    # ── Sentinel checks ────────────────────────────
    can_collect = not active_job or all(
        j.type != "collect" or j.status not in ("running", "cancelling")
        for j in active_jobs
    )
    can_send = bool(
        lead_inventory["pending"] > 0 and available_count > 0 and not active_job
    )

    # ── Warnings ───────────────────────────────────
    warnings = []
    if offline_count > 0:
        warnings.append(f"{offline_count} 台设备离线")
    if isolated_count > 0:
        warnings.append(f"{isolated_count} 台设备需人工处理")
    if cooldown_count > 0:
        warnings.append(f"{cooldown_count} 台设备冷却中")
    if lead_inventory["pending"] == 0:
        warnings.append("没有待发送线索")
    if lead_inventory["failed"] > 0:
        warnings.append(f"{lead_inventory['failed']} 条线索发送失败")

    return {
        "project": {
            "industry_count": len(industries),
            "active_industry_slug": active_slug,
            "active_industry_name": industries[0].name if industries else "",
        },
        "has_llm": has_llm,
        "can_collect": can_collect,
        "can_send": can_send,
        "next_action": _next_action(
            lead_inventory["pending"],
            available_count,
            active_job,
            offline_count,
            isolated_count,
        ),
        "lead_inventory": lead_inventory,
        "device_matrix": {
            "total": len(device_matrix),
            "available": available_count,
            "offline": offline_count,
            "isolated": isolated_count,
            "cooldown": cooldown_count,
            "devices": device_matrix,
        },
        "active_jobs": jobs_data,
        "has_active_job": active_job,
        "warnings": warnings,
    }


@router.get("/execution")
def execution_monitor(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    job_id: str = Query(default=""),
):
    """Per-device execution state for the send monitor panel."""
    from server.models.matrix import DeviceState, ExecutionLog, ScreenSnapshot

    # Active device states
    query = db.query(DeviceState).filter(DeviceState.user_id == current_user.id)
    if job_id:
        query = query.filter(DeviceState.job_id == job_id)
    states = query.order_by(DeviceState.updated_at.desc()).limit(20).all()

    devices = []
    for s in states:
        # Latest execution log for this device
        last_log = (
            db.query(ExecutionLog)
            .filter(
                ExecutionLog.user_id == current_user.id,
                ExecutionLog.device_id == s.device_id,
            )
            .order_by(ExecutionLog.created_at.desc())
            .first()
        )
        # Latest screenshot
        last_shot = (
            db.query(ScreenSnapshot)
            .filter(
                ScreenSnapshot.user_id == current_user.id,
                ScreenSnapshot.device_id == s.device_id,
            )
            .order_by(ScreenSnapshot.created_at.desc())
            .first()
        )
        last_payload = (
            last_log.payload if last_log and isinstance(last_log.payload, dict) else {}
        )
        health = s.health if isinstance(s.health, dict) else {}
        ui_tree = (
            last_shot.ui_tree
            if last_shot and isinstance(last_shot.ui_tree, dict)
            else {}
        )
        agent_decision = (
            extract_agent_decision(last_payload)
            or extract_decision_from_health(health)
            or extract_decision_from_snapshot(ui_tree)
        )
        devices.append(
            {
                "device_id": s.device_id,
                "status": s.status,
                "current_screen": s.current_screen or "",
                "current_app": s.current_app or "",
                "last_action": last_log.action if last_log else "",
                "last_action_status": last_log.status if last_log else "",
                "last_screenshot": last_shot.image_path if last_shot else "",
                "last_ocr": (last_shot.ocr_text or "")[:200] if last_shot else "",
                "agent_decision": agent_decision,
                "decision_reason": decision_reason(agent_decision),
                "decision_screenshot": decision_screenshot(agent_decision)
                or (last_shot.image_path if last_shot else ""),
                "consecutive_failures": s.consecutive_failures or 0,
                "last_heartbeat": s.last_heartbeat.isoformat()
                if s.last_heartbeat
                else None,
            }
        )

    active_job = (
        db.query(Job)
        .filter(Job.user_id == current_user.id, Job.status == "running")
        .first()
    )

    return {
        "has_active_job": bool(active_job),
        "active_job_id": active_job.id if active_job else "",
        "active_job_status": active_job.status if active_job else "",
        "devices": devices,
    }


@router.get("/funnel")
def funnel_analytics(
    current_user: User = Depends(get_current_user),
    industry_slug: str = Query(default=""),
):
    """Funnel analytics + replenishment recommendation."""
    try:
        from server.services.task_stats import (
            funnel_stats,
            replenishment_plan,
            queue_stats,
        )
    except Exception as exc:
        logging.getLogger("thunder.api.dashboard").warning(
            "Readiness check failed: %s", exc
        )
        return {"ok": False, "error": "Engine unavailable"}

    uid = current_user.id
    stats = (
        queue_stats(industry_slug, owner_user_id=uid)
        if industry_slug
        else queue_stats(owner_user_id=uid)
    )
    funnel_raw = (
        funnel_stats(industry_slug, owner_user_id=uid)
        if industry_slug
        else funnel_stats(owner_user_id=uid)
    )

    # Replenishment recommendation
    replenish = {}
    if industry_slug:
        try:
            replenish = replenishment_plan(
                industry_slug,
                per_device_daily_limit=10,
                inventory_days=3,
                threshold_days=1,
                owner_user_id=uid,
            )
        except Exception as exc:
            logging.getLogger("thunder.api.dashboard").debug(
                "Failure distribution query failed: %s", exc
            )

    # Failure reason distribution
    try:
        from server.models import SessionLocal
        from server.models.task import TaskQueue
        from sqlalchemy import func

        db = SessionLocal()
        failures = (
            db.query(TaskQueue.error, func.count(TaskQueue.id).label("cnt"))
            .filter(
                TaskQueue.status == "failed",
                TaskQueue.industry_slug == industry_slug,
                TaskQueue.owner_user_id == uid,
            )
            .group_by(TaskQueue.error)
            .order_by(func.count(TaskQueue.id).desc())
            .limit(10)
            .all()
        )
        db.close()
        failure_dist = [
            {"reason": (r[0] or "unknown")[:100], "count": r[1]} for r in failures
        ]
    except Exception as exc:
        logging.getLogger("thunder.api.dashboard").debug(
            "Failure distribution aggregation failed: %s", exc
        )
        failure_dist = []

    return {
        "today_sent": stats.get("done", 0),
        "total_pending": stats.get("pending", 0),
        "total_failed": stats.get("failed", 0),
        "success_rate": funnel_raw.get("success_rate"),
        "intent_pass_rate": funnel_raw.get("intent_pass_rate"),
        "inventory_days_remaining": funnel_raw.get("inventory_days_remaining"),
        "should_replenish": replenish.get("should_replenish", False),
        "replenish_recommended": replenish.get("replenish_recommended", False),
        "replenish_mode": replenish.get("mode", ""),
        "failure_distribution": failure_dist,
    }
