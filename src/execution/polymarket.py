"""Live Polymarket execution — totoong CLOB orders via py-clob-client.

Auth: ang API creds ay dine-derive mula sa private key (walang API key
dashboard sa Polymarket).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Optional
from zoneinfo import ZoneInfo  # stdlib; sa Windows kailangan ng tzdata pkg

import httpx

# CLOB V2 (2026-04-28 migration): ang lumang py-clob-client ay tinanggihan
# na ng server ("invalid order version") — py-clob-client-v2 na ang gamit
from py_clob_client_v2 import (
    AssetType,
    BalanceAllowanceParams,
    ClobClient,
    OrderArgs,
    Side,
)

from src.storage.db import ScopedDatabase
from src.strategy.mean_reversion import Position

CLOB_HOST = "https://clob.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"
POLYGON_CHAIN_ID = 137
USDC_DECIMALS = 6


class _ExpectedAuthNoiseFilter(logging.Filter):
    """Itago ang inaasahang 400 sa /auth/api-key.

    Ang create_or_derive_api_key ay SINASADYANG sumusubok munang gumawa
    ng bagong key; kapag mayroon na, 400 ("Could not create api key")
    tapos nagde-derive na lang ng existing. Normal na fallback iyon —
    pero nilo-log ito ng SDK bilang ERROR at nakakagulat sa app.log.
    Ang ibang totoong errors (hal. order rejections) ay dumadaan pa rin.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return "Could not create api key" not in record.getMessage()


logging.getLogger("py_clob_client_v2.http_helpers.helpers").addFilter(
    _ExpectedAuthNoiseFilter()
)


class PolymarketError(Exception):
    """May problema sa Polymarket API call."""


class DailyBtcMarket:
    """Resolved na daily BTC Up/Down market para sa isang araw."""

    def __init__(self, question: str, token_up: str, token_down: str) -> None:
        self.question = question
        self.token_up = token_up
        self.token_down = token_down

    def token_for(self, side: str) -> str:
        return self.token_up if side == "UP" else self.token_down


class PolymarketClient:
    """Wrapper sa py-clob-client + Gamma API. Lahat sync (requests-based)."""

    def __init__(
        self,
        private_key: str,
        funder: str,
        signature_type: int = 1,  # 1 = Magic, 2 = MetaMask, 3 = Deposit Wallet
        host: str = CLOB_HOST,
        clob_client: Optional[ClobClient] = None,  # injectable para sa tests
    ) -> None:
        self._sig_type = signature_type
        self._client = clob_client or ClobClient(
            host=host,
            key=private_key,
            chain_id=POLYGON_CHAIN_ID,
            signature_type=signature_type,
            funder=funder,
        )
        self._connected = False

    def connect(self) -> None:
        """I-derive ang L2 API creds mula sa private key."""
        creds = self._client.create_or_derive_api_key()
        self._client.set_api_creds(creds)
        self._connected = True

    # ------------------------------------------------------------- balance

    def get_usdc_balance(self) -> float:
        """Totoong USDC balance (collateral) sa Polymarket.

        Sa Deposit Wallet accounts (sig type 3), KAILANGANG ipasa ang
        signature_type sa balance request — kung hindi, sa lumang-style
        na account hahanapin ng server ang pondo at 0.00 ang babalik.
        Sa sig 1/2, default (-1) pa rin: hinahayaang mag-resolve ang
        server base sa account mapping (ito ang gumagana sa Magic).
        """
        if self._sig_type == 3:
            params = BalanceAllowanceParams(
                asset_type=AssetType.COLLATERAL, signature_type=3
            )
        else:
            params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        resp = self._client.get_balance_allowance(params)
        raw = resp.get("balance", "0") if isinstance(resp, dict) else "0"
        return int(raw) / 10**USDC_DECIMALS

    # ------------------------------------------------------------- pricing

    def get_best_prices(self, token_id: str) -> tuple[Optional[float], Optional[float]]:
        """(best_bid, best_ask) mula sa order book; None kung walang liquidity.

        Sa CLOB V2, ang order book ay dict na (`{"bids": [{"price": ...}]}`)
        imbes na object — parehong sinusuportahan dito.
        """
        book = self._client.get_order_book(token_id)
        if isinstance(book, dict):
            bids, asks = book.get("bids") or [], book.get("asks") or []
        else:  # V1-style object (ginagamit pa ng test mocks)
            bids, asks = book.bids, book.asks

        def px(level: object) -> float:
            return float(level["price"] if isinstance(level, dict)
                         else level.price)

        best_bid = max((px(b) for b in bids), default=None)
        best_ask = min((px(a) for a in asks), default=None)
        return best_bid, best_ask

    # -------------------------------------------------------------- orders

    def buy_limit(self, token_id: str, price: float, usdc: float) -> str:
        """Limit BUY; size = shares (usdc / price). Ibinabalik ang order ID."""
        shares = round(usdc / price, 2)
        resp = self._client.create_and_post_order(
            OrderArgs(token_id=token_id, price=price, size=shares,
                      side=Side.BUY)
        )
        return _order_id(resp)

    def sell_limit(self, token_id: str, price: float, shares: float) -> str:
        resp = self._client.create_and_post_order(
            OrderArgs(token_id=token_id, price=price, size=round(shares, 2),
                      side=Side.SELL)
        )
        return _order_id(resp)

    def cancel_all(self) -> None:
        self._client.cancel_all()

    def filled_size(self, order_id: str) -> float:
        """Matched (filled) share count of a resting order. 0 if unknown.

        Used by the box-arbitrage executor to track single-sided fills. CLOB V2
        returns `size_matched` on the order; tolerant of dict/object shapes.
        """
        if not order_id:
            return 0.0
        try:
            o = self._client.get_order(order_id)
        except Exception:
            return 0.0
        if isinstance(o, dict):
            return float(o.get("size_matched") or o.get("sizeMatched") or 0)
        return float(getattr(o, "size_matched", 0) or 0)


