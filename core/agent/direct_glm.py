"""DirectGLMAgent — Phase 4 step-by-step execution via GLM Vision API.

Replaces PhoneAgent black-box execution with per-step GLM calls.
Each step: screenshot → GLM plans one action → executor runs it → verify.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from core.agent.state import ExecutionResult, utc_now
from core.device.adb_client import ADBClient

log = logging.getLogger("thunder.agent.direct_glm")


@dataclass
class GLMAction:
    """Structured action returned by GLM Vision for one step."""
    action: str = ""       # "tap" | "swipe" | "type" | "key" | "wait" | "done" | "failed"
    x: int = 0
    y: int = 0
    x2: int = 0
    y2: int = 0
    text: str = ""
    key_code: str = ""
    duration_ms: int = 300
    reason: str = ""
    screen_after: str = ""  # expected screen after this action

    @classmethod
    def from_json(cls, raw: str) -> "GLMAction":
        """Parse GLM JSON response, handling markdown code fences."""
        clean = raw.strip()
        if clean.startswith("```"):
            clean = re.sub(r"^```(?:json)?\s*", "", clean)
            clean = re.sub(r"\s*```$", "", clean)
        try:
            data = json.loads(clean)
        except json.JSONDecodeError:
            # Try to extract JSON from mixed text
            m = re.search(r'\{[^{}]*"action"[^{}]*\}', clean, re.DOTALL)
            if m:
                data = json.loads(m.group(0))
            else:
                return cls(action="failed", reason=f"JSON parse error: {raw[:200]}")
        return cls(
            action=data.get("action", "unknown"),
            x=int(data.get("x", 0) or 0),
            y=int(data.get("y", 0) or 0),
            x2=int(data.get("x2", 0) or 0),
            y2=int(data.get("y2", 0) or 0),
            text=data.get("text", ""),
            key_code=data.get("key_code", ""),
            duration_ms=int(data.get("duration_ms", 300) or 300),
            reason=data.get("reason", ""),
            screen_after=data.get("screen_after", ""),
        )


@dataclass
class StepResult:
    """Result of executing one plan step."""
    ok: bool
    step_index: int = 0
    step_name: str = ""
    action: GLMAction | None = None
    error: str = ""
    before_screen: str = ""
    after_screen: str = ""
    latency_ms: int = 0


class DirectGLMAgent:
    """Step-by-step GLM Vision agent.

    Usage:
        agent = DirectGLMAgent(
            adb_serial="abc123",
            api_base="https://open.bigmodel.cn/api/paas/v4",
            api_key="...",
            model="autoglm-phone",
            should_stop=lambda: False,
        )
        result = agent.execute_plan(plan_steps=[...])
    """

    ACTION_PROMPT = """You are controlling an Android phone via ADB. Based on the screenshot, decide the NEXT single action to accomplish the current step.

Current step: {step_description}
Expected outcome: {expected_outcome}
Previous step results: {context}
Current screen: {screen_state}
OCR text visible: {ocr_text}

Return ONLY a JSON object with these fields:
{{
  "action": "tap" | "swipe" | "type" | "key" | "wait" | "done" | "failed",
  "x": <pixel_x>,
  "y": <pixel_y>,
  "x2": <pixel_x2>,
  "y2": <pixel_y2>,
  "text": "<text to type>",
  "key_code": "<BACK|HOME|ENTER>",
  "duration_ms": 300,
  "reason": "<brief reason for this action>",
  "screen_after": "<expected screen after action>"
}}

