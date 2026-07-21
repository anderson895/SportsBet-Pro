"""Kalshi LIVE executor — totoong orders via Kalshi API v2.

Kapareho ng interface ng KalshiPaperExecutor para direktang mapalitan
sa engine. Lahat ng orders ay limit orders:
- entry: post_only=True (maker lang — kritikal sa strategy economics;
  kapag mag-co-cross agad, ire-reject ng server, hindi tayo magta-taker)
- hedge: post_only=False sa max price (sadyang tatawid sa book para
  ma-lock ang scratch)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from src.execution.kalshi_client import KalshiClient, KalshiError

filelog = logging.getLogger("sportsbet.kalshi_live")


class KalshiLiveExecutor:
    MODE = "LIVE"

    def __init__(self, client: KalshiClient) -> None:
        self._client = client
        self._order_ids: dict[str, str] = {}  # side -> order_id
        self.ticker: Optional[str] = None

    # ------------------------------------------------------------------ API

    async def place_straddle(
        self, ticker: str, entry_cents: int, count: int
    ) -> dict[str, str]:
        """Dalawang post-only resting BUY: YES @ entry at NO @ entry.

        Kapag pumalya ang PANGALAWANG order, kinakansela agad ang una —
        hindi tayo maiiwan na kalahati lang ang straddle.
        """
        self.ticker = ticker
        yes_order = await self._client.create_order(
            ticker, "yes", count, entry_cents, post_only=True
        )
        yes_id = str(yes_order.get("order_id", ""))
        try:
            no_order = await self._client.create_order(
                ticker, "no", count, entry_cents, post_only=True
            )
        except Exception:
            filelog.exception("NO leg failed — cancelling resting YES leg:")
            await self._safe_cancel(yes_id)
            raise
        self._order_ids = {
            "YES": yes_id,
            "NO": str(no_order.get("order_id", "")),
        }
        return dict(self._order_ids)

    async def get_fills(self, ticker: str) -> tuple[int, int]:
        """(yes_filled, no_filled) mula sa order statuses."""
        counts = {}
        for side in ("YES", "NO"):
            order_id = self._order_ids.get(side)
            if not order_id:
                counts[side] = 0
                continue
            order = await self._client.get_order(order_id)
            # Kalshi order: fill_count o (initial_count - remaining_count)
            fill = order.get("fill_count")
            if fill is None:
                initial = order.get("initial_count", order.get("count", 0))
                remaining = order.get("remaining_count", initial)
                fill = int(initial) - int(remaining)
            counts[side] = int(fill)
        return counts["YES"], counts["NO"]

    async def cancel(self, ticker: str, side: str) -> None:
        order_id = self._order_ids.get(side)
        if order_id:
            await self._safe_cancel(order_id)

    async def cancel_all(self, ticker: str) -> None:
        for side in ("YES", "NO"):
            await self.cancel(ticker, side)

    async def hedge(
        self, ticker: str, side: str, max_price_cents: int, count: int,
        prices: Optional[dict] = None,
    ) -> int:
        """Aggressive limit BUY ng lagging side sa max price (taker OK).

        Ibinabalik ang na-fill na count pagkatapos ng maikling hintay.
        """
        try:
            order = await self._client.create_order(
                ticker, side.lower(), count, max_price_cents, post_only=False
            )
        except KalshiError as e:
            filelog.warning("Hedge order rejected: %s", e)
            return 0
        order_id = str(order.get("order_id", ""))
        self._order_ids[side] = order_id
        await asyncio.sleep(1.0)  # bigyan ng saglit para mag-match
        status = await self._client.get_order(order_id)
        fill = status.get("fill_count")
        if fill is None:
            initial = status.get("initial_count", count)
            remaining = status.get("remaining_count", initial)
            fill = int(initial) - int(remaining)
        return int(fill)

    async def get_balance(self) -> Optional[float]:
        return await self._client.get_balance()

    # -------------------------------------------------------------- helpers

    async def _safe_cancel(self, order_id: str) -> None:
        try:
            await self._client.cancel_order(order_id)
        except Exception:
            # Baka na-fill na o kanselado na habang nasa flight — ayos lang
            filelog.info("Cancel skipped (order %s already done?)", order_id)
