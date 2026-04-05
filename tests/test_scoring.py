"""
Tests for scoring module.
Verifies against the worked example in Polymarket docs:
  https://docs.polymarket.com/market-makers/liquidity-rewards#worked-example

Setup: adjusted midpoint = 0.50, max_spread = 0.03 for both m and m'
"""

from sfmm.core.scoring import (
    order_score,
    side_score,
    q_min,
    q_normal,
    adjusted_midpoint,
    optimal_quote_score,
    C,
)


class TestOrderScore:
    """S(v, s) = ((v - s) / v)^2"""

    def test_at_midpoint(self):
        # s=0 → score = 1.0
        assert order_score(0.03, 0.0) == 1.0

    def test_at_max_spread(self):
        # s=v → score = 0.0
        assert order_score(0.03, 0.03) == 0.0

    def test_beyond_max_spread(self):
        # s > v → score = 0.0
        assert order_score(0.03, 0.05) == 0.0

    def test_one_cent(self):
        # s=0.01, v=0.03 → ((0.03-0.01)/0.03)^2 = (2/3)^2 = 0.4444
        s = order_score(0.03, 0.01)
        assert abs(s - (2 / 3) ** 2) < 1e-10

    def test_two_cents(self):
        # s=0.02, v=0.03 → ((0.03-0.02)/0.03)^2 = (1/3)^2 = 0.1111
        s = order_score(0.03, 0.02)
        assert abs(s - (1 / 3) ** 2) < 1e-10

    def test_half_cent(self):
        # s=0.005, v=0.03 → ((0.03-0.005)/0.03)^2 = (5/6)^2
        s = order_score(0.03, 0.005)
        assert abs(s - (5 / 6) ** 2) < 1e-10

    def test_with_multiplier(self):
        s = order_score(0.03, 0.01, multiplier=2.5)
        assert abs(s - (2 / 3) ** 2 * 2.5) < 1e-10

    def test_zero_spread_returns_zero(self):
        assert order_score(0.0, 0.0) == 0.0

    def test_negative_spread_returns_zero(self):
        assert order_score(0.03, -0.01) == 0.0


class TestSideScore:
    """Q = sum(S(v, s_i) * size_i)"""

    def test_single_order(self):
        # 100 contracts at 1 cent spread, v=0.03
        q = side_score([(0.01, 100)], 0.03)
        assert abs(q - (2 / 3) ** 2 * 100) < 1e-6

    def test_multiple_orders(self):
        # From Polymarket worked example — Q_one (first side):
        # 100Q bid on m @ 0.49 (spread=1c), 200Q bid on m @ 0.48 (spread=2c),
        # 100Q ask on m' @ 0.51 (spread=1c)
        v = 0.03
        q_one = side_score(
            [(0.01, 100), (0.02, 200), (0.01, 100)],
            v,
        )
        expected = (
            (2 / 3) ** 2 * 100
            + (1 / 3) ** 2 * 200
            + (2 / 3) ** 2 * 100
        )
        assert abs(q_one - expected) < 1e-6

    def test_empty_orders(self):
        assert side_score([], 0.03) == 0.0


class TestQMin:
    """Q_min logic — two-sided bonus and extreme midpoint handling."""

    def test_balanced_two_sided(self):
        # min(100, 100) = 100
        assert q_min(100, 100) == 100

    def test_unbalanced_two_sided(self):
        # max(min(200, 50), max(200, 50)/3) = max(50, 66.67) = 66.67
        result = q_min(200, 50)
        assert abs(result - 200 / C) < 1e-6  # single-sided fallback is better

    def test_single_sided_normal_midpoint(self):
        # midpoint=0.50: max(min(100, 0), max(100, 0)/3) = max(0, 33.33) = 33.33
        result = q_min(100, 0, midpoint=0.50)
        assert abs(result - 100 / C) < 1e-6

    def test_single_sided_extreme_midpoint(self):
        # midpoint=0.05: min(100, 0) = 0 (no single-sided allowed)
        assert q_min(100, 0, midpoint=0.05) == 0.0
        assert q_min(100, 0, midpoint=0.95) == 0.0

    def test_two_sided_at_boundary(self):
        # midpoint=0.10 is IN range [0.10, 0.90]
        result = q_min(100, 0, midpoint=0.10)
        assert abs(result - 100 / C) < 1e-6

    def test_two_sided_just_outside(self):
        # midpoint=0.09 is OUTSIDE range
        assert q_min(100, 0, midpoint=0.09) == 0.0

    def test_unbalanced_but_single_sided_better(self):
        # q_one=300, q_two=10, midpoint=0.50
        # min(300, 10) = 10
        # max(300, 10)/3 = 100
        # Q_min = max(10, 100) = 100
        result = q_min(300, 10, midpoint=0.50)
        assert abs(result - 100) < 1e-6


