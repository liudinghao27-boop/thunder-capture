from core.agent.decision import decide_next_action
from core.agent.state import Observation


def _observation(screen, *, confidence=0.8, blocker="", screenshot_path="screens/1.png", elements=None):
    return Observation(
        device_id="device-1",
        adb_serial="serial-1",
        screen=screen,
        confidence=confidence,
        blocker=blocker,
        screenshot_path=screenshot_path,
        elements=elements or [],
        evidence=["ui evidence"],
        ocr_text="ocr text",
    )


def test_chat_observation_decides_to_input_message_with_sop_payload():
    decision = decide_next_action(
        _observation(
            "chat",
            elements=[
                {"text": "input message", "class_name": "android.widget.EditText"},
                {"text": "send", "clickable": True},
            ],
        ),
        goal="send_dm",
    )

    assert decision.page_state == "chat_input_ready"
    assert decision.next_action == "input_message"
    assert decision.confidence == 0.8
    assert decision.screenshot == "screens/1.png"
    assert decision.as_dict() == {
        "page_state": "chat_input_ready",
        "confidence": 0.8,
        "next_action": "input_message",
        "reason": "Chat input is visible and ready for message entry.",
        "screenshot": "screens/1.png",
        "blocker": "",
        "evidence": ["ui evidence"],
        "ocr_text": "ocr text",
        "ui_elements": [
            {"text": "input message", "class_name": "android.widget.EditText"},
            {"text": "send", "clickable": True},
        ],
    }


def test_blocked_observation_decides_to_stop_and_preserves_evidence():
    decision = decide_next_action(
        _observation(
            "blocked",
            confidence=0.98,
            blocker="risk_control",
            screenshot_path="evidence/risk.png",
        ),
        goal="send_dm",
    )

    assert decision.page_state == "blocked"
    assert decision.next_action == "stop"
    assert decision.reason == "Blocked by risk_control."
    assert decision.blocker == "risk_control"
    assert decision.screenshot == "evidence/risk.png"


def test_message_sent_observation_decides_to_confirm_success():
    decision = decide_next_action(_observation("message_sent"), goal="send_dm")

    assert decision.page_state == "message_sent"
    assert decision.next_action == "confirm_success"
    assert decision.reason == "Message send evidence is visible."


def test_search_results_decides_to_open_target_profile():
    decision = decide_next_action(_observation("search_results"), goal="send_dm")

    assert decision.page_state == "search_results"
    assert decision.next_action == "open_target_profile"


def test_profile_dm_ready_decides_to_open_chat():
    decision = decide_next_action(_observation("profile_dm_ready"), goal="send_dm")

    assert decision.page_state == "profile_dm_ready"
    assert decision.next_action == "open_chat"


def test_chat_input_disabled_decides_to_stop():
    decision = decide_next_action(_observation("chat_input_disabled"), goal="send_dm")

    assert decision.page_state == "chat_input_disabled"
    assert decision.next_action == "stop"


def test_unknown_observation_keeps_observing_with_low_confidence_reason():
    decision = decide_next_action(_observation("unknown", confidence=0.0, screenshot_path=""), goal="send_dm")

    assert decision.page_state == "unknown"
    assert decision.next_action == "observe"
    assert decision.reason == "Current screen is unknown; capture more evidence before acting."
    assert decision.screenshot == ""
