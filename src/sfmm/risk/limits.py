"""
Position and loss limits.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class RiskLimits:
    max_position_per_market: int = 1000     # contracts
    max_total_exposure_usd: float = 5000.0
    daily_loss_limit_usd: float = 500.0


class RiskManager:
    def __init__(self, limits: RiskLimits):
        self.limits = limits
        self.daily_pnl: float = 0.0
        self.total_exposure_usd: float = 0.0
        self.halted: bool = False

    def check_order(self, position: int, order_size: int, price: float) -> bool:
        """Check if a new order is allowed."""
        if self.halted:
            log.warning("Risk halted — rejecting order")
            return False

        new_position = abs(position + order_size)
        if new_position > self.limits.max_position_per_market:
            log.warning("Position limit: %d > %d", new_position, self.limits.max_position_per_market)
            return False

        new_exposure = self.total_exposure_usd + order_size * price
        if new_exposure > self.limits.max_total_exposure_usd:
            log.warning("Exposure limit: $%.0f > $%.0f", new_exposure, self.limits.max_total_exposure_usd)
            return False

        return True

    def record_fill(self, price: float, size: int, is_buy: bool):
        """Update state after a fill."""
        cost = size * price
        if is_buy:
            self.total_exposure_usd += cost
        else:
            self.total_exposure_usd -= cost

    def record_pnl(self, pnl: float):
        """Record realized P&L. Halt if daily limit breached."""
        self.daily_pnl += pnl
        if self.daily_pnl < -self.limits.daily_loss_limit_usd:
            log.error(
                "DAILY LOSS LIMIT: $%.2f < -$%.2f — HALTING",
                self.daily_pnl, self.limits.daily_loss_limit_usd,
            )
            self.halted = True

    def reset_daily(self):
        """Call at midnight UTC."""
        self.daily_pnl = 0.0
        self.halted = False
        log.info("Daily risk reset")
