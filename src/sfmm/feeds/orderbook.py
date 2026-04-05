"""
Orderbook feed — poll Polymarket CLOB for orderbook data.
Computes adjusted midpoint and detects price jumps.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from sfmm.core.scoring import adjusted_midpoint

log = logging.getLogger(__name__)

CLOB = "https://clob.polymarket.com"


@dataclass
class BookSnapshot:
    token_id: str
    best_bid: float
    best_ask: float
    mid: float
    adjusted_mid: float
    bids: list[tuple[float, float]]   # (price, size) desc by price
    asks: list[tuple[float, float]]   # (price, size) asc by price
    timestamp: str = ""


async def fetch_orderbook(
    client: httpx.AsyncClient,
    token_id: str,
    min_size: int = 50,
) -> BookSnapshot | None:
    """Fetch orderbook for a token and compute adjusted midpoint."""
    try:
        resp = await client.get(
            f"{CLOB}/book",
            params={"token_id": token_id},
            timeout=5.0,
        )
        if resp.status_code != 200:
            log.warning("CLOB book %d for %s", resp.status_code, token_id[:16])
            return None

        data = resp.json()
        raw_bids = data.get("bids", [])
        raw_asks = data.get("asks", [])

        bids = [
            (float(b["price"]), float(b["size"]))
            for b in raw_bids
            if "price" in b and "size" in b
        ]
        asks = [
            (float(a["price"]), float(a["size"]))
            for a in raw_asks
            if "price" in a and "size" in a
        ]

        # Sort: bids descending, asks ascending
        bids.sort(key=lambda x: -x[0])
        asks.sort(key=lambda x: x[0])

        best_bid = bids[0][0] if bids else 0.0
        best_ask = asks[0][0] if asks else 1.0
        raw_mid = (best_bid + best_ask) / 2

        adj_mid = adjusted_midpoint(bids, asks, min_size)

        return BookSnapshot(
            token_id=token_id,
            best_bid=best_bid,
            best_ask=best_ask,
            mid=raw_mid,
            adjusted_mid=adj_mid,
            bids=bids,
            asks=asks,
            timestamp=data.get("timestamp", ""),
        )

    except Exception as e:
        log.warning("fetch_orderbook error for %s: %s", token_id[:16], e)
        return None


async def fetch_midpoint(
    client: httpx.AsyncClient,
    token_id: str,
) -> float | None:
    """Lightweight midpoint fetch (no full book)."""
    try:
        resp = await client.get(
            f"{CLOB}/midpoint",
            params={"token_id": token_id},
            timeout=3.0,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        return float(data.get("mid", 0.5))
    except Exception:
        return None


def detect_jump(old_mid: float, new_mid: float, threshold: float) -> bool:
    """Detect if midpoint moved more than threshold."""
    return abs(new_mid - old_mid) > threshold
