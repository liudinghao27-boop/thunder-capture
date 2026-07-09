"""WaveStrategy — adaptive pacing, warmup, and nurture scheduling.

Extracted from DeviceSender.run() to make wave logic testable and configurable.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("thunder.strategy.wave")


@dataclass
class WaveDecision:
    """Output of wave strategy for the next action."""

    action: str  # "send" | "wait" | "nurture" | "wave_break" | "stop"
    wait_seconds: int = 0
    reason: str = ""
    meta: dict[str, Any] | None = None


class WaveStrategy:
    """Determines *when* and *how fast* to send, independent of task execution.

    Encapsulates:
      - Warmup: first N sends get longer intervals
      - Wave pacing: send in bursts with rest breaks
      - Nurture insertion: periodic account warming between waves
      - Lunch break detection
      - Boot delay randomization (anti-stampede)
    """

    def __init__(
        self,
        *,
        base_interval_sec: int = 120,
        warmup_send_count: int = 3,
        warmup_extra_sec: int = 60,
        wave_sends_min: int = 3,
        wave_sends_max: int = 5,
        wave_rest_min_sec: int = 180,
        wave_rest_max_sec: int = 600,
        boot_delay_min_sec: int = 10,
        boot_delay_max_sec: int = 300,
        nurture_frequency: int = 3,  # nurture after every N waves
    ):
        self.base_interval_sec = base_interval_sec
        self.warmup_send_count = warmup_send_count
        self.warmup_extra_sec = warmup_extra_sec
        self.wave_sends_min = wave_sends_min
        self.wave_sends_max = wave_sends_max
        self.wave_rest_min_sec = wave_rest_min_sec
        self.wave_rest_max_sec = wave_rest_max_sec
        self.boot_delay_min_sec = boot_delay_min_sec
        self.boot_delay_max_sec = boot_delay_max_sec
        self.nurture_frequency = nurture_frequency

    def boot_delay(self) -> int:
        """Random delay before first send to avoid all devices starting at once."""
        return random.randint(self.boot_delay_min_sec, self.boot_delay_max_sec)

    def send_interval(self, *, total_sent: int) -> int:
        """Compute the wait interval after a successful send.

        Warmup phase: base + random extra (slower, safer).
        Normal phase: base + small jitter.
        """
        base = self.base_interval_sec
        if total_sent <= self.warmup_send_count:
            return base + random.randint(
                self.warmup_extra_sec // 2, self.warmup_extra_sec
            )
        return base + random.randint(0, 30)

    def wave_decision(
        self,
        *,
        wave_sent: int,
        wave_limit: int,
        sent_since_break: int,
        nurture_done_today: int,
        wave_count: int,
    ) -> WaveDecision:
        """Decide the next action in the wave cycle.

        Priority order: wave complete → nurture → rest break → send.
        """
        # Wave complete → take a break
        if wave_sent >= wave_limit:
            rest = random.randint(self.wave_rest_min_sec, self.wave_rest_max_sec)
            return WaveDecision(
                action="wave_break",
                wait_seconds=rest,
                reason=f"Wave complete ({wave_sent}/{wave_limit})",
            )

        # Periodic nurture insertion
        if self._should_nurture(wave_count, nurture_done_today):
            return WaveDecision(action="nurture", reason="Periodic nurture session")

        # Rest break within wave
        if sent_since_break >= random.randint(self.wave_sends_min, self.wave_sends_max):
            rest = random.randint(self.wave_rest_min_sec, self.wave_rest_max_sec)
            return WaveDecision(
                action="rest_break",
                wait_seconds=rest,
                reason=f"Mid-wave rest after {sent_since_break} sends",
            )

        return WaveDecision(action="send")

    def _should_nurture(self, wave_count: int, nurture_done_today: int) -> bool:
        if nurture_done_today >= self.nurture_frequency:
            return False
        return wave_count > 0 and wave_count % self.nurture_frequency == 0

    def daily_limit_reached(self) -> WaveDecision:
        return WaveDecision(action="stop", reason="Daily limit reached")

    def no_tasks(self) -> WaveDecision:
        return WaveDecision(action="stop", reason="No pending tasks")
