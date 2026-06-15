"""Task graph definitions."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TaskStep:
    key: str
    depends_on: list[str] = field(default_factory=list)
    retryable: bool = True
    timeout_sec: int = 60


@dataclass(frozen=True)
class TaskGraphDefinition:
    name: str
    steps: list[TaskStep]

    def as_dict(self) -> dict:
        return {"name": self.name, "steps": [step.__dict__ for step in self.steps]}


def douyin_dm_graph() -> TaskGraphDefinition:
    return TaskGraphDefinition(
        name="douyin_dm",
        steps=[
            TaskStep("plan", retryable=False, timeout_sec=20),
            TaskStep("observe_home", ["plan"], timeout_sec=15),
            TaskStep("find_user", ["observe_home"], timeout_sec=180),
            TaskStep("open_chat", ["find_user"], timeout_sec=90),
            TaskStep("send_message", ["open_chat"], timeout_sec=90),
            TaskStep("verify_sent", ["send_message"], retryable=False, timeout_sec=30),
            TaskStep("memory_update", ["verify_sent"], retryable=False, timeout_sec=15),
        ],
    )
