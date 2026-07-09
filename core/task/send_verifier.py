"""Evidence-based verification for private-message delivery."""

from dataclasses import dataclass

_SENT_MARKERS = ("刚刚", "已发送", "发送成功", "消息已送达", "sent")


@dataclass(frozen=True)
class SendEvidence:
    before_screen: str
    after_screen: str
    after_confidence: float
    ocr_text: str
    ui_texts: list[str]
    blocker: str = ""


@dataclass(frozen=True)
class SendVerification:
    ok: bool
    reason: str
    confidence: float


def _normalize(value: str) -> str:
    return "".join(str(value or "").split()).casefold()


def verify_send(message: str, evidence: SendEvidence) -> SendVerification:
    visible_text = " ".join([evidence.ocr_text, *evidence.ui_texts])
    normalized_message = _normalize(message)
    normalized_visible_text = _normalize(visible_text)

    if evidence.after_screen == "message_sent" and evidence.after_confidence >= 0.5:
        return SendVerification(True, "message_sent_signal", evidence.after_confidence)

    has_sent_marker = any(marker in visible_text for marker in _SENT_MARKERS)
    if (
        normalized_message
        and normalized_message in normalized_visible_text
        and has_sent_marker
    ):
        return SendVerification(
            True, "message_visible", max(0.8, evidence.after_confidence)
        )

    if (
        evidence.after_screen == "chat"
        and normalized_message
        and normalized_message in normalized_visible_text
    ):
        return SendVerification(
            True, "message_visible", max(0.8, evidence.after_confidence)
        )

    if evidence.blocker:
        return SendVerification(False, evidence.blocker, 1.0)

    return SendVerification(
        False, "unconfirmed_send", min(0.49, evidence.after_confidence)
    )
