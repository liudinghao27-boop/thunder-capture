"""Agent executors for device actions and PhoneAgent goals."""

from __future__ import annotations

import sys
import time
import threading
from pathlib import Path
from typing import Callable

from core.agent.state import ActionStep, ExecutionResult
from core.constants import DEFAULT_AGENT_MAX_STEPS
from core.device.adb_client import ADBClient, ADBError

_FAILURE_MARKERS = [
    "Max steps reached",
    "失败",
    "错误",
    "无法",
    "超时",
    "未找到",
    "未发送",
    "不存在",
    "打不开",
    "找不到",
    "Model error",
    "Connection error",
    "Rate limit",
    "频繁",
    "限制",
    "拦截",
    "风控",
    "验证码",
    "实名",
    "认证",
    "Take_over",
    "上限",
    "上线",
]

_SUCCESS_MARKERS = [
    "任务完成",
    "已成功",
    "消息已发送",
    "发送成功",
    "操作成功",
    "成功发送",
]


def _ensure_bundled_phone_agent_path() -> Path:
    """Expose the vendored Open-AutoGLM phone_agent package to imports."""
    bundle_path = Path(__file__).resolve().parents[2] / "deps" / "Open-AutoGLM"
    if bundle_path.exists() and str(bundle_path) not in sys.path:
        sys.path.insert(0, str(bundle_path))
    return bundle_path


class AgentExecutor:
    """Execute low-level structured actions through the device wrapper."""

    def __init__(self, adb_serial: str):
        self.client = ADBClient(adb_serial)

    def execute(self, step: ActionStep) -> ExecutionResult:
        started = time.perf_counter()
        try:
            if step.action == "tap":
                self.client.tap(int(step.payload["x"]), int(step.payload["y"]))
            elif step.action == "swipe":
                self.client.swipe(
                    int(step.payload["x1"]),
                    int(step.payload["y1"]),
                    int(step.payload["x2"]),
                    int(step.payload["y2"]),
                    int(step.payload.get("duration_ms", 300)),
                )
            elif step.action == "keyevent":
                self.client.keyevent(step.payload["key_code"])
            elif step.action == "input_text":
                self.client.input_text(str(step.payload.get("text", "")))
            else:
                return ExecutionResult(False, "unsupported_action", action=step.action)
            return ExecutionResult(
                True,
                "done",
                action=step.action,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        except (ADBError, KeyError, ValueError) as exc:
            return ExecutionResult(
                False,
                "failed",
                message=str(exc),
                action=step.action,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )


class PhoneAgentExecutor:
    """Thin wrapper around PhoneAgent for goal-driven execution."""

    def __init__(
        self,
        *,
        adb_serial: str,
        base_url: str,
        model_name: str,
        api_key: str,
        should_stop: Callable[[], bool] | None = None,
        on_cancel: Callable[[], None] | None = None,
        max_steps: int = DEFAULT_AGENT_MAX_STEPS,
    ):
        self.adb_serial = adb_serial
        self.base_url = base_url
        self.model_name = model_name
        self.api_key = api_key
        self.should_stop = should_stop
        self.on_cancel = on_cancel
        self.max_steps = max_steps
        self._agent = None
        self._cancel_notified = False

    @property
    def raw_agent(self):
        return self._agent

    def stop(self) -> None:
        """Release the underlying agent after a device run."""
        agent = self._agent
        self._agent = None
        if not agent:
            return
        for method_name in ("stop", "close"):
            method = getattr(agent, method_name, None)
            if callable(method):
                try:
                    method()
                except Exception:
                    pass
                return

    def start(self):
        _ensure_bundled_phone_agent_path()
        from phone_agent import PhoneAgent
        from phone_agent.agent import AgentConfig
        from phone_agent.model import ModelConfig

        model_cfg = ModelConfig(
            base_url=self.base_url,
            model_name=self.model_name,
            api_key=self.api_key,
        )
        agent_cfg = AgentConfig(
            max_steps=self.max_steps,
            lang="cn",
            device_id=self.adb_serial or None,
        )
        agent = PhoneAgent(model_config=model_cfg, agent_config=agent_cfg)
        self._patch_cancellation(agent)
        self._agent = agent
        return self

    def _patch_cancellation(self, agent) -> None:
        original_step = agent.step
        original_execute_step = agent._execute_step

        def _cancelable_step(*args, **kwargs):
            if self.should_stop and self.should_stop():
                raise SystemExit("Cancelled by user")
            return original_step(*args, **kwargs)

        def _cancelable_execute(*args, **kwargs):
            if self.should_stop and self.should_stop():
                raise SystemExit("Cancelled by user")
            return original_execute_step(*args, **kwargs)

        agent.step = _cancelable_step
        agent._execute_step = _cancelable_execute

    def _notify_cancel(self) -> None:
        if self._cancel_notified:
            return
        self._cancel_notified = True
        if not self.on_cancel:
            return
        try:
            self.on_cancel()
        except Exception:
            pass

    def _start_cancel_watcher(self) -> tuple[threading.Event, threading.Thread | None]:
        stop_event = threading.Event()
        if not self.should_stop:
            return stop_event, None

        def _watch():
            while not stop_event.wait(0.5):
                try:
                    if self.should_stop and self.should_stop():
                        self._notify_cancel()
                        return
                except Exception:
                    return

        thread = threading.Thread(target=_watch, name=f"phone-agent-cancel-{self.adb_serial}", daemon=True)
        thread.start()
        return stop_event, thread

    def execute_goal(self, goal: str) -> ExecutionResult:
        started = time.perf_counter()
        cancel_stop, cancel_thread = self._start_cancel_watcher()
        try:
            if self.should_stop and self.should_stop():
                self._notify_cancel()
                raise SystemExit("Cancelled by user")
            if not self._agent:
                self.start()
            if self.should_stop and self.should_stop():
                self._notify_cancel()
                raise SystemExit("Cancelled by user")
            if not self._agent:
                raise RuntimeError("Agent failed to start")
            result = self._agent.run(goal)
            if self.should_stop and self.should_stop():
                self._notify_cancel()
                raise SystemExit("Cancelled by user")
            message = str(result).strip() if result else ""
            failed = any(marker in message for marker in _FAILURE_MARKERS)
            succeeded = any(marker in message for marker in _SUCCESS_MARKERS)
            if failed:
                status = "failed"
                ok = False
            elif succeeded:
                status = "done"
                ok = True
            else:
                status = "uncertain" if message else "empty_result"
                ok = False
            return ExecutionResult(
                ok=ok,
                status=status,
                message=message[:500],
                action="phone_agent_goal",
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        except SystemExit as exc:
            self._notify_cancel()
            return ExecutionResult(
                False,
                "cancelled",
                message=f"Cancelled by user: {exc}",
                action="phone_agent_goal",
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:
            return ExecutionResult(
                False,
                "failed",
                message=str(exc)[:500],
                action="phone_agent_goal",
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        finally:
            cancel_stop.set()
            if cancel_thread and cancel_thread.is_alive():
                cancel_thread.join(timeout=1)
