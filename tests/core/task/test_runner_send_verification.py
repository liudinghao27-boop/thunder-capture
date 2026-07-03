"""TaskGraphRunner must not trust an action result without UI evidence."""

from core.agent.state import ExecutionResult, Observation
from core.task.runner import TaskGraphRunner


class MemoryStub:
    def __init__(self):
        self.logs = []
        self.plan_updates = []

    def save_plan(self, *_args, **_kwargs):
        return "graph-1"

    def save_observation(self, *_args, **_kwargs):
        return None

    def log_execution(self, result, **kwargs):
        self.logs.append((result, kwargs))

    def update_device_state(self, **_kwargs):
        return None

    def remember(self, *_args, **_kwargs):
        return "memory-1"

    def update_plan_status(self, graph_id, status, *, patch=None):
        self.plan_updates.append((graph_id, status, patch or {}))


class PerceptionStub:
    def __init__(self, observations):
        self.observations = iter(observations)

    def observe(self, **_kwargs):
        return next(self.observations)


def _observation(screen, *, confidence=0.8, text="", elements=None, blocker=""):
    return Observation(
        device_id="device-1",
        adb_serial="serial-1",
        screen=screen,
        confidence=confidence,
        blocker=blocker,
        elements=elements or [],
        ocr_text=text,
    )


def _run(before, after, message="测试消息"):
    memory = MemoryStub()
    runner = TaskGraphRunner(
        memory=memory,
        perception=PerceptionStub([before, after]),
    )
    result = runner.run_douyin_dm(
        device_id="device-1",
        adb_serial="serial-1",
        search_target="target-1",
        user_name="测试用户",
        message=message,
        execute_goal=lambda _goal: ExecutionResult(
            ok=True,
            status="done",
            message="agent reported success",
            action="phone_agent_goal",
        ),
        job_id="job-1",
        task_id="task-1",
    )
    return result, memory


def test_successful_action_without_ui_evidence_is_rejected():
    result, memory = _run(
        _observation("profile"),
        _observation("unknown", confidence=0.0),
    )
    assert result.ok is False
    assert result.status == "unconfirmed_send"
    assert result.message == "unconfirmed_send"
    assert memory.plan_updates[-1][1] == "unconfirmed_send"
    assert result.action_result.payload["agent_decisions"]["before"]["next_action"] == "open_chat"
    assert result.action_result.payload["agent_decisions"]["after"]["next_action"] == "observe"


def test_visible_message_keeps_successful_action_confirmed():
    result, memory = _run(
        _observation("profile"),
        _observation(
            "chat",
            text="测试消息",
            elements=[{"text": "测试消息"}],
        ),
    )
    assert result.ok is True
    assert result.status == "done"
    verification = result.action_result.payload["send_verification"]
    assert verification["reason"] == "message_visible"
    assert memory.plan_updates[-1][1] == "done"


def test_post_send_dm_limit_does_not_override_confirmed_success():
    result, memory = _run(
        _observation("profile"),
        _observation(
            "blocked",
            text="刚刚\n测试消息\n对方回复后才能发消息",
            elements=[{"text": "测试消息"}],
            blocker="dm_unavailable",
        ),
        message="测试消息",
    )

    assert result.ok is True
    assert result.status == "done"
    verification = result.action_result.payload["send_verification"]
    assert verification["reason"] == "message_visible"
    assert memory.plan_updates[-1][1] == "done"


def test_blocked_before_execution_returns_agent_decision_and_skips_action():
    memory = MemoryStub()
    runner = TaskGraphRunner(
        memory=memory,
        perception=PerceptionStub([
            _observation("blocked", blocker="risk_control", confidence=0.98),
        ]),
    )
    calls = []

    result = runner.run_douyin_dm(
        device_id="device-1",
        adb_serial="serial-1",
        search_target="target-1",
        user_name="test user",
        message="test message",
        execute_goal=lambda goal: calls.append(goal) or ExecutionResult(ok=True, status="done"),
        job_id="job-1",
        task_id="task-1",
    )

    assert result.ok is False
    assert result.status == "blocked"
    assert calls == []
    decision = result.action_result.payload["decision"]
    assert decision["page_state"] == "blocked"
    assert decision["next_action"] == "stop"
    assert decision["reason"] == "Blocked by risk_control."
    observe_logs = [entry for entry in memory.logs if entry[0].action == "observe_screen"]
    assert observe_logs[-1][0].payload["decision"]["next_action"] == "stop"


def test_unknown_preflight_reobserves_until_recoverable_before_executing():
    memory = MemoryStub()
    runner = TaskGraphRunner(
        memory=memory,
        perception=PerceptionStub([
            _observation("unknown", confidence=0.0),
            _observation("profile_dm_ready", confidence=0.91),
            _observation("chat", text="test message", elements=[{"text": "test message"}]),
        ]),
    )
    calls = []

    result = runner.run_douyin_dm(
        device_id="device-1",
        adb_serial="serial-1",
        search_target="target-1",
        user_name="test user",
        message="test message",
        execute_goal=lambda goal: calls.append(goal) or ExecutionResult(ok=True, status="done"),
        job_id="job-1",
        task_id="task-1",
    )

    assert result.ok is True
    assert len(calls) == 1
    assert [obs.screen for obs in result.observations] == ["unknown", "profile_dm_ready", "chat"]
    assert result.action_result.payload["agent_decisions"]["before"]["next_action"] == "open_chat"


def test_repeated_unknown_preflight_stops_as_ui_unknown_and_skips_execution():
    memory = MemoryStub()
    runner = TaskGraphRunner(
        memory=memory,
        perception=PerceptionStub([
            _observation("unknown", confidence=0.0),
            _observation("unknown", confidence=0.0),
            _observation("unknown", confidence=0.0),
        ]),
    )
    calls = []

    result = runner.run_douyin_dm(
        device_id="device-1",
        adb_serial="serial-1",
        search_target="target-1",
        user_name="test user",
        message="test message",
        execute_goal=lambda goal: calls.append(goal) or ExecutionResult(ok=True, status="done"),
        job_id="job-1",
        task_id="task-1",
    )

    assert result.ok is False
    assert result.status == "ui_unknown"
    assert calls == []
    assert [obs.screen for obs in result.observations] == ["unknown", "unknown", "unknown"]
    assert result.action_result.payload["recovery"]["status"] == "ui_unknown"
    assert result.action_result.payload["decision"]["next_action"] == "observe"
