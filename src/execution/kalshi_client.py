"""Kalshi API v2 REST client (async httpx).

Public endpoints (markets, orderbook, series) — walang auth na kailangan.
Portfolio endpoints (balance, orders, fills, positions) — RSA-PSS signed.

Environments:
- prod : https://api.elections.kalshi.com/trade-api/v2
- demo : https://demo-api.kalshi.co/trade-api/v2   (practice money)

Ang base URL ay nasa settings ("kalshi.env") para madaling palitan kung
mag-rename ulit ang Kalshi ng host — huwag mag-hardcode sa ibang module.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Optional

import httpx

from src.execution.kalshi_auth import auth_headers, load_private_key

filelog = logging.getLogger("sportsbet.kalshi_client")

API_PREFIX = "/trade-api/v2"
PROD_BASE = "https://api.elections.kalshi.com"
DEMO_BASE = "https://demo-api.kalshi.co"

ENV_BASES = {"prod": PROD_BASE, "demo": DEMO_BASE}

_RETRY_STATUS = (429, 502, 503)
_MAX_RETRIES = 3


class KalshiError(Exception):
    """May problema sa Kalshi API call."""


class KalshiClient:
    """Thin async wrapper sa Kalshi REST API.

    Walang creds -> public endpoints lang ang gagana. May key_id + PEM ->
    kasama na ang portfolio endpoints.
    """

    def __init__(
        self,
        env: str = "prod",
        key_id: Optional[str] = None,
        private_key_pem: Optional[str] = None,
        base_url: Optional[str] = None,   # override para sa tests
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._base = (base_url or ENV_BASES.get(env, PROD_BASE)).rstrip("/")
        self._key_id = key_id
        self._key = load_private_key(private_key_pem) if private_key_pem else None
        self._client = client or httpx.AsyncClient(timeout=15)

    @property
    def has_auth(self) -> bool:
        return self._key_id is not None and self._key is not None

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------- plumbing

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
        auth: bool = False,
    ) -> dict:
        path = f"{API_PREFIX}{endpoint}"
        url = f"{self._base}{path}"
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            headers = {}
            if auth:
                if not self.has_auth:
                    raise KalshiError(
                        "Kalshi API credentials not configured (Settings)"
                    )
                # Bagong timestamp/signature KADA attempt — may expiry ang ts
                headers = auth_headers(self._key_id, self._key, method, path)
            try:
                resp = await self._client.request(
                    method, url, params=params, json=json_body, headers=headers
                )
            except httpx.HTTPError as e:
                last_exc = e
                await asyncio.sleep(1.5 * (attempt + 1))
                continue

            if resp.status_code in _RETRY_STATUS:
                filelog.warning(
                    "Kalshi %s %s -> %s (retry %d)",
                    method, endpoint, resp.status_code, attempt + 1,
                )
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            if resp.status_code >= 400:
                raise KalshiError(
                    f"Kalshi API {method} {endpoint} failed "
                    f"({resp.status_code}): {resp.text[:300]}"
                )
            if not resp.content:
                return {}
            return resp.json()

        raise KalshiError(
            f"Kalshi API {method} {endpoint} failed after retries: {last_exc}"
        )

    # ------------------------------------------------------ public endpoints

    async def exchange_status(self) -> dict:
        return await self._request("GET", "/exchange/status")

    async def get_series_list(self, category: str = "Sports") -> list[dict]:
        data = await self._request(
            "GET", "/series", params={"category": category}
        )
        return data.get("series", [])

    async def get_markets(
        self,
        series_ticker: Optional[str] = None,
        status: str = "open",
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> dict:
        """Raw markets response: {"markets": [...], "cursor": ...}."""
        params: dict[str, Any] = {"status": status, "limit": limit}
        if series_ticker:
            params["series_ticker"] = series_ticker
        if cursor:
            params["cursor"] = cursor
        return await self._request("GET", "/markets", params=params)

    async def get_market(self, ticker: str) -> dict:
        data = await self._request("GET", f"/markets/{ticker}")
        return data.get("market", data)

    async def get_orderbook(self, ticker: str, depth: int = 5) -> dict:
        data = await self._request(
            "GET", f"/markets/{ticker}/orderbook", params={"depth": depth}
        )
        # Bagong API: "orderbook_fp" na may dollar-string levels;
        # lumang API: "orderbook" na may integer-cent levels
        return data.get("orderbook_fp") or data.get("orderbook") or data

    # --------------------------------------------------- portfolio (signed)

    async def get_balance(self) -> float:
        """Available balance sa DOLLARS."""
        data = await self._request("GET", "/portfolio/balance", auth=True)
        return float(data.get("balance", 0)) / 100.0

    async def create_order(
        self,
        ticker: str,
        side: str,                 # 'yes' | 'no'
        count: int,
        price_cents: int,
        post_only: bool = True,
        client_order_id: Optional[str] = None,
    ) -> dict:
        """Limit BUY order sa napiling side. Ibinabalik ang order dict.

        Kalshi V2 orders API (POST /portfolio/events/orders) — lahat ay
        ini-express mula sa YES perspective:
          - BUY YES @ p¢  -> side="bid",  price = p/100
          - BUY NO  @ p¢  -> side="ask",  price = (100 - p)/100
            (ang pag-benta ng YES @ (100-p)¢ ay katumbas ng pagbili ng NO @ p¢)
        Kaya gumagana ito para sa parehong resting maker legs AT sa hedge:
        ang "ask" leg ay nagsa-scratch/flatten ng anumang hawak na YES.
        """
        side = side.lower()
        if side == "yes":
            v2_side = "bid"
            v2_price_cents = price_cents
        else:  # 'no' -> sell YES @ (100 - price)
            v2_side = "ask"
            v2_price_cents = 100 - price_cents
        body = {
            "ticker": ticker,
            "client_order_id": client_order_id or str(uuid.uuid4()),
            "side": v2_side,
            "count": f"{int(count):.2f}",           # FixedPointCount, hal. "10.00"
            "price": f"{v2_price_cents / 100:.2f}",  # FixedPointDollars, hal. "0.49"
            "time_in_force": "good_till_canceled",
            "self_trade_prevention_type": "taker_at_cross",
            "post_only": post_only,
        }
        data = await self._request(
            "POST", "/portfolio/events/orders", json_body=body, auth=True
        )
        return data.get("order", data)

    async def get_order(self, order_id: str) -> dict:
        data = await self._request(
            "GET", f"/portfolio/orders/{order_id}", auth=True
        )
        return data.get("order", data)

    async def cancel_order(self, order_id: str) -> dict:
        # V2 cancel endpoint (matches create endpoint family)
        return await self._request(
            "DELETE", f"/portfolio/events/orders/{order_id}", auth=True
        )

    async def get_resting_orders(
        self, ticker: Optional[str] = None
    ) -> list[dict]:
        """Lahat ng RESTING (open, di-pa-fill) orders sa account.

        Ginagamit sa reconcile-on-start: kung na-restart ang app habang
        may nakalatag na straddle, naiiwan ang mga order sa exchange pero
        nawawalan ng bantay ang app — dito sila makikita at makakansela."""
        params: dict[str, Any] = {"status": "resting"}
        if ticker:
            params["ticker"] = ticker
        data = await self._request(
            "GET", "/portfolio/orders", params=params, auth=True
        )
        return data.get("orders", [])

    async def get_fills(self, limit: int = 200,
                        ticker: Optional[str] = None) -> list[dict]:
        """Totoong fill history mula sa Kalshi (hindi ang lokal na tala).

        Ito ang ground truth: kung ano talaga ang nabili/naibenta, kailan,
        sa anong presyo, at magkano ang fee — kahit na-restart ang app o
        napalampas ng bot ang isang fill.
        """
        params: dict[str, Any] = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        data = await self._request(
            "GET", "/portfolio/fills", params=params, auth=True
        )
        return data.get("fills", [])

    async def get_positions(self, ticker: Optional[str] = None) -> list[dict]:
        params = {"ticker": ticker} if ticker else None
        data = await self._request(
            "GET", "/portfolio/positions", params=params, auth=True
        )
        return data.get("market_positions", [])

    async def get_settlements(self, limit: int = 200) -> list[dict]:
        """Settlement history — ground truth ng realized PnL.

        Ang natapos nang market ay INAALIS sa /portfolio/positions, kaya
        DITO lang makikita ang kinita/nalugi pagkatapos mag-settle. Bawat
        row ay may yes/no counts + costs at ang market_result."""
        data = await self._request(
            "GET", "/portfolio/settlements", params={"limit": limit},
            auth=True,
        )
        return data.get("settlements", [])


def _level_price_cents(price: object) -> int:
    """Level price -> cents. Bagong API: dollar string ("0.3800");
    lumang API: integer cents (38)."""
    if isinstance(price, str) and "." in price:
        return int(round(float(price) * 100))
    return int(float(price))  # type: ignore[arg-type]


def best_prices_from_orderbook(book: dict) -> dict[str, Optional[int]]:
    """Kunin ang best bid/ask ng YES at NO mula sa orderbook response.

    Ang Kalshi orderbook ay mga RESTING BUY orders per side:
    - bago: {"yes_dollars": [["0.3800", "45.00"], ...], "no_dollars": [...]}
    - luma: {"yes": [[38, 45], ...], "no": [...]}
    Ang implied ask ng isang side ay 100 - best_bid ng kabilang side
    (binary complement).
    """
    def best_bid(side: str) -> Optional[int]:
        levels = book.get(f"{side}_dollars") or book.get(side)
        if not levels:
            return None
        try:
            return max(_level_price_cents(lv[0]) for lv in levels)  # type: ignore[index]
        except (TypeError, ValueError, IndexError):
            return None

    yes_bid = best_bid("yes")
    no_bid = best_bid("no")
    return {
        "yes_bid": yes_bid,
        "no_bid": no_bid,
        "yes_ask": (100 - no_bid) if no_bid is not None else None,
        "no_ask": (100 - yes_bid) if yes_bid is not None else None,
    }
