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


def _count(order: dict, *keys: str) -> Optional[float]:
    """Unang key na may halaga, bilang float. Ang 2026 Kalshi API ay
    nagbabalik ng fixed-point STRINGS ("8.00"), hindi integers."""
    for key in keys:
        raw = order.get(key)
        if raw not in (None, ""):
            try:
                return float(raw)
            except (TypeError, ValueError):
                continue
    return None


def filled_count(order: dict) -> int:
    """Ilang contract na ang na-fill sa order na ito.

    KRITIKAL: ang 2026 API ay gumagamit ng `*_fp` na fixed-point strings
    (fill_count_fp="8.00"). Ang lumang integer na field (fill_count) ay
    wala na — kapag iyon lang ang hinanap, LAGING 0 ang mababasa, kaya
    hindi makikita ng bot ang mga fill at hindi kikilos ang Hedge
    Sentinel. Tumatanggap ito ng luma AT bagong format.
    """
    fill = _count(order, "fill_count_fp", "fill_count")
    if fill is not None:
        return int(fill)
    initial = _count(order, "initial_count_fp", "initial_count", "count")
    remaining = _count(order, "remaining_count_fp", "remaining_count")
    if initial is None:
        return 0
    return int(initial - (remaining if remaining is not None else initial))


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
        if not self._order_ids:
            # Nawala ang order IDs (hal. na-restart ang app) — kunin ang
            # fills DIREKTA sa ticker para masubaybayan pa rin ang cycle.
            return await self._fills_by_ticker(ticker)
        counts = {}
        for side in ("YES", "NO"):
            order_id = self._order_ids.get(side)
            if not order_id:
                counts[side] = 0
                continue
            order = await self._client.get_order(order_id)
            counts[side] = filled_count(order)
        return counts["YES"], counts["NO"]

    async def _fills_by_ticker(self, ticker: str) -> tuple[int, int]:
        """(yes, no) na na-fill sa market na ito, ayon sa fill history.

        Fallback kapag wala nang order IDs sa memory. Tandaan: kabuuan ito
        ng LAHAT ng fills sa ticker — tama ito dahil isang cycle lang ang
        pinapayagan kada ticker (`_traded_tickers`).
        """
        try:
            fills = await self._client.get_fills(limit=200, ticker=ticker)
        except Exception as e:
            filelog.warning("Fill lookup by ticker failed: %s", e)
            return 0, 0
        yes = no = 0.0
        for f in fills:
            count = _count(f, "count_fp", "count") or 0.0
            if str(f.get("outcome_side", "")).lower() == "yes":
                yes += count
            else:
                no += count
        return int(yes), int(no)

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
        return filled_count(status)

    async def get_balance(self) -> Optional[float]:
        return await self._client.get_balance()

    # -------------------------------------------------------------- helpers

    async def _safe_cancel(self, order_id: str) -> None:
        try:
            await self._client.cancel_order(order_id)
        except Exception:
            # Baka na-fill na o kanselado na habang nasa flight — ayos lang
            filelog.info("Cancel skipped (order %s already done?)", order_id)
