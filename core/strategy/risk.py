"""RiskManager — centralized risk detection and fuse management.

Extracted from DeviceSender.run() to make strategy testable and reusable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("thunder.strategy.risk")


@dataclass
class RiskDecision:
    """Output of risk assessment for a single action."""
    action: str                # "proceed" | "cooldown" | "isolate" | "nurture"
    reason: str = ""
    cooldown_hours: int = 0
    should_isolate: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.action == "proceed"


class RiskManager:
    """Centralized risk detection for device matrix operations.

    Handles:
      - Rate limit / frequency control detection
      - Device blocker detection (captcha, real-name, login)
      - Shadow ban detection
      - Consecutive failure fuse
      - Adaptive cooldown escalation

    All markers are configurable via constructor injection for A/B testing.
    """

    # ── Configurable marker sets ──

    RATE_LIMIT_MARKERS = (
        "频繁", "太快", "休息", "稍后再试", "操作过于", "暂停",
        "frequency", "too fast", "rate limit", "try again later",
    )
    SHADOW_BAN_MARKERS = (
        "隐私设置", "无法发送消息", "privacy",
    )
    DEVICE_BLOCKER_MARKERS = (
        "real_name_verification", "captcha", "login_required",
        "risk_control", "Blocked before execution", "Blocked after execution",
        "Take_over", "实名认证", "验证码", "登录", "风控",
    )

    def __init__(
        self,
        *,
        rate_limit_markers: tuple[str, ...] | None = None,
        shadow_ban_markers: tuple[str, ...] | None = None,
        device_blocker_markers: tuple[str, ...] | None = None,
        max_consecutive_failures: int = 5,
        base_cooldown_hours: int = 4,
        max_cooldown_hours: int = 24,
        consecutive_privacy_threshold: int = 3,
    ):
        self._rate_limit_markers = rate_limit_markers or self.RATE_LIMIT_MARKERS
        self._shadow_ban_markers = shadow_ban_markers or self.SHADOW_BAN_MARKERS
        self._device_blocker_markers = device_blocker_markers or self.DEVICE_BLOCKER_MARKERS
        self.max_consecutive_failures = max_consecutive_failures
        self.base_cooldown_hours = base_cooldown_hours
        self.max_cooldown_hours = max_cooldown_hours
        self.consecutive_privacy_threshold = consecutive_privacy_threshold

    def assess_action_result(
        self,
        error: str,
        *,
        consecutive_failures: int = 0,
        consecutive_privacy_blocks: int = 0,
        current_cooldown_count: int = 0,
    ) -> RiskDecision:
        """Assess a single action result and return the risk decision.

        Called after each DM send attempt (success or failure).
        """
        error_lower = (error or "").lower()

        # 1. Device blocker → isolate immediately
        if self._is_device_blocker(error_lower):
            return RiskDecision(
                action="isolate",
                reason=f"Device blocker: {error[:100]}",
                should_isolate=True,
                evidence={"blocker_type": self._classify_blocker(error_lower)},
            )

        # 2. Rate limit → cooldown with escalation
        if self._is_rate_limited(error_lower):
            hours = min(
                self.base_cooldown_hours * (1 + current_cooldown_count),
                self.max_cooldown_hours,
            )
            return RiskDecision(
                action="cooldown",
                reason=f"Rate limited: {error[:100]}",
                cooldown_hours=hours,
                evidence={"escalation": current_cooldown_count + 1},
            )

        # 3. Shadow ban → cooldown if threshold reached
        if self._is_shadow_banned(error_lower, consecutive_privacy_blocks):
            hours = self.base_cooldown_hours
            return RiskDecision(
                action="cooldown",
                reason=f"Shadow ban suspected after {consecutive_privacy_blocks} privacy blocks",
                cooldown_hours=hours,
                evidence={"privacy_blocks": consecutive_privacy_blocks},
            )

        # 4. Consecutive failure fuse → isolate
        if consecutive_failures >= self.max_consecutive_failures:
            return RiskDecision(
                action="isolate",
                reason=f"Fuse blown: {consecutive_failures} consecutive failures",
                should_isolate=True,
            )

        return RiskDecision(action="proceed")

    def _is_rate_limited(self, error_lower: str) -> bool:
        return any(m in error_lower for m in self._rate_limit_markers)

    def _is_shadow_banned(self, error_lower: str, privacy_blocks: int) -> bool:
        if privacy_blocks < self.consecutive_privacy_threshold:
            return False
        return any(m in error_lower for m in self._shadow_ban_markers)

    def _is_device_blocker(self, error_lower: str) -> bool:
        return any(m.lower() in error_lower for m in self._device_blocker_markers)

    def _classify_blocker(self, error_lower: str) -> str:
        if "实名" in error_lower or "real_name" in error_lower:
            return "real_name_verification"
        if "验证码" in error_lower or "captcha" in error_lower:
            return "captcha"
        if "登录" in error_lower or "login" in error_lower:
            return "login_required"
        if "风控" in error_lower or "risk" in error_lower:
            return "risk_control"
        return "unknown_blocker"

    # ── Time-window helpers ──

    @staticmethod
    def is_lunch_hour() -> bool:
        """True during 12:00-14:00 local time."""
        now = datetime.now()
        return 12 <= now.hour < 14

    @staticmethod
    def lunch_seconds_remaining() -> int:
        """Seconds until 14:00, or 0 if outside lunch window."""
        if not RiskManager.is_lunch_hour():
            return 0
        now = datetime.now()
        target = now.replace(hour=14, minute=0, second=0, microsecond=0)
        return max(0, int((target - now).total_seconds()))

    @staticmethod
    def cooldown_remaining(cooldown_until_iso: str) -> int:
        """Seconds remaining in cooldown, or 0 if expired."""
        if not cooldown_until_iso:
            return 0
        try:
            until = datetime.fromisoformat(cooldown_until_iso)
            return max(0, int((until - datetime.now(timezone.utc)).total_seconds()))
        except (ValueError, TypeError):
            return 0
