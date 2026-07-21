"""Coinbase read-only BTC spot price — para sa premium check vs Binance.

Public API, walang key na kailangan. Kada 60 segundo ang refresh —
sapat na ito dahil ang premium ay slow-moving signal, hindi tick data.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx

filelog = logging.getLogger("sportsbet.coinbase")

COINBASE_SPOT_URL = "https://api.coinbase.com/v2/prices/BTC-USD/spot"
REFRESH_SECONDS = 60


class CoinbaseFeed:
    def __init__(self) -> None:
        self.last_price: Optional[float] = None
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="coinbase-feed")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self.last_price = None

    async def _run(self) -> None:
        async with httpx.AsyncClient(timeout=10) as client:
            while True:
                try:
                    resp = await client.get(COINBASE_SPOT_URL)
                    resp.raise_for_status()
                    self.last_price = float(resp.json()["data"]["amount"])
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    filelog.warning("Coinbase fetch failed: %s", e)
                    self.last_price = None  # stale data ay mas masama sa mali
                await asyncio.sleep(REFRESH_SECONDS)