class TestQNormal:
    def test_sole_maker(self):
        # Only maker → gets 100%
        assert q_normal(100, 100) == 1.0

    def test_equal_share(self):
        # 5 equal makers → 20% each
        assert abs(q_normal(100, 500) - 0.2) < 1e-10

    def test_zero_total(self):
        # No makers but we have score → we get 100%
        assert q_normal(50, 0) == 1.0

    def test_zero_both(self):
        assert q_normal(0, 0) == 0.0


class TestAdjustedMidpoint:
    def test_normal_book(self):
        bids = [(0.49, 100), (0.48, 200)]
        asks = [(0.51, 100), (0.52, 200)]
        mid = adjusted_midpoint(bids, asks, min_size=50)
        assert mid == (0.49 + 0.51) / 2

    def test_filters_small_orders(self):
        bids = [(0.49, 10), (0.48, 200)]   # best bid too small
        asks = [(0.51, 100), (0.52, 200)]
        mid = adjusted_midpoint(bids, asks, min_size=50)
        # best valid bid is 0.48, best valid ask is 0.51
        assert mid == (0.48 + 0.51) / 2

    def test_all_small(self):
        bids = [(0.49, 10)]
        asks = [(0.51, 10)]
        # Falls back to raw best bid/ask
        mid = adjusted_midpoint(bids, asks, min_size=50)
        assert mid == (0.49 + 0.51) / 2

    def test_empty_book(self):
        mid = adjusted_midpoint([], [], min_size=50)
        assert mid == 0.5  # (0.0 + 1.0) / 2


class TestOptimalQuoteScore:
    def test_default_tick(self):
        # v=0.03, tick=0.01 → (2/3)^2 = 0.4444
        s = optimal_quote_score(0.03)
        assert abs(s - (2 / 3) ** 2) < 1e-10

    def test_wider_spread(self):
        # v=0.05, tick=0.01 → (4/5)^2 = 0.64
        s = optimal_quote_score(0.05)
        assert abs(s - (4 / 5) ** 2) < 1e-10


class TestWorkedExample:
    """
    Full worked example from Polymarket docs.
    midpoint=0.50, max_spread=0.03
    """

    def test_q_one(self):
        v = 0.03
        # Bids on m: 100@0.49(s=1c), 200@0.48(s=2c)
        # Asks on m': 100@0.51(s=1c)
        q_one = side_score([(0.01, 100), (0.02, 200), (0.01, 100)], v)
        expected = (2 / 3) ** 2 * 100 + (1 / 3) ** 2 * 200 + (2 / 3) ** 2 * 100
        assert abs(q_one - expected) < 1e-6

    def test_q_two(self):
        v = 0.03
        # Bids on m: 100@0.485(s=1.5c), Bids on m': 100@0.48(s=2c)
        # Asks on m': 200@0.505(s=0.5c)
        q_two = side_score([(0.015, 100), (0.02, 100), (0.005, 200)], v)
        expected = (
            ((0.03 - 0.015) / 0.03) ** 2 * 100
            + (1 / 3) ** 2 * 100
            + ((0.03 - 0.005) / 0.03) ** 2 * 200
        )
        assert abs(q_two - expected) < 1e-6

    def test_q_min_with_worked_values(self):
        v = 0.03
        q_one = side_score([(0.01, 100), (0.02, 200), (0.01, 100)], v)
        q_two = side_score([(0.015, 100), (0.02, 100), (0.005, 200)], v)

        result = q_min(q_one, q_two, midpoint=0.50)
        # Should be min(q_one, q_two) since both are > 0
        assert result == min(q_one, q_two)
