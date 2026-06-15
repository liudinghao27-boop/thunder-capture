"""Task graph runner for goal-driven matrix execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from core.agent.memory import AgentMemoryStore
from core.agent.perception import PerceptionService
from core.agent.planner import Planner, build_douyin_dm_goal
from core.agent.state import ExecutionResult, Observation, utc_now
from core.task.graph import douyin_dm_graph


@dataclass
class TaskRunResult:
    ok: bool
    status: str
    message: str = ""
    graph_id: str = ""
    action_result: ExecutionResult | None = None
    observations: list[Observation] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "status": self.status,
            "message": self.message,
            "graph_id": self.graph_id,
            "action_result": self.action_result.as_dict() if self.action_result else None,
            "observations": [obs.as_dict() for obs in self.observations],
        }


class TaskGraphRunner:
    """Runs the Phase 2 execution loop: plan, observe, act, observe, remember."""

    def __init__(
        self,
        *,
        memory: AgentMemoryStore,
        planner: Planner | None = None,
        perception: PerceptionService | None = None,
        screenshot_dir: str | Path | None = None,
    ):
        self.memory = memory
        self.planner = planner or Planner()
        self.perception = perception or PerceptionService()
        self.screenshot_dir = screenshot_dir

    def _observe_safe(
        self,
        *,
        device_id: str,
        adb_serial: str,
        job_id: str,
        stage: str,
    ) -> Observation | None:
        try:
            observation = self.perception.observe(
                device_id=device_id,
                adb_serial=adb_serial,
                screenshot_dir=self.screenshot_dir,
            )
            self.memory.save_observation(observation, job_id=job_id)
            self.memory.log_execution(
                ExecutionResult(
                    ok=not bool(observation.blocker),
                    status="blocked" if observation.blocker else "observed",
                    message=(
                        f"{stage}: screen={observation.screen}, "
                        f"confidence={observation.confidence:.2f}, "
                        f"blocker={observation.blocker or '-'}"
                    ),
                    action="observe_screen",
                    payload={
                        "stage": stage,
                        "screen": observation.screen,
                        "confidence": observation.confidence,
                        "blocker": observation.blocker,
                        "evidence": observation.evidence,
                        "errors": observation.errors,
                        "ocr_status": observation.ocr_status,
                        "ocr_provider": observation.ocr_provider,
                        "screenshot_path": observation.screenshot_path,
                    },
                ),
                device_id=device_id,
                job_id=job_id,
                target=stage,
            )
            self.memory.update_device_state(
                device_id=device_id,
                job_id=job_id,
                status="running",
                current_app=observation.package_name or "douyin",
                current_screen=observation.screen,
                health={
                    "screen_confidence": observation.confidence,
                    "screen_blocker": observation.blocker,
                    "screen_evidence": observation.evidence[:8],
                    "observation_errors": observation.errors[:8],
                    "ocr_status": observation.ocr_status,
                    "ocr_provider": observation.ocr_provider,
                    "activity": observation.activity,
                },
            )
            self.memory.remember(
                "observation",
                {"stage": stage, "observation": observation.as_dict()},
                device_id=device_id,
                subject_id=job_id,
                subject_type="job",
            )
            return observation
        except Exception as exc:
            self.memory.remember(
                "observation_error",
                {"stage": stage, "error": str(exc)[:500]},
                device_id=device_id,
                subject_id=job_id,
                subject_type="job",
            )
            return None

    def run_douyin_dm(
        self,
        *,
        device_id: str,
        adb_serial: str,
        search_target: str,
        user_name: str,
        message: str,
        execute_goal: Callable[[str], ExecutionResult],
        job_id: str = "",
        task_id: str = "",
    ) -> TaskRunResult:
        graph_def = douyin_dm_graph()
        plan = self.planner.plan_dm("douyin", search_target, user_name, message)
        graph_id = self.memory.save_plan(
            plan,
            job_id=job_id,
            name=f"douyin_dm:{search_target or user_name}"[:128],
            status="running",
            extra={
                "task_graph": graph_def.as_dict(),
                "task_id": task_id,
                "device_id": device_id,
                "started_at": utc_now(),
            },
        )
        self.memory.update_device_state(
            device_id=device_id,
            job_id=job_id,
            status="running",
            current_app="douyin",
        )
        self.memory.remember(
            "task_started",
            {
                "graph_id": graph_id,
                "task_id": task_id,
                "plan": plan.as_dict(),
                "message_preview": message[:80],
            },
            device_id=device_id,
            subject_id=job_id or task_id,
            subject_type="job" if job_id else "task",
        )

        observations: list[Observation] = []
        before = self._observe_safe(
            device_id=device_id,
            adb_serial=adb_serial,
            job_id=job_id,
            stage="before_execute",
        )
        if before:
            observations.append(before)
            if before.blocker:
                blocked_result = ExecutionResult(
                    ok=False,
                    status="blocked",
                    message=f"Blocked before execution: {before.blocker}",
                    action="phone_agent_goal",
                    payload={
                        "stage": "before_execute",
                        "screen": before.screen,
                        "confidence": before.confidence,
                        "blocker": before.blocker,
                        "evidence": before.evidence,
                        "errors": before.errors,
                        "screenshot_path": before.screenshot_path,
                    },
                )
                self.memory.log_execution(
                    blocked_result,
                    device_id=device_id,
                    job_id=job_id,
                    target=search_target or user_name,
                    payload={
                        "graph_id": graph_id,
                        "task_id": task_id,
                        "plan": plan.as_dict(),
                        "blocked_by_observation": before.as_dict(),
                    },
                )
                self.memory.update_plan_status(
                    graph_id,
                    "blocked",
                    patch={
                        "completed_at": utc_now(),
                        "result": blocked_result.as_dict(),
                        "observation_count": len(observations),
                    },
                )
                self.memory.update_device_state(
                    device_id=device_id,
                    job_id=job_id,
                    status="error",
                    current_app=before.package_name or "douyin",
                    current_screen=before.screen,
                    error=blocked_result.message,
                )
                return TaskRunResult(
                    ok=False,
                    status="blocked",
                    message=blocked_result.message,
                    graph_id=graph_id,
                    action_result=blocked_result,
                    observations=observations,
                )

        goal = build_douyin_dm_goal(search_target, user_name, message)
        action_result = execute_goal(goal)
        self.memory.log_execution(
            action_result,
            device_id=device_id,
            job_id=job_id,
            target=search_target or user_name,
            payload={
                "graph_id": graph_id,
                "task_id": task_id,
                "plan": plan.as_dict(),
                "message": message,
            },
        )

        after = self._observe_safe(
            device_id=device_id,
            adb_serial=adb_serial,
            job_id=job_id,
            stage="after_execute",
        )
        if after:
            observations.append(after)
            if after.blocker and action_result.ok:
                action_result = ExecutionResult(
                    ok=False,
                    status="blocked",
                    message=f"Blocked after execution: {after.blocker}",
                    action=action_result.action,
                    payload={
                        **(action_result.payload or {}),
                        "original_result": action_result.as_dict(),
                        "verification": after.as_dict(),
                    },
                    latency_ms=action_result.latency_ms,
                )

        status = "done" if action_result.ok else action_result.status or "failed"
        verification = observations[-1].as_dict() if observations else {}
        self.memory.update_plan_status(
            graph_id,
            status,
            patch={
                "completed_at": utc_now(),
                "result": action_result.as_dict(),
                "observation_count": len(observations),
                "verification": verification,
            },
        )
        self.memory.update_device_state(
            device_id=device_id,
            job_id=job_id,
            status="idle" if action_result.ok else "error",
            current_app="douyin",
            current_screen=observations[-1].screen if observations else "",
            error="" if action_result.ok else action_result.message,
        )
        self.memory.remember(
            "task_finished",
            {
                "graph_id": graph_id,
                "task_id": task_id,
                "ok": action_result.ok,
                "status": status,
                "message": action_result.message[:500],
            },
            device_id=device_id,
            subject_id=job_id or task_id,
            subject_type="job" if job_id else "task",
        )
        return TaskRunResult(
            ok=action_result.ok,
            status=status,
            message=action_result.message,
            graph_id=graph_id,
            action_result=action_result,
            observations=observations,
        )
