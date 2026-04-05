"""
Live engine — fast-poll quoting during games with circuit breaker.

Same core logic as pregame but:
  - 1 second poll interval
  - Circuit breaker: detect midpoint jumps → pull quotes → cooldown → requote
  - No view skew (pure symmetric — survival mode)
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from sfmm.core.types import Game, Market, Phase, QuoteInput, Side
from sfmm.engine.quoter import compute_quotes, should_update
from sfmm.execution.clob import ClobExecutor
from sfmm.feeds.orderbook import fetch_orderbook
from sfmm.risk.circuit import CircuitBreaker, Action
from sfmm.risk.limits import RiskManager

log = logging.getLogger(__name__)


class LiveEngine:
    """Manages live quoting for a single game with circuit breaker protection."""

    def __init__(
        self,
        game: Game,
        executor: ClobExecutor,
        risk: RiskManager,
        poll_interval: float = 1.0,
        cooldown_sec: float = 10.0,
        max_position: int = 1000,
    ):
        self.game = game
        self.executor = executor
        self.risk = risk
        self.poll_interval = poll_interval
        self.max_position = max_position

        self.breaker = CircuitBreaker(game.sport, cooldown_sec)

        self._live_bids: dict[str, tuple | None] = {}
        self._live_asks: dict[str, tuple | None] = {}
        self._bid_ids: dict[str, str | None] = {}
        self._ask_ids: dict[str, str | None] = {}

        self._running = False
        self._cycles = 0
        self._pulls = 0

    async def run(self):
        self._running = True
        self.breaker.reset()
        log.info("LIVE engine started for: %s", self.game.title)

        async with httpx.AsyncClient() as client:
            while self._running and self.game.phase == Phase.LIVE:
                if self.risk.halted:
                    await self._cancel_all()
                    await asyncio.sleep(30)
                    continue

                await self._cycle(client)
                self._cycles += 1
                await asyncio.sleep(self.poll_interval)

        await self._cancel_all()
        log.info(
            "LIVE engine stopped for: %s (%d cycles, %d pulls)",
            self.game.title, self._cycles, self._pulls,
        )

    async def stop(self):
        self._running = False

    async def _cycle(self, client: httpx.AsyncClient):
        for market in self.game.markets:
            try:
                await self._update_market(client, market)
            except Exception as e:
                log.error("Live cycle error for %s: %s", market.question[:40], e)

    async def _update_market(self, client: httpx.AsyncClient, market: Market):
        book = await fetch_orderbook(client, market.yes_token, market.min_size)
        if book is None:
            return

        # Circuit breaker check
        action = self.breaker.check(book.adjusted_mid)

        if action == Action.PULL:
            self._pulls += 1
            await self._cancel_market(market.market_id)
            return

        market.current_mid = book.adjusted_mid

        # Live mode: fair_value = midpoint (no view, pure symmetric)
        inp = QuoteInput(
            mid=book.adjusted_mid,
            fair_value=book.adjusted_mid,  # symmetric in live
            max_spread=market.max_spread,
            min_size=market.min_size,
            current_position=self.game.position,
            max_position=self.max_position,
        )

        target_bid, target_ask = compute_quotes(inp)

        # Widen if circuit says so
        if action == Action.WIDEN:
            # Move prices further from mid (half max_spread)
            widen = market.max_spread * 0.3
            target_bid = type(target_bid)(target_bid.price - widen, target_bid.size)
            target_ask = type(target_ask)(target_ask.price + widen, target_ask.size)

        mk = market.market_id
        from sfmm.core.types import Quote
        live_bid = Quote(*self._live_bids[mk]) if self._live_bids.get(mk) else None
        live_ask = Quote(*self._live_asks[mk]) if self._live_asks.get(mk) else None

        if not should_update(live_bid, live_ask, target_bid, target_ask):
            return

        # Cancel and replace
        if self._bid_ids.get(mk):
            self.executor.cancel_order(self._bid_ids[mk])
        if self._ask_ids.get(mk):
            self.executor.cancel_order(self._ask_ids[mk])

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
        self._live_bids[mk] = (target_bid.price, target_bid.size) if bid_id else None
        self._live_asks[mk] = (target_ask.price, target_ask.size) if ask_id else None

    async def _cancel_market(self, market_id: str):
        if self._bid_ids.get(market_id):
            self.executor.cancel_order(self._bid_ids[market_id])
            self._bid_ids[market_id] = None
            self._live_bids[market_id] = None
        if self._ask_ids.get(market_id):
            self.executor.cancel_order(self._ask_ids[market_id])
            self._ask_ids[market_id] = None
            self._live_asks[market_id] = None

    async def _cancel_all(self):
        for mk in list(self._bid_ids.keys()):
            await self._cancel_market(mk)
