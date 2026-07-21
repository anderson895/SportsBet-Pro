"""Periodic connection checks: Internet, Binance, Polymarket, Kalshi.

Bawat 15 segundo, chine-check kung reachable ang bawat service,
tapos ini-report sa UI via callback.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

import httpx

filelog = logging.getLogger("sportsbet.status")

CHECK_INTERVAL = 15  # seconds

INTERNET_URL = "https://1.1.1.1"                       # Cloudflare - internet check
BINANCE_URL = "https://api.binance.com/api/v3/ping"    # Binance REST ping
POLYMARKET_URL = "https://clob.polymarket.com/time"    # Polymarket CLOB server time
KALSHI_URL = "https://api.elections.kalshi.com/trade-api/v2/exchange/status"

StatusCallback = Callable[[str, bool], None]  # (service_name, is_up)


class ConnectionMonitor:
    SERVICES = {
        "internet": INTERNET_URL,
        "binance": BINANCE_URL,
        "polymarket": POLYMARKET_URL,
        "kalshi": KALSHI_URL,
    }

    def __init__(self, on_status: StatusCallback) -> None:
        self._on_status = on_status
        self._task: Optional[asyncio.Task] = None
        self._last_state: dict[str, bool] = {}

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="conn-monitor")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        async with httpx.AsyncClient(timeout=8, verify=True) as client:
            while True:
                await asyncio.gather(
                    *(self._check(client, name, url) for name, url in self.SERVICES.items())
                )
                await asyncio.sleep(CHECK_INTERVAL)

    async def _check(self, client: httpx.AsyncClient, name: str, url: str) -> None:
        error: Optional[BaseException] = None
        try:
            resp = await client.get(url)
            up = resp.status_code < 500
            detail = f"HTTP {resp.status_code}"
        except Exception as e:
            up = False
            error = e
            detail = f"{type(e).__name__}: {e}"

        # I-log lang kapag NAGBAGO ang estado — kasama ang eksaktong dahilan,
        # para makita sa app.log kung bakit "Disconnected" ang isang service
        if self._last_state.get(name) != up:
            self._last_state[name] = up
            if up:
                filelog.info("%s: CONNECTED (%s)", name, detail)
            else:
                filelog.warning("%s: DISCONNECTED — %s (url: %s)", name, detail, url)
                if error is not None:
                    filelog.debug("%s traceback:", name, exc_info=error)

        self._on_status(name, up)
