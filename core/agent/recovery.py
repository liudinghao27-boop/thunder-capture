"""Recovery policy for evidence-driven Agent execution."""

from __future__ import annotations

from dataclasses import dataclass

from core.agent.state import AgentDecision


@dataclass(frozen=True)
class RecoveryDecision:
    action: str
    status: str
    terminal: bool
    execute_goal: bool
    reason: str

    def as_dict(self) -> dict:
        return {
            "action": self.action,
            "status": self.status,
            "terminal": self.terminal,
            "execute_goal": self.execute_goal,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RecoveryPolicy:
    max_observe_retries: int = 2

    def evaluate(
        self, decision: AgentDecision, *, observe_attempt: int = 0
    ) -> RecoveryDecision:
        if decision.next_action == "observe":
            if observe_attempt < self.max_observe_retries:
                return RecoveryDecision(
                    action="observe_again",
                    status="observing",
                    terminal=False,
                    execute_goal=False,
                    reason="Screen is unknown; capture another observation before acting.",
                )
            return RecoveryDecision(
                action="stop",
                status="ui_unknown",
                terminal=True,
                execute_goal=False,
                reason="Screen stayed unknown after observation retry limit.",
            )

        if decision.next_action == "stop":
            reason = (
                f"Blocked by {decision.blocker}."
                if decision.blocker
                else decision.reason
            )
            return RecoveryDecision(
                action="stop",
                status="blocked"
                if decision.blocker
                else decision.page_state or "stopped",
                terminal=True,
                execute_goal=False,
                reason=reason,
            )

        return RecoveryDecision(
            action=decision.next_action,
            status="ready",
            terminal=False,
            execute_goal=True,
            reason=decision.reason,
        )
