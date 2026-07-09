"""Agent planning, perception, and action routes."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.agent.executor import AgentExecutor
from core.agent.memory import AgentMemoryStore
from core.agent.perception import PerceptionService
from core.agent.planner import Planner
from core.agent.state import ActionStep
from server.auth import get_current_user
from server.config import BASE_DIR
from server.models import get_db
from server.models.device import Device
from server.models.industry import Industry
from server.models.matrix import DeviceState, ExecutionLog, TaskGraph
from server.models.user import User
from server.services.agent_decision import (
    extract_agent_decision,
    extract_agent_decisions,
)

router = APIRouter(prefix="/api/agent", tags=["agent"])


class PlanRequest(BaseModel):
    platform: str = "douyin"
    search_target: str = ""
    user_name: str = ""
    message: str
    industry_id: str | None = None


class ObserveRequest(BaseModel):
    device_id: str
    industry_id: str | None = None
    save_snapshot: bool = False


class ActRequest(BaseModel):
    device_id: str
    action: str
    target: str = ""
    payload: dict = Field(default_factory=dict)
    industry_id: str | None = None


class ExecutionLogOut(BaseModel):
    id: str
    job_id: str
    device_id: str
    action: str
    target: str
    status: str
    detail: str
    latency_ms: int | None = None
    payload: dict = Field(default_factory=dict)
    agent_decision: dict | None = None
    agent_decisions: dict = Field(default_factory=dict)
    created_at: str | None = None


def _get_owned_device(device_id: str, current_user: User, db: Session) -> Device:
    device = (
        db.query(Device)
        .filter(Device.id == device_id, Device.user_id == current_user.id)
        .first()
    )
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


def _industry_slug(industry_id: str | None, current_user: User, db: Session) -> str:
    if not industry_id:
        return ""
    industry = (
        db.query(Industry)
        .filter(Industry.id == industry_id, Industry.user_id == current_user.id)
        .first()
    )
    if not industry:
        raise HTTPException(status_code=404, detail="Industry not found")
    return industry.slug


@router.post("/plan")
def plan_agent_task(
    body: PlanRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    industry_slug = _industry_slug(body.industry_id, current_user, db)
    plan = Planner().plan_dm(
        body.platform,
        body.search_target,
        body.user_name,
        body.message,
    )
    if industry_slug:
        AgentMemoryStore(current_user.id, industry_slug).save_plan(
            plan, name=plan.goal[:128]
        )
    return {"ok": True, "plan": plan.as_dict()}


@router.post("/observe")
def observe_device(
    body: ObserveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    device = _get_owned_device(body.device_id, current_user, db)
    industry_slug = _industry_slug(body.industry_id, current_user, db)
    screenshot_dir = None
    if body.save_snapshot:
        screenshot_dir = Path(BASE_DIR) / "data" / "screen_snapshots" / current_user.id
    observation = PerceptionService().observe(
        device_id=device.id,
        adb_serial=device.adb_serial,
        screenshot_dir=screenshot_dir,
    )
    if body.save_snapshot or industry_slug:
        AgentMemoryStore(current_user.id, industry_slug).save_observation(observation)
    return {"ok": True, "observation": observation.as_dict()}


@router.post("/act")
def execute_agent_action(
    body: ActRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    device = _get_owned_device(body.device_id, current_user, db)
    industry_slug = _industry_slug(body.industry_id, current_user, db)
    result = AgentExecutor(device.adb_serial).execute(
        ActionStep(action=body.action, target=body.target, payload=body.payload)
    )
    AgentMemoryStore(current_user.id, industry_slug).log_execution(
        result,
        device_id=device.id,
        target=body.target,
        payload=body.payload,
    )
    return {"ok": result.ok, "result": result.as_dict()}


@router.get("/device-state")
def list_agent_device_state(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    industry_slug: str = "",
):
    query = db.query(DeviceState).filter(DeviceState.user_id == current_user.id)
    rows = query.order_by(DeviceState.updated_at.desc()).all()
    return [
        {
            "id": row.id,
            "device_id": row.device_id,
            "job_id": row.job_id,
            "status": row.status,
            "current_app": row.current_app,
            "current_screen": row.current_screen,
            "health": row.health or {},
            "consecutive_failures": row.consecutive_failures,
            "last_heartbeat": row.last_heartbeat.isoformat()
            if row.last_heartbeat
            else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        for row in rows
    ]


@router.get("/task-graphs")
def list_agent_task_graphs(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    industry_slug: str = "",
    limit: int = 50,
):
    limit = max(1, min(int(limit or 50), 200))
    query = db.query(TaskGraph).filter(TaskGraph.user_id == current_user.id)
    if industry_slug:
        query = query.filter(TaskGraph.industry_slug == industry_slug)
    rows = query.order_by(TaskGraph.updated_at.desc()).limit(limit).all()
    return [
        {
            "id": row.id,
            "industry_slug": row.industry_slug,
            "job_id": row.job_id,
            "name": row.name,
            "task_type": row.task_type,
            "status": row.status,
            "priority": row.priority,
            "graph": row.graph or {},
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        for row in rows
    ]


@router.get("/execution-logs", response_model=list[ExecutionLogOut])
def list_agent_execution_logs(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    job_id: str = "",
    device_id: str = "",
    limit: int = 100,
):
    limit = max(1, min(int(limit or 100), 500))
    query = db.query(ExecutionLog).filter(ExecutionLog.user_id == current_user.id)
    if job_id:
        query = query.filter(ExecutionLog.job_id == job_id)
    if device_id:
        query = query.filter(ExecutionLog.device_id == device_id)
    rows = query.order_by(ExecutionLog.created_at.desc()).limit(limit).all()
    results = []
    for row in rows:
        payload = row.payload if isinstance(row.payload, dict) else {}
        results.append(
            {
                "id": row.id,
                "job_id": row.job_id,
                "device_id": row.device_id,
                "action": row.action,
                "target": row.target,
                "status": row.status,
                "detail": row.detail,
                "latency_ms": row.latency_ms,
                "payload": payload,
                "agent_decision": extract_agent_decision(payload),
                "agent_decisions": extract_agent_decisions(payload),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )
    return results
