"""Policy gate — centralized pre-send decision combining risk + wave + quota.

A single gateway that answers: "Should this device send the next task now?"
Combines RiskManager, WaveStrategy, and global quota checks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from core.config import IndustryConfig

log = logging.getLogger("thunder.strategy.policy")


def _parse_time(value: str):
    """Parse HH:MM string into (hour, minute) tuple."""
    try:
        h, m = value.split(":")
        return int(h), int(m)
    except Exception:
        return 0, 0


def is_send_window_open(industry: IndustryConfig) -> bool:
    """Return True if current UTC time is inside the industry's send window."""
    now = datetime.now(timezone.utc)

    if getattr(industry, "pause_weekends", False) and now.weekday() >= 5:
        return False

    start_h, start_m = _parse_time(getattr(industry, "send_start_time", "00:00"))
    end_h, end_m = _parse_time(getattr(industry, "send_end_time", "23:59"))

    current_minutes = now.hour * 60 + now.minute
    start_minutes = start_h * 60 + start_m
    end_minutes = end_h * 60 + end_m

    if start_minutes <= end_minutes:
        return start_minutes <= current_minutes <= end_minutes
    return current_minutes >= start_minutes or current_minutes <= end_minutes


@dataclass
class PolicyDecision:
    """Result of policy gate check."""
    allowed: bool
    reason: str = ""
    action: str = ""            # "send" | "wait" | "cooldown" | "isolate" | "stop"
    wait_seconds: int = 0
    meta: dict[str, Any] = field(default_factory=dict)


class SendPolicyGate:
    """Single entry point for all pre-send checks.

    Usage:
        gate = SendPolicyGate(risk_mgr, wave_strategy)
        decision = gate.check(
            device_id="xiaomi-a",
            daily_sent=5, daily_limit=10,
            global_sent=45, global_limit=200,
            consecutive_failures=2,
            is_rate_limited=False,
            is_cooldown=False,
            wave_sent=3, wave_limit=5,
        )
        if not decision.allowed:
            time.sleep(decision.wait_seconds)
    """

    def __init__(self, *, risk_manager, wave_strategy):
        self._risk = risk_manager
        self._wave = wave_strategy

    def check(
        self,
        *,
        device_id: str = "",
        daily_sent: int = 0,
        daily_limit: int = 10,
        global_sent: int = 0,
        global_limit: int = 0,
        consecutive_failures: int = 0,
        is_rate_limited: bool = False,
        is_cooldown: bool = False,
        is_lunch_hour: bool = False,
        wave_sent: int = 0,
        wave_limit: int = 5,
        nurture_done_today: int = 0,
        wave_count: int = 0,
    ) -> PolicyDecision:
        # 1. Device-level hard blocks
        if is_cooldown:
            return PolicyDecision(False, "Device in cooldown", "cooldown")
        if is_rate_limited:
            return PolicyDecision(False, "Device rate limited", "cooldown")

        # 2. Daily limit
        if daily_sent >= daily_limit:
            return PolicyDecision(False, "Daily limit reached", "stop")

        # 3. Global limit
        if global_limit > 0 and global_sent >= global_limit:
            return PolicyDecision(False, "Global daily limit reached", "stop")

        # 4. Consecutive failure fuse
        if consecutive_failures >= self._risk.max_consecutive_failures:
            return PolicyDecision(
                False,
                f"Fuse blown: {consecutive_failures} failures",
                "isolate",
            )

        # 5. Lunch break
        if is_lunch_hour:
            wait = self._risk.lunch_seconds_remaining()
            return PolicyDecision(False, "Lunch break (12:00-14:00)", "wait", wait)

        # 6. Wave strategy decision
        wd = self._wave.wave_decision(
            wave_sent=wave_sent,
            wave_limit=wave_limit,
            sent_since_break=0,
            nurture_done_today=nurture_done_today,
            wave_count=wave_count,
        )
        if wd.action != "send":
            return PolicyDecision(
                False, wd.reason, wd.action, wd.wait_seconds, wd.meta or {},
            )

        return PolicyDecision(True, "ok", "send")
