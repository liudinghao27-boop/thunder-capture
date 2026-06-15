"""Persistence adapter for agent memory, snapshots, and execution logs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.agent.state import ExecutionResult, Observation, Plan


class AgentMemoryStore:
    def __init__(self, user_id: str = "", industry_slug: str = ""):
        self.user_id = user_id
        self.industry_slug = industry_slug

    def _session(self):
        from server.models import SessionLocal

        return SessionLocal()

    def remember(
        self,
        memory_type: str,
        content: dict,
        *,
        device_id: str = "",
        subject_id: str = "",
        subject_type: str = "task",
    ) -> str:
        if not self.user_id:
            return ""
        from server.models.matrix import AgentMemory

        db = self._session()
        try:
            row = AgentMemory(
                user_id=self.user_id,
                industry_slug=self.industry_slug,
                device_id=device_id or None,
                subject_type=subject_type,
                subject_id=subject_id,
                memory_type=memory_type,
                content=content,
            )
            db.add(
                row
            )
            db.commit()
            return row.id
        except Exception:
            db.rollback()
            return ""
        finally:
            db.close()

    def save_plan(
        self,
        plan: Plan,
        *,
        job_id: str = "",
        name: str = "",
        status: str = "ready",
        extra: dict[str, Any] | None = None,
    ) -> str:
        if not self.user_id:
            return ""
        from server.models.matrix import TaskGraph

        db = self._session()
        try:
            graph = plan.as_dict()
            if extra:
                graph["extra"] = extra
            row = TaskGraph(
                user_id=self.user_id,
                industry_slug=self.industry_slug,
                job_id=job_id or None,
                name=name or plan.goal[:128],
                task_type="send",
                status=status,
                graph=graph,
            )
            db.add(
                row
            )
            db.commit()
            return row.id
        except Exception:
            db.rollback()
            return ""
        finally:
            db.close()

    def update_plan_status(
        self,
        graph_id: str,
        status: str,
        *,
        patch: dict[str, Any] | None = None,
    ) -> None:
        if not self.user_id or not graph_id:
            return
        from server.models.matrix import TaskGraph

        db = self._session()
        try:
            row = (
                db.query(TaskGraph)
                .filter(TaskGraph.id == graph_id, TaskGraph.user_id == self.user_id)
                .first()
            )
            if not row:
                return
            graph = dict(row.graph or {})
            if patch:
                graph.update(patch)
            row.graph = graph
            row.status = status
            row.updated_at = datetime.now(timezone.utc)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    def save_observation(self, observation: Observation, *, job_id: str = "") -> None:
        if not self.user_id:
            return
        from server.models.matrix import DeviceState, ScreenSnapshot

        db = self._session()
        try:
            db.add(
                ScreenSnapshot(
                    user_id=self.user_id,
                    device_id=observation.device_id,
                    job_id=job_id or None,
                    screen_name=observation.screen,
                    image_path=observation.screenshot_path,
                    ocr_text=observation.ocr_text,
                    ui_tree={
                        "elements": observation.elements,
                        "confidence": observation.confidence,
                        "blocker": observation.blocker,
                        "evidence": observation.evidence,
                        "errors": observation.errors,
                        "ocr_status": observation.ocr_status,
                        "ocr_provider": observation.ocr_provider,
                        "package_name": observation.package_name,
                        "activity": observation.activity,
                    },
                )
            )
            state = (
                db.query(DeviceState)
                .filter(DeviceState.user_id == self.user_id, DeviceState.device_id == observation.device_id)
                .first()
            )
            if not state:
                state = DeviceState(user_id=self.user_id, device_id=observation.device_id)
                db.add(state)
            state.current_screen = observation.screen
            state.current_app = observation.package_name or state.current_app
            state.health = {
                **(state.health or {}),
                "screen_confidence": observation.confidence,
                "screen_blocker": observation.blocker,
                "screen_evidence": observation.evidence[:8],
                "observation_errors": observation.errors[:8],
                "ocr_status": observation.ocr_status,
                "ocr_provider": observation.ocr_provider,
                "activity": observation.activity,
            }
            state.last_heartbeat = datetime.now(timezone.utc)
            state.updated_at = datetime.now(timezone.utc)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    def update_device_state(
        self,
        *,
        device_id: str,
        job_id: str = "",
        status: str = "",
        current_app: str = "",
        current_screen: str = "",
        health: dict | None = None,
        error: str = "",
    ) -> None:
        if not self.user_id or not device_id:
            return
        from server.models.matrix import DeviceState

        db = self._session()
        try:
            state = (
                db.query(DeviceState)
                .filter(DeviceState.user_id == self.user_id, DeviceState.device_id == device_id)
                .first()
            )
            if not state:
                state = DeviceState(user_id=self.user_id, device_id=device_id)
                db.add(state)
            if job_id:
                state.job_id = job_id
            if status:
                state.status = status
            if current_app:
                state.current_app = current_app
            if current_screen:
                state.current_screen = current_screen
            if health is not None:
                state.health = health
            if error:
                state.consecutive_failures = int(state.consecutive_failures or 0) + 1
                state.health = {**(state.health or {}), "last_error": error[:500]}
            elif status in {"idle", "running"}:
                state.consecutive_failures = 0
            state.last_heartbeat = datetime.now(timezone.utc)
            state.updated_at = datetime.now(timezone.utc)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    def log_execution(
        self,
        result: ExecutionResult,
        *,
        device_id: str = "",
        job_id: str = "",
        target: str = "",
        payload: dict | None = None,
    ):
        if not self.user_id:
            return
        from server.models.matrix import ExecutionLog

        db = self._session()
        try:
            db.add(
                ExecutionLog(
                    user_id=self.user_id,
                    job_id=job_id or None,
                    device_id=device_id or None,
                    action=result.action,
                    target=target,
                    status=result.status or ("done" if result.ok else "failed"),
                    detail=result.message[:1000],
                    latency_ms=result.latency_ms,
                    payload=payload or result.payload,
                )
            )
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
