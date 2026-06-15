"""Task dispatch router — routes incoming tasks to appropriate executors."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger("thunder.task.router")


def route_devices_by_capacity(
    devices: list[dict],
    tasks_per_device: int = 5,
) -> list[dict]:
    """Sort devices by remaining capacity (daily_limit - daily_sent) descending.

    Used by the scheduler to distribute tasks to the least-loaded devices first.
    """
    scored = []
    for d in devices:
        limit = int(d.get("daily_limit", 10) or 10)
        sent = int(d.get("daily_sent", 0) or 0)
        remaining = max(0, limit - sent)
        skip = remaining <= 0
        scored.append((remaining, skip, d))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [d for _, _, d in scored]


@dataclass
class DispatchRequest:
    platform: str = "douyin"
    goal: str = "send_dm"
    device_id: str = ""
    adb_serial: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class DispatchResult:
    ok: bool
    status: str = ""
    message: str = ""
    route: str = ""


class TaskRouter:
    """Routes task dispatch requests to the appropriate executor."""

    def __init__(self, executors: dict[str, Callable] | None = None):
        self._executors: dict[str, Callable] = executors or {}

    def register(self, platform: str, goal: str, handler: Callable):
        self._executors[f"{platform}:{goal}"] = handler

    def dispatch(self, request: DispatchRequest) -> DispatchResult:
        key = f"{request.platform}:{request.goal}"
        handler = self._executors.get(key)
        if not handler:
            return DispatchResult(False, "unknown_route", f"No handler for {key}")
        try:
            result = handler(request)
            return DispatchResult(
                True, result.get("status", "done"), result.get("message", ""), key,
            )
        except Exception as e:
            return DispatchResult(False, "error", str(e)[:500], key)
