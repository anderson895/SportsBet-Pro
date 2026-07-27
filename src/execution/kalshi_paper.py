"""Kalshi PAPER executor — simulated fills, WALANG totoong pera.

Gumagamit ito ng TOTOONG public Kalshi market data (orderbook) para
makatotohanan ang simulation:

- Ang resting BUY YES @ 49¢ natin ay "nafi-fill" kapag ang yes_ask ay
  bumaba sa <= 49¢ (ibig sabihin may nagbebenta sa presyo natin) nang
  DALAWANG sunod na poll — konserbatibo, para hindi tayo maloko ng
  panandaliang flicker ng book.
- Ang hedge taker order ay nafi-fill agad kung ang ask <= max price.

Ang engine ang nagpapasa ng best prices kada poll via `on_book()`;
kaya injectable din ito ng canned snapshots para sa unit tests.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class _SimOrder:
    side: str                 # 'YES' | 'NO'
    price_cents: int
    count: int
    filled: int = 0
    cancelled: bool = False
    # persistence rule: kailangang makita ang fillable ask nang 2 poll
    _seen_fillable: bool = False


class KalshiPaperExecutor:
    """Simulated straddle order management (isang market kada pagkakataon)."""

    MODE = "PAPER"

    def __init__(self) -> None:
        self._orders: dict[str, _SimOrder] = {}  # side -> order
        self.ticker: Optional[str] = None

    # ------------------------------------------------------------------ API

    async def place_straddle(
        self, ticker: str, entry_cents: int, count: int
    ) -> dict[str, str]:
        """Ilagay ang dalawang simulated resting orders."""
        self.ticker = ticker
        self._orders = {
            "YES": _SimOrder("YES", entry_cents, count),
            "NO": _SimOrder("NO", entry_cents, count),
        }
        return {"YES": f"paper-yes-{ticker}", "NO": f"paper-no-{ticker}"}

    def on_book(self, prices: dict) -> None:
        """Bagong orderbook snapshot — i-update ang simulated fills.

        `prices` = {"yes_ask": int|None, "no_ask": int|None, ...} sa cents.
        Fill rule: ask <= ang resting bid natin nang 2 sunod na poll.
        """
        for side, ask_key in (("YES", "yes_ask"), ("NO", "no_ask")):
            order = self._orders.get(side)
            if order is None or order.cancelled or order.filled >= order.count:
                continue
            ask = prices.get(ask_key)
            fillable = ask is not None and ask <= order.price_cents
            if fillable and order._seen_fillable:
                order.filled = order.count  # buong fill sa ika-2 sighting
            order._seen_fillable = fillable

    async def get_fills(self, ticker: str) -> tuple[int, int]:
        yes = self._orders.get("YES")
        no = self._orders.get("NO")
        return (yes.filled if yes else 0, no.filled if no else 0)

    async def cancel(self, ticker: str, side: str) -> None:
        order = self._orders.get(side)
        if order is not None:
            order.cancelled = True

    async def cancel_all(self, ticker: str) -> None:
        for order in self._orders.values():
            order.cancelled = True

    async def hedge(
        self, ticker: str, side: str, max_price_cents: int, count: int,
        prices: Optional[dict] = None,
    ) -> int:
        """Simulated taker BUY ng lagging side; fill kung abot ang ask.

        Ibinabalik ang nadagdag na filled count (0 kung hindi umabot).
        """
        ask_key = "yes_ask" if side == "YES" else "no_ask"
        ask = (prices or {}).get(ask_key)
        if ask is None or ask > max_price_cents:
            return 0
        order = self._orders.get(side)
        if order is None:
            order = _SimOrder(side, ask, count)
            self._orders[side] = order
        need = count - order.filled
        order.filled += max(need, 0)
        order.price_cents = ask  # na-fill sa ask (taker)
        return max(need, 0)

    async def get_balance(self) -> Optional[float]:
        """Walang totoong balance sa paper — ang dashboard ang nagkukuwenta
        mula sa paper_start + total_pnl (tulad ng poly paper pattern)."""
        return None
