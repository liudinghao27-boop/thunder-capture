"""Deterministic message-delivery verification from perception evidence."""

from core.task.send_verifier import SendEvidence, verify_send


def test_visible_message_in_chat_confirms_send():
    evidence = SendEvidence(
        before_screen="profile",
        after_screen="chat",
        after_confidence=0.8,
        ocr_text="你好，想了解一下",
        ui_texts=["输入消息", "你好，想了解一下"],
    )
    result = verify_send("你好，想了解一下", evidence)
    assert result.ok is True
    assert result.reason == "message_visible"


def test_explicit_message_sent_screen_confirms_send():
    evidence = SendEvidence(
        before_screen="chat",
        after_screen="message_sent",
        after_confidence=0.9,
        ocr_text="消息已送达",
        ui_texts=[],
    )
    result = verify_send("测试消息", evidence)
    assert result.ok is True
    assert result.reason == "message_sent_signal"


def test_blocker_never_confirms_send():
    evidence = SendEvidence(
        before_screen="profile",
        after_screen="blocked",
        after_confidence=0.98,
        ocr_text="登录后继续",
        ui_texts=[],
        blocker="login_required",
    )
    result = verify_send("测试消息", evidence)
    assert result.ok is False
    assert result.reason == "login_required"


def test_action_without_after_evidence_is_unconfirmed():
    evidence = SendEvidence(
        before_screen="profile",
        after_screen="unknown",
        after_confidence=0.0,
        ocr_text="",
        ui_texts=[],
    )
    result = verify_send("测试消息", evidence)
    assert result.ok is False
    assert result.reason == "unconfirmed_send"
