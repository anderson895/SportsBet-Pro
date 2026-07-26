"""Kalshi LIVE executor — real single-side BUY/SELL via Kalshi API v2.

Mirrors ``polymarket.LiveExecutor`` (same ``buy``/``sell`` interface) so the
Kalshi engine can swap paper<->live transparently. The mean-reversion strategy
holds ONE directional position at a time:

- UP  side -> Kalshi ``yes`` contract (BTC above the pinned strike)
- DOWN side -> Kalshi ``no``  contract (BTC below the pinned strike)

``share_price`` is always in DOLLARS (0-1) sourced from the real order book;
Kalshi orders are placed in CENTS via ``KalshiClient.create_order`` with an
explicit ``action`` (buy to open, sell to close) on the held side.

Entry/exit both use limit orders. Entry is post-only (maker); exit crosses the
book to guarantee the fill (we never want to be stuck holding to settlement).
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Optional

from src.execution.kalshi_client import KalshiClient
from src.execution.kalshi_market import KalshiBtcMarket
from src.storage.db import ScopedDatabase
from src.strategy.mean_reversion import Position

filelog = logging.getLogger("sportsbet.kalshi_live")


def _to_cents(share_price: float) -> int:
    """Dollars (0-1) -> integer cents (1-99), clamped to a valid Kalshi price."""
    return max(1, min(99, round(share_price * 100)))


class KalshiLiveExecutor:
    """Real Kalshi trade execution; same interface as ``PaperExecutor``."""

    MODE = "LIVE"

    def __init__(self, db: ScopedDatabase, client: KalshiClient) -> None:
        self._db = db
        self._client = client
        self.position: Optional[Position] = None
        self.market: Optional[KalshiBtcMarket] = None

    def set_market(self, market: KalshiBtcMarket) -> None:
        self.market = market

    async def buy(
        self, market: str, side: str, share_price: float, usdc: float
    ) -> Position:
        assert self.market is not None, "no market resolved yet"
        cents = _to_cents(share_price)
        # count = whole contracts affordable at this price (each pays $1)
        count = int(usdc / (cents / 100.0))
        if count < 1:
            raise ValueError(
                f"Risk ${usdc:.2f} too small for one {cents}¢ contract"
            )
        order = await self._client.create_order(
            self.market.ticker, self.market.side_key(side), count, cents,
            action="buy", post_only=True,
        )
        order_id = str(order.get("order_id", ""))
        self.position = Position(
            side=side,
            entry_price=cents / 100.0,
            shares=float(count),
            entry_ts=dt.datetime.now(dt.timezone.utc),
        )
        self._db.add_trade(
            market=market, side=side, action="BUY",
            price=cents / 100.0, size=count * cents / 100.0, status="OPEN",
        )
        self._db.save_open_position(
            self.MODE, market, side, cents / 100.0, float(count),
            self.position.entry_ts,
        )
        self._db.add_log("TRADE", f"[LIVE] Kalshi order posted: {order_id}")
        return self.position

    async def sell(self, market: str, share_price: float) -> float:
        assert self.position is not None, "no open position"
        assert self.market is not None
        pos = self.position
        cents = _to_cents(share_price)
        count = int(pos.shares)
        # Close by SELLING the same side we hold at the current bid; cross the
        # book (post_only=False) so the exit fills — never hold to settlement.
        order = await self._client.create_order(
            self.market.ticker, self.market.side_key(pos.side), count, cents,
            action="sell", post_only=False,
        )
        order_id = str(order.get("order_id", ""))
        proceeds = pos.shares * (cents / 100.0)
        pnl = proceeds - pos.shares * pos.entry_price
        self._db.add_trade(
            market=market, side=pos.side, action="SELL",
            price=cents / 100.0, size=proceeds, status="OPEN", pnl=pnl,
        )
        self._db.add_log("TRADE", f"[LIVE] Kalshi close posted: {order_id}")
        self.position = None
        self._db.clear_open_position()
        return pnl

    async def get_balance(self) -> Optional[float]:
        return await self._client.get_balance()
