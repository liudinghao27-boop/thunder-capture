from core.agent.executor import PhoneAgentExecutor
from core.agent.executor import _ensure_bundled_phone_agent_path


class _FakeAgent:
    def __init__(self):
        self.stop_calls = 0

    def stop(self):
        self.stop_calls += 1


def test_phone_agent_stop_releases_agent_and_is_idempotent():
    executor = PhoneAgentExecutor(
        adb_serial="device-1",
        base_url="https://example.invalid",
        model_name="model",
        api_key="key",
    )
    agent = _FakeAgent()
    executor._agent = agent

    executor.stop()
    executor.stop()

    assert agent.stop_calls == 1
    assert executor.raw_agent is None


def test_ensure_bundled_phone_agent_path_adds_open_autoglm_to_sys_path(monkeypatch):
    monkeypatch.setattr("core.agent.executor.sys.path", [])

    path = _ensure_bundled_phone_agent_path()

    assert path.name == "Open-AutoGLM"
    assert str(path) in __import__("sys").path
