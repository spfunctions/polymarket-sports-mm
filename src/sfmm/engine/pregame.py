"""
Pre-game engine — poll orderbook, compute quotes, place/update orders.

Loop:
  1. Fetch orderbook for each active market
  2. Compute adjusted midpoint
  3. Fair value = midpoint (Level 0) or external odds blend (Level 1+)
  4. Run quoter → target bid/ask
  5. If changed: cancel old, place new
  6. Sleep poll_interval
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx

from sfmm.core.types import Game, Market, Phase, QuoteInput, Quote, Side
from sfmm.engine.quoter import compute_quotes, should_update
from sfmm.execution.clob import ClobExecutor
from sfmm.feeds.orderbook import fetch_orderbook, BookSnapshot
from sfmm.risk.limits import RiskManager

log = logging.getLogger(__name__)


class PregameEngine:
    """Manages pre-game quoting for a single game."""

    def __init__(
        self,
        game: Game,
        executor: ClobExecutor,
        risk: RiskManager,
        poll_interval: float = 5.0,
        max_position: int = 1000,
    ):
        self.game = game
        self.executor = executor
        self.risk = risk
        self.poll_interval = poll_interval
        self.max_position = max_position

        # Live order tracking per market
        self._live_bids: dict[str, Quote | None] = {}
        self._live_asks: dict[str, Quote | None] = {}
        self._bid_ids: dict[str, str | None] = {}
        self._ask_ids: dict[str, str | None] = {}

        self._running = False
        self._cycles = 0

    async def run(self):
        """Main loop. Runs until game phase changes or stopped."""
        self._running = True
        log.info("PRE engine started for: %s (%d markets)",
                 self.game.title, len(self.game.markets))

        async with httpx.AsyncClient() as client:
            while self._running and self.game.phase == Phase.PRE:
                if self.risk.halted:
                    log.warning("Risk halted, pausing quotes")
                    await self._cancel_all()
                    await asyncio.sleep(60)
                    continue

                await self._cycle(client)
                self._cycles += 1
                await asyncio.sleep(self.poll_interval)

        # Cleanup
        await self._cancel_all()
        log.info("PRE engine stopped for: %s (ran %d cycles)", self.game.title, self._cycles)

    async def stop(self):
        self._running = False

    async def _cycle(self, client: httpx.AsyncClient):
        """One poll-compute-update cycle."""
        for market in self.game.markets:
            try:
                await self._update_market(client, market)
            except Exception as e:
                log.error("Cycle error for %s: %s", market.question[:40], e)

    async def _update_market(self, client: httpx.AsyncClient, market: Market):
        """Update quotes for a single market."""
        book = await fetch_orderbook(client, market.yes_token, market.min_size)
        if book is None:
            return

        market.current_mid = book.adjusted_mid
        market.best_bid = book.best_bid
        market.best_ask = book.best_ask

        # Fair value: Level 0 = midpoint
        fair_value = book.adjusted_mid

        # Compute target quotes
        inp = QuoteInput(
            mid=book.adjusted_mid,
            fair_value=fair_value,
            max_spread=market.max_spread,
            min_size=market.min_size,
            current_position=self.game.position,
            max_position=self.max_position,
        )
        target_bid, target_ask = compute_quotes(inp)

        # Check if update needed
        mk = market.market_id
        live_bid = self._live_bids.get(mk)
        live_ask = self._live_asks.get(mk)

        if not should_update(live_bid, live_ask, target_bid, target_ask):
            return

        # Cancel old orders
        if self._bid_ids.get(mk):
            self.executor.cancel_order(self._bid_ids[mk])
        if self._ask_ids.get(mk):
            self.executor.cancel_order(self._ask_ids[mk])

        # Place new orders
        bid_id = None
        ask_id = None

        if target_bid.size > 0:
            bid_id = self.executor.place_order(
                market.yes_token, target_bid.price, target_bid.size, Side.BUY,
            )

        if target_ask.size > 0:
            ask_id = self.executor.place_order(
                market.yes_token, target_ask.price, target_ask.size, Side.SELL,
            )

        self._bid_ids[mk] = bid_id
        self._ask_ids[mk] = ask_id
        self._live_bids[mk] = target_bid if bid_id else None
        self._live_asks[mk] = target_ask if ask_id else None

        log.info(
            "  %s: bid %.2f×%d ask %.2f×%d (mid=%.3f)",
            market.question[:30],
            target_bid.price, target_bid.size,
            target_ask.price, target_ask.size,
            book.adjusted_mid,
        )

    async def _cancel_all(self):
        """Cancel all live orders for this game."""
        for mk in list(self._bid_ids.keys()):
            if self._bid_ids.get(mk):
                self.executor.cancel_order(self._bid_ids[mk])
                self._bid_ids[mk] = None
                self._live_bids[mk] = None
            if self._ask_ids.get(mk):
                self.executor.cancel_order(self._ask_ids[mk])
                self._ask_ids[mk] = None
                self._live_asks[mk] = None
