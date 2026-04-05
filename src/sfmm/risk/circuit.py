"""
Circuit breaker — detect game events via orderbook jumps and protect against adverse selection.

Actions:
  CONTINUE — normal quoting
  WIDEN    — widen spreads (marginal event)
  PULL     — cancel all quotes (major event, wait for cooldown)
"""

from __future__ import annotations

import time
import logging
from enum import Enum

from sfmm.core.types import Sport

log = logging.getLogger(__name__)


class Action(Enum):
    CONTINUE = "continue"
    WIDEN = "widen"
    PULL = "pull"


# Midpoint jump thresholds per sport (in probability units, 0-1)
# These represent "likely major game event" detection
JUMP_THRESHOLDS: dict[Sport, float] = {
    Sport.SOCCER: 0.08,       # goal ≈ 15-30c swing
    Sport.BASKETBALL: 0.03,   # unusual — scores are frequent but small
    Sport.TENNIS: 0.10,       # break of serve
    Sport.CS2: 0.06,          # round end / half
    Sport.LOL: 0.05,          # tower / baron / teamfight
    Sport.DOTA2: 0.05,
    Sport.VALORANT: 0.06,
    Sport.UFC: 0.15,          # knockout
    Sport.BASEBALL: 0.05,     # home run
    Sport.HOCKEY: 0.07,       # goal
    Sport.CRICKET: 0.04,      # wicket
}

DEFAULT_THRESHOLD = 0.06


class CircuitBreaker:
    """
    Tracks midpoint history and decides whether to pull/widen quotes.
    """

    def __init__(self, sport: Sport, cooldown_sec: float = 10.0):
        self.sport = sport
        self.threshold = JUMP_THRESHOLDS.get(sport, DEFAULT_THRESHOLD)
        self.cooldown_sec = cooldown_sec
        self.last_pull_time: float = 0.0
        self.last_mid: float | None = None
        self.pull_count: int = 0

    def check(self, new_mid: float) -> Action:
        """
        Check if circuit should break given new midpoint.
        """
        now = time.time()

        # Still in cooldown from last pull
        if now - self.last_pull_time < self.cooldown_sec:
            return Action.PULL

        if self.last_mid is None:
            self.last_mid = new_mid
            return Action.CONTINUE

        delta = abs(new_mid - self.last_mid)
        self.last_mid = new_mid

        if delta > self.threshold:
            log.warning(
                "CIRCUIT BREAK: %s delta=%.3f > threshold=%.3f",
                self.sport.value, delta, self.threshold,
            )
            self.last_pull_time = now
            self.pull_count += 1
            return Action.PULL

        if delta > self.threshold * 0.5:
            log.info(
                "WIDEN: %s delta=%.3f (half-threshold)",
                self.sport.value, delta,
            )
            return Action.WIDEN

        return Action.CONTINUE

    def reset(self):
        """Reset state (e.g., on phase transition)."""
        self.last_mid = None
        self.last_pull_time = 0.0

    @property
    def in_cooldown(self) -> bool:
        return time.time() - self.last_pull_time < self.cooldown_sec
