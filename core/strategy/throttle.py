"""Throttle — per-device and global rate limiting extracted from WaveStrategy.

Handles:
- Per-device daily caps
- Global daily caps
- Adaptive limit adjustment
- Cooldown interval computation
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger("thunder.strategy.throttle")


@dataclass
class ThrottleState:
    device_id: str
    daily_sent: int = 0
    daily_limit: int = 10
    global_sent: int = 0
    global_limit: int = 0
    adaptive_limit: int = 5
    wave_sent: int = 0
    cooldown_until: str = ""
    rate_limited: bool = False


class ThrottleManager:
    """Centralized rate control independent of sender internals.

    Usage:
        tm = ThrottleManager(per_device_limit=10, global_limit=200)
        if tm.can_send(device_id="xiaomi-a", daily_sent=8):
            # proceed
    """

    def __init__(
        self,
        *,
        per_device_limit: int = 10,
        global_limit: int = 0,
        adaptive_initial: int = 5,
        adaptive_min: int = 2,
        adaptive_max: int = 15,
    ):
        self.per_device_limit = per_device_limit
        self.global_limit = global_limit
        self.adaptive_initial = adaptive_initial
        self.adaptive_min = adaptive_min
        self.adaptive_max = adaptive_max

    def can_send(self, *, daily_sent: int, global_sent: int = 0) -> bool:
        if daily_sent >= self.per_device_limit:
            return False
        if self.global_limit > 0 and global_sent >= self.global_limit:
            return False
        return True

    def adaptive_adjust(self, *, current_limit: int, was_successful: bool) -> int:
        if was_successful:
            return min(current_limit + 1, self.adaptive_max)
        return max(current_limit - 1, self.adaptive_min)

    def cooldown_seconds(self, escalation: int = 0, base_hours: int = 4) -> int:
        hours = min(base_hours * (1 + escalation), 24)
        return hours * 3600

    def send_interval(self, *, total_sent: int, base_sec: int = 120) -> int:
        import random
        if total_sent <= 3:
            return base_sec + random.randint(30, 90)
        return base_sec + random.randint(0, 30)
