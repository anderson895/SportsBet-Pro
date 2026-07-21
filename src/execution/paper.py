"""Paper trading executor — simulated fills, WALANG totoong pera.

Dahil hindi naa-access ang Polymarket order book (blocked sa network na ito),
ini-estimate natin ang share price mula sa BTC stretch gamit ang simpleng
linear model na tugma sa reference sa details.txt:

    stretch 0.0%  -> OTM share ~ 0.50 (50/50 ang laban)
    stretch 2.0%  -> OTM share ~ 0.20 (reference: "around 20c")
    retrace 0.6%  -> OTM share ~ 0.41 (reference: "45c to 50c")

    price = clamp(0.50 - 0.15 * |stretch_pct|, 0.03, 0.50)

IMPORTANTE: Estimate lang ito para sa strategy validation. Sa live mode,
pinapalitan ito ng totoong order book prices mula sa CLOB.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from src.storage.db import ScopedDatabase
from src.strategy.mean_reversion import Position

PRICE_AT_ZERO = 0.50
PRICE_SLOPE_PER_PCT = 0.15
PRICE_FLOOR = 0.03
PRICE_CEIL = 0.50


def estimate_otm_share_price(stretch_pct: float, scale: float = 1.0) -> float:
    """Estimated na presyo ng out-of-the-money share given ang BTC stretch.

    Ang `scale` ay ang stretch_scale ng timeframe (1.0 = daily) — sa mas
    maikling periods, mas maliit na stretch ang katumbas ng parehong
    share-price move (hal. +0.3% sa 1h market ~ +1.5% sa daily).
    """
    price = PRICE_AT_ZERO - PRICE_SLOPE_PER_PCT * abs(stretch_pct) / scale
    return max(PRICE_FLOOR, min(PRICE_CEIL, price))


def position_share_price(
    stretch_pct: float, side: str, scale: float = 1.0
) -> float:
    """Presyo ng hawak nating side given ang kasalukuyang stretch.

    Kung ang stretch ay papunta LABAN sa side natin (e.g., hawak natin DOWN
    tapos naka-+2% pa rin ang BTC), mura ang share natin. Kung bumalik na
    ang presyo PABOR sa atin (nag-cross sa kabila ng open), mahal na ito.
    """
    otm = estimate_otm_share_price(stretch_pct, scale)
    against_us = (side == "DOWN" and stretch_pct > 0) or (
        side == "UP" and stretch_pct < 0
    )
    return otm if against_us else 1.0 - otm


class PaperExecutor:
    """Simulated trade execution; nire-record ang lahat sa SQLite."""

    MODE = "PAPER"

    def __init__(self, db: ScopedDatabase) -> None:
        self._db = db
        self.position: Optional[Position] = None

    def buy(self, market: str, side: str, share_price: float, usdc: float) -> Position:
        shares = usdc / share_price
        self.position = Position(
            side=side,
            entry_price=share_price,
            shares=shares,
            entry_ts=dt.datetime.now(dt.timezone.utc),
        )
        self._db.add_trade(
            market=market,
            side=side,
            action="BUY",
            price=share_price,
            size=usdc,
            status="FILLED",
        )
        # I-persist para ma-restore kapag na-restart ang app mid-position
        self._db.save_open_position(
            self.MODE, market, side, share_price, shares, self.position.entry_ts
        )
        return self.position

    def sell(self, market: str, share_price: float) -> float:
        """Isara ang position; ibalik ang realized PnL (USDC)."""
        assert self.position is not None, "no open position"
        pos = self.position
        proceeds = pos.shares * share_price
        cost = pos.shares * pos.entry_price
        pnl = proceeds - cost
        self._db.add_trade(
            market=market,
            side=pos.side,
            action="SELL",
            price=share_price,
            size=proceeds,
            status="FILLED",
            pnl=pnl,
        )
        self.position = None
        self._db.clear_open_position()
        return pnl