def _order_id(resp: object) -> str:
    if isinstance(resp, dict):
        if not resp.get("success", True):
            raise PolymarketError(f"Order rejected: {resp.get('errorMsg', resp)}")
        return str(resp.get("orderID", ""))
    return ""


# ------------------------------------------------------------ market lookup


def build_market_slugs(timeframe: str, now_utc: dt.datetime) -> list[str]:
    """Slug candidates ng KASALUKUYANG BTC Up/Down market ng timeframe.

    Mga pattern — VERIFIED sa totoong Gamma API (2026-07-11/12):
    - daily : 'bitcoin-up-or-down-on-july-12-2026' — naka-pangalan sa araw
              ng SETTLEMENT (tanghali ET); ang period ay tanghali-ET ->
              tanghali-ET, kaya pagkalampas ng 12PM ET ay BUKAS na ang
              petsa ng aktibong market (legacy fallback: walang year)
    - 15m/4h: 'btc-updown-15m-<period_start_unix>' (UTC-aligned)
    - 1h    : 'bitcoin-up-or-down-july-13-2026-9am-et' (naka-pangalan sa
              ET hour — kailangan ng America/New_York conversion, may DST)
    """
    if timeframe == "daily":
        et = now_utc.astimezone(ZoneInfo("America/New_York"))
        settle = et.date() if et.hour < 12 else et.date() + dt.timedelta(days=1)
        base = (f"bitcoin-up-or-down-on-"
                f"{settle.strftime('%B').lower()}-{settle.day}")
        return [f"{base}-{settle.year}", base]  # bago muna, tapos legacy

    if timeframe in ("15m", "4h"):
        secs = {"15m": 900, "4h": 14400}[timeframe]
        ts = now_utc.timestamp()
        start = int(ts - ts % secs)
        return [f"btc-updown-{timeframe}-{start}"]

    if timeframe == "1h":
        et = now_utc.astimezone(ZoneInfo("America/New_York"))
        hour12 = et.strftime("%I").lstrip("0")  # '9', '12' — walang zero
        ampm = et.strftime("%p").lower()        # 'am' / 'pm'
        return [
            f"bitcoin-up-or-down-{et.strftime('%B').lower()}-{et.day}-"
            f"{et.year}-{hour12}{ampm}-et"
        ]

    raise PolymarketError(f"Unknown market timeframe: {timeframe!r}")


