"""Tests for the quote engine."""

from sfmm.core.types import Quote, QuoteInput
from sfmm.engine.quoter import compute_quotes, should_update, TICK


def make_input(**overrides) -> QuoteInput:
    defaults = dict(
        mid=0.50,
        fair_value=0.50,
        max_spread=0.03,
        min_size=50,
        current_position=0,
        max_position=1000,
        inventory_half_life=500,
    )
    defaults.update(overrides)
    return QuoteInput(**defaults)


class TestComputeQuotes:
    def test_symmetric_at_fair(self):
        """When fair_value == mid and position == 0, quotes should be symmetric."""
        bid, ask = compute_quotes(make_input())
        assert bid.price == 0.50 - TICK
        assert ask.price == 0.50 + TICK
        assert bid.size == ask.size  # symmetric

    def test_prices_always_one_tick(self):
        """Prices are always mid ± 1 tick regardless of fair value."""
        bid, ask = compute_quotes(make_input(fair_value=0.60))
        assert bid.price == 0.50 - TICK
        assert ask.price == 0.50 + TICK

    def test_bullish_skews_sizes(self):
        """When fair_value > mid, bid bigger, ask smaller."""
        bid, ask = compute_quotes(make_input(fair_value=0.55))
        assert bid.size > ask.size

    def test_bearish_skews_sizes(self):
        """When fair_value < mid, ask bigger, bid smaller."""
        bid, ask = compute_quotes(make_input(fair_value=0.45))
        assert ask.size > bid.size

    def test_both_sides_above_min(self):
        """Both sides always meet min_size (for 3x two-sided bonus)."""
        bid, ask = compute_quotes(make_input(fair_value=0.60))
        assert bid.size >= 50
        assert ask.size >= 50

    def test_inventory_mean_reversion(self):
        """Long position → bid shrinks, ask grows."""
        bid_long, ask_long = compute_quotes(make_input(current_position=300))
        bid_flat, ask_flat = compute_quotes(make_input(current_position=0))
        assert bid_long.size < bid_flat.size
        assert ask_long.size > ask_flat.size

    def test_max_position_caps_bid(self):
        """At max position, bid = 0 (can't buy more)."""
        bid, ask = compute_quotes(make_input(current_position=1000, max_position=1000))
        assert bid.size == 0

    def test_max_short_caps_ask(self):
        """At max short, ask = 0 (can't sell more)."""
        bid, ask = compute_quotes(make_input(current_position=-1000, max_position=1000))
        assert ask.size == 0

    def test_price_clamp_low(self):
        """Bid price doesn't go below 0.01."""
        bid, ask = compute_quotes(make_input(mid=0.01))
        assert bid.price >= 0.01

    def test_price_clamp_high(self):
        """Ask price doesn't exceed 0.99."""
        bid, ask = compute_quotes(make_input(mid=0.99))
        assert ask.price <= 0.99


class TestShouldUpdate:
    def test_no_live_orders(self):
        assert should_update(None, None, Quote(0.49, 100), Quote(0.51, 100))

    def test_same_quotes(self):
        bid = Quote(0.49, 100)
        ask = Quote(0.51, 100)
        assert not should_update(bid, ask, bid, ask)

    def test_price_moved(self):
        assert should_update(
            Quote(0.49, 100), Quote(0.51, 100),
            Quote(0.50, 100), Quote(0.52, 100),
        )

    def test_size_changed_small(self):
        """10% change — below threshold, don't update."""
        assert not should_update(
            Quote(0.49, 100), Quote(0.51, 100),
            Quote(0.49, 110), Quote(0.51, 90),
        )

    def test_size_changed_large(self):
        """50% change — above threshold, update."""
        assert should_update(
            Quote(0.49, 100), Quote(0.51, 100),
            Quote(0.49, 150), Quote(0.51, 50),
        )
