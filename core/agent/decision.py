"""Agent decision contract derived from screen observations."""

from __future__ import annotations

from core.agent.state import AgentDecision, Observation


def decide_next_action(observation: Observation, *, goal: str = "") -> AgentDecision:
    """Convert perception output into the Phase 8 decision JSON contract."""
    page_state = _normalize_page_state(observation)
    next_action, reason = _action_for_state(page_state, observation, goal=goal)

    return AgentDecision(
        page_state=page_state,
        confidence=observation.confidence,
        next_action=next_action,
        reason=reason,
        screenshot=observation.screenshot_path,
        blocker=observation.blocker,
        evidence=list(observation.evidence),
        ocr_text=observation.ocr_text,
        ui_elements=list(observation.elements),
    )


def _normalize_page_state(observation: Observation) -> str:
    if observation.blocker:
        return "blocked"
    if observation.screen == "chat":
        return "chat_input_ready"
    return observation.screen or "unknown"


def _action_for_state(
    page_state: str,
    observation: Observation,
    *,
    goal: str = "",
) -> tuple[str, str]:
    if observation.blocker:
        return "stop", f"Blocked by {observation.blocker}."

    if page_state == "chat_input_ready":
        return "input_message", "Chat input is visible and ready for message entry."

    if page_state == "message_sent":
        return "confirm_success", "Message send evidence is visible."

    if page_state == "search_results":
        return (
            "open_target_profile",
            "Search results are visible; open the matched target profile.",
        )

    if page_state == "profile_dm_ready":
        return "open_chat", "Profile message entry is available; open the private chat."

    if page_state == "chat_input_disabled":
        return (
            "stop",
            "Chat input is disabled; stop this send attempt and preserve evidence.",
        )

    if page_state == "dm_unavailable":
        return "stop", "Private message entry is unavailable for this target."

    if page_state == "profile":
        return "open_chat", "Profile page is visible; proceed to private message entry."

    if page_state == "search":
        return "search_target", "Search page is visible; proceed to target lookup."

    if page_state == "launcher":
        return (
            "open_app",
            "Device is on launcher; open the target platform before continuing.",
        )

    if page_state == "unknown":
        return (
            "observe",
            "Current screen is unknown; capture more evidence before acting.",
        )

    return (
        "observe",
        f"Observed page state {page_state}; capture more evidence before acting.",
    )