Rules:
- Coordinates must be actual pixel values visible in the screenshot.
- Use "tap" for clicking buttons, search boxes, user names, etc.
- Use "swipe" for scrolling (provide x/y start and x2/y2 end).
- Use "type" for entering text into a focused input field.
- Use "key" with key_code="BACK" to go back, "HOME" for home.
- Use "wait" with duration_ms to pause for loading.
- If the step is already complete, return action="done".
- If something blocks progress (captcha, login, error), return action="failed" with reason.
- Do NOT return action arrays. One single action per response.
- Only output the JSON, no other text."""

    MAX_STEPS_PER_PLAN_STEP = 5  # max retries per plan step
    MAX_TOTAL_ACTIONS = 30       # safety limit

    def __init__(
        self,
        *,
        adb_serial: str,
        api_base: str,
        api_key: str,
        model: str = "autoglm-phone",
        should_stop: Callable[[], bool] | None = None,
        perception=None,         # PerceptionService
        executor=None,           # AgentExecutor
    ):
        self.adb_serial = adb_serial
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.should_stop = should_stop or (lambda: False)
        self._perception = perception
        self._executor = executor
        self._client = ADBClient(adb_serial)

    def _call_glm(self, screenshot_bytes: bytes, prompt: str) -> str:
        """Send screenshot + prompt to GLM Vision API."""
        import httpx

        img_b64 = base64.b64encode(screenshot_bytes).decode("ascii")

        body = {
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }],
            "max_tokens": 300,
            "temperature": 0.1,
        }

        resp = httpx.post(
            f"{self.api_base}/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=httpx.Timeout(30.0, connect=10.0),
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def _execute_action(self, action: GLMAction) -> str:
        """Execute a single GLM action via ADB. Returns error string or ''."""
        try:
            if action.action == "tap":
                self._client.tap(action.x, action.y)
            elif action.action == "swipe":
                self._client.swipe(action.x, action.y, action.x2, action.y2, action.duration_ms)
            elif action.action == "type":
                self._client.input_text(action.text)
            elif action.action == "key":
                kc = action.key_code.upper()
                key_map = {"BACK": "4", "HOME": "3", "ENTER": "66"}
                code = key_map.get(kc, kc)
                self._client.keyevent(code)
            elif action.action == "wait":
                time.sleep(min(action.duration_ms / 1000.0, 5.0))
            elif action.action in ("done", "failed"):
                pass
            else:
                return f"Unknown action: {action.action}"
            return ""
        except Exception as e:
            return str(e)[:200]

    def execute_plan(
        self,
        plan_steps: list[dict],
        *,
        task_id: str = "",
    ) -> ExecutionResult:
        """Execute a structured plan step by step.

        Args:
            plan_steps: [{"name": "open_app", "description": "...", "expected": "home"},
                         {"name": "search_user", ...}, ...]

        Returns:
            ExecutionResult with per-step details.
        """
        from core.agent.perception import PerceptionService

        perception = self._perception or PerceptionService()
        started = time.perf_counter()
        step_results: list[StepResult] = []
        total_actions = 0
        last_error = ""

        for i, step in enumerate(plan_steps):
            if self.should_stop():
                return ExecutionResult(
                    False, "cancelled",
                    message="Cancelled during plan execution",
                    action="direct_glm",
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    payload={"step_results": [r.__dict__ for r in step_results]},
                )

            step_name = step.get("name", f"step_{i}")
            step_desc = step.get("description", "")
            step_expected = step.get("expected", "")

            for attempt in range(self.MAX_STEPS_PER_PLAN_STEP):
                if self.should_stop():
                    break

                step_started = time.perf_counter()

                # 1. Observe
                try:
                    obs = perception.observe(
                        device_id="", adb_serial=self.adb_serial,
                    )
                except Exception:
                    obs = None

                # 2. Screenshot
                try:
                    png = self._client.screen_png()
                except Exception:
                    png = b""

                # 3. Build context from previous steps
                context = ""
                if step_results:
                    last = step_results[-1]
                    context = f"Previous step '{last.step_name}': {'OK' if last.ok else last.error}. "

                # 4. Call GLM
                prompt = self.ACTION_PROMPT.format(
                    step_description=step_desc,
                    expected_outcome=step_expected,
                    context=context,
                    screen_state=obs.screen if obs else "unknown",
                    ocr_text=(obs.ocr_text or "")[:500] if obs else "",
                )
                if not png:
                    step_result = StepResult(
                        False, i, step_name,
                        error="Screenshot failed",
                        before_screen=obs.screen if obs else "",
                        latency_ms=int((time.perf_counter() - step_started) * 1000),
                    )
                    step_results.append(step_result)
                    last_error = "Screenshot failed"
                    break

                try:
                    raw = self._call_glm(png, prompt)
                    action = GLMAction.from_json(raw)
                except Exception as e:
                    step_result = StepResult(
                        False, i, step_name,
                        error=f"GLM call failed: {e}",
                        before_screen=obs.screen if obs else "",
                        latency_ms=int((time.perf_counter() - step_started) * 1000),
                    )
                    step_results.append(step_result)
                    last_error = str(e)
                    break

                if action.action == "done":
                    step_result = StepResult(
                        True, i, step_name, action=action,
                        before_screen=obs.screen if obs else "",
                        latency_ms=int((time.perf_counter() - step_started) * 1000),
                    )
                    step_results.append(step_result)
                    last_error = ""
                    break

                if action.action == "failed":
                    step_result = StepResult(
                        False, i, step_name, action=action,
                        error=action.reason,
                        before_screen=obs.screen if obs else "",
                        latency_ms=int((time.perf_counter() - step_started) * 1000),
                    )
                    step_results.append(step_result)
                    last_error = action.reason
                    break

                # 5. Execute
                err = self._execute_action(action)
                total_actions += 1

                # 6. Verify
                after_screen = ""
                try:
                    post_obs = perception.observe(
                        device_id="", adb_serial=self.adb_serial,
                    )
                    after_screen = post_obs.screen if post_obs else ""
                    if post_obs and post_obs.blocker:
                        step_result = StepResult(
                            False, i, step_name, action=action,
                            error=f"Blocker: {post_obs.blocker}",
                            before_screen=obs.screen if obs else "",
                            after_screen=after_screen,
                            latency_ms=int((time.perf_counter() - step_started) * 1000),
                        )
                        step_results.append(step_result)
                        last_error = post_obs.blocker
                        break
                except Exception:
                    pass

                if err:
                    step_result = StepResult(
                        False, i, step_name, action=action,
                        error=err,
                        before_screen=obs.screen if obs else "",
                        after_screen=after_screen,
                        latency_ms=int((time.perf_counter() - step_started) * 1000),
                    )
                    step_results.append(step_result)
                    last_error = err
                    break

                # Success for this sub-action, continue trying this step
                if total_actions >= self.MAX_TOTAL_ACTIONS:
                    step_result = StepResult(
                        False, i, step_name,
                        error="Max total actions reached",
                        latency_ms=int((time.perf_counter() - step_started) * 1000),
                    )
                    step_results.append(step_result)
                    last_error = "Max actions"
                    break

                time.sleep(0.5)  # brief pause between actions
            else:
                # Exhausted retries
                if last_error:
                    step_result = StepResult(
                        False, i, step_name,
                        error=f"Max retries: {last_error}",
                        latency_ms=0,
                    )
                    step_results.append(step_result)

        all_ok = all(r.ok or r.action and r.action.action == "done" for r in step_results)
        return ExecutionResult(
            ok=all_ok,
            status="done" if all_ok else "failed",
            message=f"{sum(1 for r in step_results if r.ok)}/{len(step_results)} steps OK",
            action="direct_glm",
            latency_ms=int((time.perf_counter() - started) * 1000),
            payload={
                "total_actions": total_actions,
                "step_results": [r.__dict__ for r in step_results],
            },
        )
