"""
Market discovery — find sports events on Polymarket via the Gamma API.
Maps events to Game objects with token IDs and reward estimates.
"""

from __future__ import annotations

import json
import logging

import httpx

from sfmm.core.types import Game, Market, Phase, Sport

log = logging.getLogger(__name__)

GAMMA = "https://gamma-api.polymarket.com"

# Tag slugs that Polymarket uses for sports
SPORTS_TAGS = [
    "sports", "soccer", "football", "basketball", "nba", "nfl",
    "tennis", "mma", "ufc", "cricket", "ipl", "baseball", "mlb",
    "hockey", "nhl", "esports", "cs2", "league-of-legends", "dota2",
    "valorant", "epl", "champions-league", "la-liga", "serie-a",
    "bundesliga", "ligue-1",
]

# Rough league → sport mapping
LEAGUE_SPORT: dict[str, Sport] = {
    "epl": Sport.SOCCER, "premier-league": Sport.SOCCER,
    "la-liga": Sport.SOCCER, "serie-a": Sport.SOCCER,
    "bundesliga": Sport.SOCCER, "ligue-1": Sport.SOCCER,
    "champions-league": Sport.SOCCER, "europa-league": Sport.SOCCER,
    "mls": Sport.SOCCER, "liga-mx": Sport.SOCCER,
    "nba": Sport.BASKETBALL, "euroleague": Sport.BASKETBALL,
    "mlb": Sport.BASEBALL, "nhl": Sport.HOCKEY,
    "ufc": Sport.UFC, "mma": Sport.UFC,
    "atp": Sport.TENNIS, "wta": Sport.TENNIS,
    "ipl": Sport.CRICKET,
    "cs2": Sport.CS2, "counter-strike": Sport.CS2,
    "league-of-legends": Sport.LOL, "lol": Sport.LOL,
    "dota2": Sport.DOTA2, "dota-2": Sport.DOTA2,
    "valorant": Sport.VALORANT,
}


def _guess_sport(title: str, slug: str) -> Sport:
    """Best-effort sport classification from event title/slug."""
    combined = (title + " " + slug).lower()
    for key, sport in LEAGUE_SPORT.items():
        if key in combined:
            return sport
    return Sport.SOCCER  # default


def _guess_league(title: str, slug: str) -> str:
    combined = (title + " " + slug).lower()
    for key in LEAGUE_SPORT:
        if key in combined:
            return key
    return "unknown"


async def discover_sports_events(
    client: httpx.AsyncClient,
    limit: int = 50,
) -> list[Game]:
    """
    Search Polymarket for active sports events.
    Returns Game objects with markets and token IDs.
    """
    games: list[Game] = []

    # Search across sports tags
    for tag in ["sports", "soccer", "basketball", "esports", "tennis", "mma", "cricket", "baseball", "hockey"]:
        try:
            resp = await client.get(
                f"{GAMMA}/events",
                params={
                    "active": "true",
                    "closed": "false",
                    "tag_slug": tag,
                    "limit": str(min(limit, 50)),
                },
                timeout=10.0,
            )
            if resp.status_code != 200:
                log.warning("Gamma API %d for tag=%s", resp.status_code, tag)
                continue

            events = resp.json()
            if not isinstance(events, list):
                continue

            for event in events:
                game = _parse_event(event)
                if game and game.event_id not in {g.event_id for g in games}:
                    games.append(game)

        except Exception as e:
            log.warning("discover error for tag=%s: %s", tag, e)

    log.info("Discovered %d sports events", len(games))
    return games


def _parse_event(event: dict) -> Game | None:
    """Parse a Gamma API event into a Game object."""
    event_id = str(event.get("id", ""))
    title = event.get("title", "")
    slug = event.get("slug", "")
    start_time = event.get("startDate", event.get("endDate", ""))

    if not event_id or not title:
        return None

    raw_markets = event.get("markets", [])
    if not raw_markets:
        return None

    markets: list[Market] = []
    for m in raw_markets:
        market = _parse_market(m)
        if market:
            markets.append(market)

    if not markets:
        return None

    return Game(
        event_id=event_id,
        title=title,
        sport=_guess_sport(title, slug),
        league=_guess_league(title, slug),
        start_time=start_time,
        phase=Phase.DISCOVER,
        markets=markets,
    )


def _parse_market(m: dict) -> Market | None:
    """Parse a Gamma API market into a Market object."""
    market_id = m.get("id", "")
    condition_id = m.get("conditionId", "")
    question = m.get("question", "")

    # Parse token IDs
    clob_raw = m.get("clobTokenIds", "[]")
    try:
        tokens = json.loads(clob_raw) if isinstance(clob_raw, str) else clob_raw
    except (json.JSONDecodeError, TypeError):
        return None

    if not tokens or len(tokens) < 2:
        return None

    # Parse prices
    prices_raw = m.get("outcomePrices", "[]")
    try:
        prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
    except (json.JSONDecodeError, TypeError):
        prices = [0.5, 0.5]

    accepting = m.get("acceptingOrders", True)
    if not accepting:
        return None

    return Market(
        market_id=market_id,
        condition_id=condition_id,
        question=question,
        yes_token=tokens[0],
        no_token=tokens[1],
        max_spread=0.03,  # default, will be overridden from CLOB API
        min_size=50,      # default
        current_mid=float(prices[0]) if prices else 0.5,
        best_bid=m.get("bestBid", 0.0),
        best_ask=m.get("bestAsk", 1.0),
        volume_24h=m.get("volume24hr", 0.0),
        liquidity=m.get("liquidityNum", 0.0),
    )
