"""
SF intent bridge — fire-and-forget reporting to SimpleFunctions API.
Never blocks the quoting loop.
"""

from __future__ import annotations

import logging

import httpx

from sfmm.core.types import Game, Fill

log = logging.getLogger(__name__)


class SFBridge:
    def __init__(self, api_url: str, api_key: str):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.enabled = bool(api_key)

    async def on_game_start(self, game: Game) -> str | None:
        """Create an intent for a game. Returns intent_id."""
        if not self.enabled:
            return None

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self.api_url}/api/intents",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "action": "buy",
                        "venue": "polymarket",
                        "marketId": game.markets[0].condition_id if game.markets else "",
                        "marketTitle": game.title,
                        "direction": "yes",
                        "targetQuantity": 0,
                        "source": "agent",
                        "rationale": f"MM: {game.title} ({game.sport.value})",
                        "autoExecute": True,
                    },
                    timeout=10.0,
                )
                data = resp.json()
                intent_id = data.get("id")
                log.info("SF intent created: %s", intent_id)
                return intent_id
        except Exception as e:
            log.warning("SF bridge on_game_start failed: %s", e)
            return None

    async def on_fill(self, intent_id: str, fill: Fill):
        if not self.enabled or not intent_id:
            return
        try:
            async with httpx.AsyncClient() as client:
                await client.patch(
                    f"{self.api_url}/api/intents/{intent_id}",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "fill": {
                            "orderId": fill.order_id,
                            "fillQuantity": fill.size,
                            "fillPrice": int(fill.price * 100),
                            "fillCostCents": int(fill.size * fill.price * 100),
                        }
                    },
                    timeout=10.0,
                )
        except Exception as e:
            log.warning("SF bridge on_fill failed: %s", e)

    async def on_game_end(self, intent_id: str):
        if not self.enabled or not intent_id:
            return
        try:
            async with httpx.AsyncClient() as client:
                await client.patch(
                    f"{self.api_url}/api/intents/{intent_id}",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"status": "filled"},
                    timeout=10.0,
                )
        except Exception as e:
            log.warning("SF bridge on_game_end failed: %s", e)
