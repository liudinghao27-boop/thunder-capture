"""Helpers for exposing Agent decisions in API responses."""

from __future__ import annotations

from typing import Any


def extract_agent_decisions(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    decisions = payload.get("agent_decisions")
    return decisions if isinstance(decisions, dict) else {}


def extract_agent_decision(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}

    direct = payload.get("decision")
    if isinstance(direct, dict):
        return direct

    decisions = extract_agent_decisions(payload)
    for key in ("after", "before"):
        decision = decisions.get(key)
        if isinstance(decision, dict):
            return decision
    return {}


def extract_decision_from_health(health: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(health, dict):
        return {}
    decision = health.get("agent_decision")
    return decision if isinstance(decision, dict) else {}


def extract_decision_from_snapshot(ui_tree: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(ui_tree, dict):
        return {}
    decision = ui_tree.get("decision")
    if isinstance(decision, dict):
        return decision
    return extract_agent_decision(ui_tree)


def decision_reason(decision: dict[str, Any] | None) -> str:
    if not isinstance(decision, dict):
        return ""
    return str(decision.get("reason") or "")


def decision_screenshot(decision: dict[str, Any] | None) -> str:
    if not isinstance(decision, dict):
        return ""
    return str(decision.get("screenshot") or decision.get("screenshot_path") or "")
