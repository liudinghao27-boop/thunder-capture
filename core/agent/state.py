"""State objects shared by planner, perception, executor, and memory."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ActionStep:
    action: str
    target: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    confirm: str = ""


@dataclass(frozen=True)
class Plan:
    goal: str
    steps: list[ActionStep]
    platform: str = "douyin"
    created_at: str = field(default_factory=utc_now)

    def as_dict(self) -> dict:
        return {
            "goal": self.goal,
            "platform": self.platform,
            "created_at": self.created_at,
            "steps": [step.__dict__ for step in self.steps],
        }


@dataclass(frozen=True)
class Observation:
    device_id: str
    adb_serial: str
    screen: str = "unknown"
    confidence: float = 0.0
    blocker: str = ""
    evidence: list[str] = field(default_factory=list)
    elements: list[dict[str, Any]] = field(default_factory=list)
    screenshot_path: str = ""
    ocr_text: str = ""
    ocr_status: str = ""
    ocr_provider: str = ""
    package_name: str = ""
    activity: str = ""
    errors: list[str] = field(default_factory=list)
    captured_at: str = field(default_factory=utc_now)

    def as_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass(frozen=True)
class ExecutionResult:
    ok: bool
    status: str
    message: str = ""
    action: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0

    def as_dict(self) -> dict:
        return self.__dict__.copy()
