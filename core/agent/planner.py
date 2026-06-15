"""Planner that turns business goals into structured action plans."""

from __future__ import annotations

from core.agent.state import ActionStep, Plan


def build_douyin_dm_plan(search_target: str, user_name: str, message: str) -> Plan:
    target = search_target or user_name
    goal = f"Send one Douyin direct message to {target}"
    steps = [
        ActionStep("open_app", "douyin", confirm="home feed is visible"),
        ActionStep("search_user", target, {"query": target}, "user search results are visible"),
        ActionStep(
            "select_exact_user",
            target,
            {"nickname": user_name, "prefer_exact_id": bool(search_target)},
            "profile identity matches target",
        ),
        ActionStep("open_dm", target, confirm="chat input is visible"),
        ActionStep("send_message", target, {"message": message}, "sent message bubble is visible"),
        ActionStep("verify_sent", target, {"message": message}, "message sent exactly once"),
    ]
    return Plan(goal=goal, steps=steps, platform="douyin")


def build_douyin_dm_goal(search_target: str, user_name: str, message: str) -> str:
    id_hint = (
        f"Target Douyin ID: '{search_target}', nickname: '{user_name}'. "
        "Use the Douyin ID as the exact match source of truth."
        if search_target
        else f"Target nickname: '{user_name}'."
    )
    plan = build_douyin_dm_plan(search_target, user_name, message)
    step_text = "\n".join(
        f"{idx}. {step.action}: {step.target}; confirm: {step.confirm}"
        for idx, step in enumerate(plan.steps, 1)
    )
    return (
        "## Task: send exactly one Douyin direct message\n\n"
        f"Message: '{message}'\n"
        f"{id_hint}\n\n"
        "## Structured plan\n"
        f"{step_text}\n\n"
        "## Rules\n"
        "- Confirm each screen state before moving to the next step.\n"
        "- If the exact user cannot be verified, stop and report failure.\n"
        "- If privacy/risk/rate-limit/captcha appears, stop and report failure.\n"
        "- After the message bubble appears, stop immediately. Do not send twice.\n"
        "- Return a concise completion report."
    )


class Planner:
    def plan_dm(self, platform: str, search_target: str, user_name: str, message: str) -> Plan:
        if platform != "douyin":
            return Plan(
                goal=f"Send one {platform} direct message",
                platform=platform,
                steps=[
                    ActionStep("open_app", platform),
                    ActionStep("find_user", search_target or user_name),
                    ActionStep("send_message", search_target or user_name, {"message": message}),
                    ActionStep("verify_sent", search_target or user_name),
                ],
            )
        return build_douyin_dm_plan(search_target, user_name, message)
