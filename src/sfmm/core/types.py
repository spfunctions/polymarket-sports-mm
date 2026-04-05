"""Core data types for the market making system."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Phase(Enum):
    DISCOVER = "discover"
    PRE = "pre"
    LIVE = "live"
    POST = "post"


class Sport(Enum):
    SOCCER = "soccer"
    BASKETBALL = "basketball"
    TENNIS = "tennis"
    CS2 = "cs2"
    LOL = "lol"
    DOTA2 = "dota2"
    VALORANT = "valorant"
    UFC = "ufc"
    BASEBALL = "baseball"
    HOCKEY = "hockey"
    CRICKET = "cricket"


class Side(Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class Quote:
    price: float   # 0-1 (e.g. 0.50 = 50 cents)
    size: int      # contracts


@dataclass
class OrderState:
    order_id: str
    token_id: str
    side: Side
    price: float
    size: int
    filled: int = 0


@dataclass
class Fill:
    order_id: str
    price: float
    size: int
    side: Side
    ts: str = ""


@dataclass
class Market:
    """A single outcome market within a game event."""
    market_id: str
    condition_id: str
    question: str
    yes_token: str
    no_token: str
    max_spread: float          # max_incentive_spread (0-1)
    min_size: int              # min_incentive_size
    current_mid: float = 0.5
    best_bid: float = 0.0
    best_ask: float = 1.0
    volume_24h: float = 0.0
    liquidity: float = 0.0


@dataclass
class Game:
    """A sports event with one or more markets."""
    event_id: str
    title: str
    sport: Sport
    league: str
    start_time: str            # ISO timestamp
    phase: Phase = Phase.DISCOVER
    markets: list[Market] = field(default_factory=list)
    reward_pre_usd: float = 0.0
    reward_live_usd: float = 0.0

    # Runtime state
    intent_id: Optional[str] = None
    active_orders: dict[str, OrderState] = field(default_factory=dict)
    position: int = 0          # net YES contracts (positive = long)
    realized_pnl: float = 0.0
    fills: list[Fill] = field(default_factory=list)


@dataclass
class QuoteInput:
    """Everything the quoter needs to compute optimal quotes."""
    mid: float                 # adjusted midpoint (0-1)
    fair_value: float          # our estimate (0-1)
    max_spread: float          # v — max_incentive_spread (0-1)
    min_size: int              # min_incentive_size
    current_position: int      # net position (+long YES)
    max_position: int          # risk limit per market
    inventory_half_life: int = 500
