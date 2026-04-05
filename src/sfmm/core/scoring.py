"""
Polymarket liquidity reward scoring functions.

Reference: https://docs.polymarket.com/market-makers/liquidity-rewards
All functions are pure — no side effects, no IO.

Scoring formula: S(v, s) = ((v - s) / v)^2 * b
  v = max_incentive_spread (configured per market)
  s = distance from size-cutoff-adjusted midpoint
  b = in-game multiplier (1.0 for pre, >1 for live)

Two-sided bonus:
  Q_min = max(min(Q_one, Q_two), max(Q_one, Q_two) / c)
  c = 3.0 (single-sided penalty factor)
"""

from __future__ import annotations

# Scaling factor — single-sided orders score at 1/c of two-sided
C = 3.0


def order_score(max_spread: float, spread: float, multiplier: float = 1.0) -> float:
    """
    Score a single order by its distance from the adjusted midpoint.

    S(v, s) = ((v - s) / v)^2 * b

    Args:
        max_spread: v — maximum qualifying spread (e.g. 0.03 for 3 cents)
        spread: s — actual distance from adjusted midpoint (0-1)
        multiplier: b — in-game multiplier (default 1.0)

    Returns:
        Score in [0, 1] * multiplier. Orders outside max_spread score 0.
    """
    if max_spread <= 0 or spread < 0:
        return 0.0
    if spread >= max_spread:
        return 0.0
    ratio = (max_spread - spread) / max_spread
    return ratio * ratio * multiplier


def side_score(
    orders: list[tuple[float, int]],
    max_spread: float,
    multiplier: float = 1.0,
) -> float:
    """
    Compute total score for one side of the book.

    Q = sum(S(v, spread_i) * size_i)

    Args:
        orders: list of (spread_from_mid, size) tuples
        max_spread: v
        multiplier: b
    """
    total = 0.0
    for spread, size in orders:
        total += order_score(max_spread, spread, multiplier) * size
    return total


def q_min(q_one: float, q_two: float, midpoint: float = 0.5) -> float:
    """
    Compute Q_min from both sides' scores.

    If midpoint in [0.10, 0.90]:
      Q_min = max(min(Q_one, Q_two), max(Q_one, Q_two) / c)
      — single-sided liquidity scores at 1/c rate

    If midpoint outside [0.10, 0.90]:
      Q_min = min(Q_one, Q_two)
      — must be two-sided to score anything

    Args:
        q_one: first side score
        q_two: second side score
        midpoint: current market midpoint (0-1)
    """
    if 0.10 <= midpoint <= 0.90:
        return max(min(q_one, q_two), max(q_one, q_two) / C)
    else:
        return min(q_one, q_two)


def q_normal(our_q_min: float, total_q_min: float) -> float:
    """
    Normalize Q_min against all market makers for a single sample.

    Q_normal = Q_min_n / sum(Q_min for all n)
    """
    if total_q_min <= 0:
        return 1.0 if our_q_min > 0 else 0.0
    return our_q_min / total_q_min


def epoch_reward(q_final: float, pool_usd: float) -> float:
    """
    Compute reward for an epoch.

    reward = Q_final * pool_size
    """
    return q_final * pool_usd


def estimate_reward_share(
    our_q_min: float,
    estimated_total_q: float,
    pool_usd: float,
) -> float:
    """
    Estimate our reward share given our Q_min and estimated competition.
    Useful for real-time monitoring.
    """
    share = q_normal(our_q_min, estimated_total_q)
    return epoch_reward(share, pool_usd)


def adjusted_midpoint(
    bids: list[tuple[float, float]],
    asks: list[tuple[float, float]],
    min_size: int,
) -> float:
    """
    Compute size-cutoff-adjusted midpoint.
    Filters out orders below min_incentive_size before computing mid.

    Args:
        bids: [(price, size), ...] sorted by price descending
        asks: [(price, size), ...] sorted by price ascending
        min_size: min_incentive_size

    Returns:
        Adjusted midpoint (0-1)
    """
    valid_bids = [b for b in bids if b[1] >= min_size]
    valid_asks = [a for a in asks if a[1] >= min_size]

    if not valid_bids and not valid_asks:
        # No valid orders at all — use raw best bid/ask
        best_bid = bids[0][0] if bids else 0.0
        best_ask = asks[0][0] if asks else 1.0
        return (best_bid + best_ask) / 2

    best_bid = valid_bids[0][0] if valid_bids else (bids[0][0] if bids else 0.0)
    best_ask = valid_asks[0][0] if valid_asks else (asks[0][0] if asks else 1.0)

    return (best_bid + best_ask) / 2


def optimal_quote_score(max_spread: float, tick: float = 0.01) -> float:
    """
    Score of an order placed one tick from midpoint.
    This is our target operating point.

    Example: max_spread=0.03, tick=0.01 → ((0.03-0.01)/0.03)^2 = 0.444
    """
    return order_score(max_spread, tick)