def find_btc_market(
    timeframe: str,
    now_utc: dt.datetime,
    http_client: Optional[httpx.Client] = None,
) -> DailyBtcMarket:
    """Hanapin ang kasalukuyang BTC Up/Down market ng napiling timeframe."""
    slugs = build_market_slugs(timeframe, now_utc)
    client = http_client or httpx.Client(timeout=15)
    markets: list = []
    try:
        for slug in slugs:
            resp = client.get(f"{GAMMA_API}/markets", params={"slug": slug})
            resp.raise_for_status()
            markets = resp.json()
            if markets:
                break
    finally:
        if http_client is None:
            client.close()

    if not markets:
        raise PolymarketError(
            f"No market found for slugs {slugs}"
        )

    market = markets[0]
    outcomes = _as_list(market.get("outcomes", "[]"))
    token_ids = _as_list(market.get("clobTokenIds", "[]"))
    if len(outcomes) != 2 or len(token_ids) != 2:
        raise PolymarketError(f"Unexpected market shape: {market.get('question')}")

    # Ang outcomes ay maaaring ["Up","Down"] o ["Down","Up"] — i-map nang tama
    mapping = {o.strip().upper(): t for o, t in zip(outcomes, token_ids)}
    if "UP" not in mapping or "DOWN" not in mapping:
        raise PolymarketError(f"Unexpected outcomes: {outcomes}")

    return DailyBtcMarket(
        question=market.get("question", slug),
        token_up=mapping["UP"],
        token_down=mapping["DOWN"],
    )


def find_daily_btc_market(
    date_utc: dt.date, http_client: Optional[httpx.Client] = None
) -> DailyBtcMarket:
    """Back-compat wrapper: daily market ng ibinigay na UTC date."""
    now_utc = dt.datetime(
        date_utc.year, date_utc.month, date_utc.day, tzinfo=dt.timezone.utc
    )
    return find_btc_market("daily", now_utc, http_client=http_client)


def _as_list(value: object) -> list:
    """Ang Gamma API ay nagbabalik ng stringified JSON arrays minsan."""
    if isinstance(value, str):
        return json.loads(value)
    return list(value)  # type: ignore[arg-type]


# ------------------------------------------------------------ live executor


class LiveExecutor:
    """Totoong trade execution sa Polymarket CLOB.

    Kapareho ng interface ng PaperExecutor para direktang mapalitan
    sa engine. Ang share_price na ipinapasa dito ay dapat galing sa
    TOTOONG order book (get_best_prices), hindi sa estimate.
    """

    MODE = "LIVE"

    def __init__(self, db: ScopedDatabase, client: PolymarketClient) -> None:
        self._db = db
        self._client = client
        self.position: Optional[Position] = None
        self.market: Optional[DailyBtcMarket] = None

    def set_market(self, market: DailyBtcMarket) -> None:
        self.market = market

    def buy(self, market: str, side: str, share_price: float, usdc: float) -> Position:
        assert self.market is not None, "no market resolved yet"
        token = self.market.token_for(side)
        order_id = self._client.buy_limit(token, share_price, usdc)
        shares = round(usdc / share_price, 2)
        self.position = Position(
            side=side,
            entry_price=share_price,
            shares=shares,
            entry_ts=dt.datetime.now(dt.timezone.utc),
        )
        self._db.add_trade(
            market=market, side=side, action="BUY",
            price=share_price, size=usdc, status="OPEN",
        )
        # I-persist para ma-restore kapag na-restart ang app mid-position
        self._db.save_open_position(
            self.MODE, market, side, share_price, shares, self.position.entry_ts
        )
        self._db.add_log("TRADE", f"[LIVE] Order posted: {order_id}")
        return self.position

    def sell(self, market: str, share_price: float) -> float:
        assert self.position is not None, "no open position"
        assert self.market is not None
        pos = self.position
        token = self.market.token_for(pos.side)
        order_id = self._client.sell_limit(token, share_price, pos.shares)
        proceeds = pos.shares * share_price
        pnl = proceeds - pos.shares * pos.entry_price
        self._db.add_trade(
            market=market, side=pos.side, action="SELL",
            price=share_price, size=proceeds, status="OPEN", pnl=pnl,
        )
        self._db.add_log("TRADE", f"[LIVE] Sell order posted: {order_id}")
        self.position = None
        self._db.clear_open_position()
        return pnl
