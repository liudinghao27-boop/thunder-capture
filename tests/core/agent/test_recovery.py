from core.agent.recovery import RecoveryPolicy
from core.agent.state import AgentDecision


def _decision(next_action, *, page_state="unknown", blocker=""):
    return AgentDecision(
        page_state=page_state,
        confidence=0.5,
        next_action=next_action,
        reason="test",
        screenshot="screen.png",
        blocker=blocker,
    )


def test_recovery_policy_reobserves_unknown_until_retry_limit():
    policy = RecoveryPolicy(max_observe_retries=2)

    first = policy.evaluate(_decision("observe"), observe_attempt=0)
    second = policy.evaluate(_decision("observe"), observe_attempt=1)
    final = policy.evaluate(_decision("observe"), observe_attempt=2)

    assert first.action == "observe_again"
    assert first.terminal is False
    assert second.action == "observe_again"
    assert final.action == "stop"
    assert final.terminal is True
    assert final.status == "ui_unknown"


def test_recovery_policy_stops_on_blocker_or_stop_action():
    policy = RecoveryPolicy(max_observe_retries=2)

    result = policy.evaluate(
        _decision("stop", page_state="blocked", blocker="risk_control"),
        observe_attempt=0,
    )

    assert result.action == "stop"
    assert result.terminal is True
    assert result.status == "blocked"
    assert result.reason == "Blocked by risk_control."


def test_recovery_policy_allows_recoverable_navigation_actions_to_execute_goal():
    policy = RecoveryPolicy(max_observe_retries=2)

    for action in (
        "open_app",
        "search_target",
        "open_target_profile",
        "open_chat",
        "input_message",
    ):
        result = policy.evaluate(_decision(action), observe_attempt=0)
        assert result.action == action
        assert result.terminal is False
        assert result.execute_goal is True
