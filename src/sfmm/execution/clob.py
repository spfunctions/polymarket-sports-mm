"""
Polymarket CLOB execution — wraps py-clob-client for order management.

Handles: place, cancel, cancel_all, get open orders, get trades.
All methods are sync (py-clob-client is sync) but designed to be called from async context.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sfmm.core.types import Fill, OrderState, Side

log = logging.getLogger(__name__)


@dataclass
class ClobConfig:
    host: str = "https://clob.polymarket.com"
    private_key: str = ""
    chain_id: int = 137  # Polygon
    api_key: str = ""
    api_secret: str = ""
    api_passphrase: str = ""


class ClobExecutor:
    """
    Wraps py-clob-client. Lazy-init to avoid import errors when credentials aren't set.
    """

    def __init__(self, config: ClobConfig, dry_run: bool = False):
        self.config = config
        self.dry_run = dry_run
        self._client = None

    def _ensure_client(self):
        if self._client is not None:
            return
        if self.dry_run:
            return

        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds
        except ImportError:
            raise RuntimeError(
                "py-clob-client not installed. Run: pip install py-clob-client"
            )

        if not self.config.private_key:
            raise RuntimeError("POLYMARKET_PRIVATE_KEY not set")

        creds = ApiCreds(
            api_key=self.config.api_key,
            api_secret=self.config.api_secret,
            api_passphrase=self.config.api_passphrase,
        )

        self._client = ClobClient(
            host=self.config.host,
            key=self.config.private_key,
            chain_id=self.config.chain_id,
            creds=creds,
        )
        log.info("CLOB client initialized (chain_id=%d)", self.config.chain_id)

    def place_order(
        self,
        token_id: str,
        price: float,
        size: int,
        side: Side,
    ) -> str | None:
        """
        Place a GTC limit order. Returns order_id or None.
        """
        if self.dry_run:
            log.info(
                "[DRY] place %s %d @ %.2f on %s",
                side.value, size, price, token_id[:16],
            )
            return f"dry-{token_id[:8]}-{side.value}-{price}"

        self._ensure_client()

        try:
            from py_clob_client.clob_types import OrderArgs, OrderType

            order = self._client.create_order(
                OrderArgs(
                    token_id=token_id,
                    price=price,
                    size=size,
                    side=side.value,
                )
            )
            resp = self._client.post_order(order, OrderType.GTC)
            order_id = resp.get("orderID", "")
            log.info("Placed %s %d @ %.2f → %s", side.value, size, price, order_id)
            return order_id

        except Exception as e:
            log.error("place_order failed: %s", e)
            return None

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a single order."""
        if self.dry_run:
            log.info("[DRY] cancel %s", order_id)
            return True

        self._ensure_client()
        try:
            self._client.cancel(order_id=order_id)
            log.info("Cancelled %s", order_id)
            return True
        except Exception as e:
            log.error("cancel_order failed for %s: %s", order_id, e)
            return False

    def cancel_all(self) -> bool:
        """Cancel all open orders."""
        if self.dry_run:
            log.info("[DRY] cancel_all")
            return True

        self._ensure_client()
        try:
            self._client.cancel_all()
            log.info("Cancelled all orders")
            return True
        except Exception as e:
            log.error("cancel_all failed: %s", e)
            return False

    def get_open_orders(self, market: str = "") -> list[dict]:
        """Get open orders, optionally filtered by market."""
        if self.dry_run:
            return []

        self._ensure_client()
        try:
            params = {}
            if market:
                params["market"] = market
            return self._client.get_orders(**params) or []
        except Exception as e:
            log.error("get_open_orders failed: %s", e)
            return []
