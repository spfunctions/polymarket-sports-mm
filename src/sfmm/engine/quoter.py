"""
Quote engine — computes optimal bid/ask given market state and risk parameters.

Core principle: prices for score, sizes for view.
  - Price: always mid ± 1 tick (maximizes quadratic score)
  - Size: skewed by (view + inventory mean-reversion)
"""

from __future__ import annotations

from sfmm.core.types import Quote, QuoteInput


TICK = 0.01  # 1 cent — smallest price increment


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def compute_quotes(inp: QuoteInput) -> tuple[Quote, Quote]:
    """
    Compute optimal bid and ask quotes.

    Strategy:
      1. Price: mid ± 1 tick (near-maximum score)
      2. View skew: (fair_value - mid) / max_spread → lean sizes toward our view
      3. Inventory skew: -position / half_life → mean-revert inventory
      4. Blend: 70% view + 30% inventory
      5. Clamp: both sides ≥ min_size (preserve two-sided 3x multiplier)

    Returns:
        (bid_quote, ask_quote)
    """
    # ── Prices: symmetric around mid ──
    bid_price = clamp(inp.mid - TICK, 0.01, 0.99)
    ask_price = clamp(inp.mid + TICK, 0.01, 0.99)

    # ── Size skew ──
    # View: positive = bullish (fair > mid), buy more, sell less
    view_skew = 0.0
    if inp.max_spread > 0:
        view_skew = (inp.fair_value - inp.mid) / inp.max_spread
        view_skew = clamp(view_skew, -0.6, 0.6)

    # Inventory: mean-revert. Long → sell more. Short → buy more.
    inv_skew = 0.0
    if inp.inventory_half_life > 0:
        inv_skew = -inp.current_position / inp.inventory_half_life
        inv_skew = clamp(inv_skew, -0.4, 0.4)

    # Blend
    total_skew = 0.7 * view_skew + 0.3 * inv_skew
    total_skew = clamp(total_skew, -0.8, 0.8)

    # Base size: 2x minimum for cushion
    base = max(inp.min_size, inp.min_size * 2)

    bid_size = max(inp.min_size, int(base * (1 + total_skew)))
    ask_size = max(inp.min_size, int(base * (1 - total_skew)))

    # Position limits
    room_to_buy = inp.max_position - inp.current_position
    room_to_sell = inp.max_position + inp.current_position

    if room_to_buy <= 0:
        bid_size = 0
    else:
        bid_size = min(bid_size, room_to_buy)

    if room_to_sell <= 0:
        ask_size = 0
    else:
        ask_size = min(ask_size, room_to_sell)

    return Quote(bid_price, bid_size), Quote(ask_price, ask_size)


def should_update(
    live_bid: Quote | None,
    live_ask: Quote | None,
    target_bid: Quote,
    target_ask: Quote,
    price_threshold: float = TICK,
    size_threshold: float = 0.2,
) -> bool:
    """
    Decide whether to cancel-and-replace live orders.
    Avoids unnecessary churn if quotes haven't changed meaningfully.

    Returns True if any of:
      - No live orders (need to place)
      - Price moved by > price_threshold
      - Size changed by > size_threshold (relative)
    """
    if live_bid is None or live_ask is None:
        return True

    # Price changed
    if abs(live_bid.price - target_bid.price) > price_threshold * 0.5:
        return True
    if abs(live_ask.price - target_ask.price) > price_threshold * 0.5:
        return True

    # Size changed significantly
    if live_bid.size > 0:
        bid_delta = abs(target_bid.size - live_bid.size) / live_bid.size
        if bid_delta > size_threshold:
            return True

    if live_ask.size > 0:
        ask_delta = abs(target_ask.size - live_ask.size) / live_ask.size
        if ask_delta > size_threshold:
            return True

    return False
