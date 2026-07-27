"""Polymarket Box Arbitrage — market discovery + executors.

Same Internal Straddle / Box-Arbitrage strategy as the Kalshi panel
(`strategy/straddle.py`), but on Polymarket:

- **Discovery** — the Gamma API lists binary markets with Yes/No outcome tokens,
  live best bid/ask, and volume. We turn each into a `MarketCandidate` (cents),
  and the shared `straddle.is_candidate` filter keeps only liquid ~50/50 ones.
- **Paper** — reuses the exchange-agnostic `KalshiPaperExecutor` (simulated
  fills from real order-book snapshots).
- **Live** — `PolyBoxLiveExecutor` places two resting CLOB BUY limit orders
  (YES + NO) via the existing `PolymarketClient`, with a Hedge Sentinel for
  single-sided fills — mirrors `kalshi_live` but on the Polymarket CLOB.

Prices are in CENTS (1-99) to match `strategy/straddle.py`. Polymarket's YES
best bid/ask come from Gamma; the NO book is the binary complement
(no_bid = 100 - yes_ask, no_ask = 100 - yes_bid).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from src.execution.kalshi_paper import KalshiPaperExecutor
from src.execution.polymarket import GAMMA_API, PolymarketClient
from src.strategy.straddle import MarketCandidate

filelog = logging.getLogger("sportsbet.poly_box")

# Reuse the exchange-agnostic paper executor (simulated fills from the book).
PolyBoxPaperExecutor = KalshiPaperExecutor


@dataclass(frozen=True)
class PolyMarketRef:
    """A resolved Polymarket binary market: YES/NO CLOB token ids."""
    ticker: str          # conditionId (stable id used as the "ticker")
    question: str
    yes_token: str
    no_token: str

    def token_for(self, side: str) -> str:
        return self.yes_token if side == "YES" else self.no_token


def _as_list(value: object) -> list:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return []
    return list(value) if value else []


def _cents(x: object) -> int:
    try:
        return int(round(float(x) * 100))
    except (TypeError, ValueError):
        return 0


def _close_ts(m: dict) -> float:
    raw = m.get("endDate") or m.get("endDateIso") or m.get("end_date_iso")
    if not raw:
        return 0.0
    try:
        return dt.datetime.fromisoformat(
            str(raw).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def to_candidate(m: dict) -> Optional[tuple[MarketCandidate, PolyMarketRef]]:
    """Gamma market dict -> (MarketCandidate, PolyMarketRef); None if unusable.

    yes_bid/ask come from Gamma's bestBid/bestAsk (YES side); the NO book is the
    binary complement.
    """
    if not m.get("enableOrderBook", True):
        return None
    outcomes = _as_list(m.get("outcomes"))
    tokens = _as_list(m.get("clobTokenIds"))
    if len(outcomes) != 2 or len(tokens) != 2:
        return None
    idx = {str(o).strip().upper(): i for i, o in enumerate(outcomes)}
    if "YES" not in idx or "NO" not in idx:
        return None
    yes_bid = _cents(m.get("bestBid"))
    yes_ask = _cents(m.get("bestAsk"))
    if yes_bid <= 0 or yes_ask <= 0:
        return None
    cond = str(m.get("conditionId") or m.get("condition_id") or m.get("id") or "")
    if not cond:
        return None
    cand = MarketCandidate(
        ticker=cond,
        title=str(m.get("question", m.get("slug", cond)))[:90],
        yes_bid=yes_bid,
        yes_ask=yes_ask,
        no_bid=100 - yes_ask,
        no_ask=100 - yes_bid,
        volume=int(float(m.get("volumeNum") or m.get("volume") or 0)),
        close_ts=_close_ts(m),
    )
    ref = PolyMarketRef(
        ticker=cond,
        question=cand.title,
        yes_token=str(tokens[idx["YES"]]),
        no_token=str(tokens[idx["NO"]]),
    )
    return cand, ref


async def scan_markets(
    client: Optional[httpx.AsyncClient] = None, limit: int = 500
) -> tuple[list[MarketCandidate], dict[str, PolyMarketRef]]:
    """Scan active Polymarket binary markets. Returns (candidates, ref-by-ticker).

    Any liquid ~50/50 binary market qualifies — box arb is market-agnostic; the
    `straddle.is_candidate` band + volume filter picks the tradeable ones.
    """
    owned = client is None
    http = client or httpx.AsyncClient(timeout=20)
    params = {
        "closed": "false", "active": "true", "limit": limit,
        "order": "volumeNum", "ascending": "false",
    }
    try:
        resp = await http.get(f"{GAMMA_API}/markets", params=params)
        resp.raise_for_status()
        data = resp.json()
    finally:
        if owned:
            await http.aclose()
    rows = data if isinstance(data, list) else data.get("data", [])
    cands: list[MarketCandidate] = []
    refs: dict[str, PolyMarketRef] = {}
    for m in rows:
        parsed = to_candidate(m)
        if parsed is None:
            continue
        cand, ref = parsed
        cands.append(cand)
        refs[cand.ticker] = ref
    return cands, refs


async def fetch_market_prices(
    ticker: str, client: Optional[httpx.AsyncClient] = None
) -> Optional[dict]:
    """Current best yes/no bid/ask (cents) for one market via Gamma (public).

    Used by PAPER monitoring (no CLOB access). `ticker` is the conditionId.
    """
    owned = client is None
    http = client or httpx.AsyncClient(timeout=15)
    try:
        resp = await http.get(f"{GAMMA_API}/markets",
                              params={"condition_ids": ticker})
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None
    finally:
        if owned:
            await http.aclose()
    rows = data if isinstance(data, list) else data.get("data", [])
    if not rows:
        return None
    m = rows[0]
    yes_bid = _cents(m.get("bestBid"))
    yes_ask = _cents(m.get("bestAsk"))
    if yes_bid <= 0 or yes_ask <= 0:
        return None
    return {"yes_bid": yes_bid, "yes_ask": yes_ask,
            "no_bid": 100 - yes_ask, "no_ask": 100 - yes_bid}


def best_prices_for_ref(
    client: PolymarketClient, ref: PolyMarketRef
) -> dict[str, Optional[int]]:
    """Live best yes/no bid/ask (cents) for a resolved market via the CLOB."""
    yes_bid, yes_ask = client.get_best_prices(ref.yes_token)
    no_bid, no_ask = client.get_best_prices(ref.no_token)

    def c(x: Optional[float]) -> Optional[int]:
        return None if x is None else int(round(x * 100))

    return {"yes_bid": c(yes_bid), "yes_ask": c(yes_ask),
            "no_bid": c(no_bid), "no_ask": c(no_ask)}


class PolyBoxLiveExecutor:
    """Live Polymarket box-arb execution — same interface as the paper one.

    Places two resting BUY limit orders (YES + NO) on the CLOB. Fill tracking
    uses the client's order status. Like the Kalshi live path, this is
    implemented against the documented CLOB API but not verified on a funded
    account — validate with a tiny real order first.
    """

    MODE = "LIVE"

    def __init__(self, client: PolymarketClient) -> None:
        self._client = client
        self._ref: Optional[PolyMarketRef] = None
        self._orders: dict[str, str] = {}   # side -> order id
        self.ticker: Optional[str] = None

    def set_market(self, ref: PolyMarketRef) -> None:
        self._ref = ref

    async def place_straddle(
        self, ticker: str, entry_cents: int, count: int
    ) -> dict[str, str]:
        assert self._ref is not None, "no market resolved"
        self.ticker = ticker
        price = entry_cents / 100.0
        import asyncio
        yes_id = await asyncio.to_thread(
            self._client.buy_limit, self._ref.yes_token, price, count * price)
        try:
            no_id = await asyncio.to_thread(
                self._client.buy_limit, self._ref.no_token, price, count * price)
        except Exception:
            filelog.exception("NO leg failed — cancelling YES leg:")
            await asyncio.to_thread(self._client.cancel_all)
            raise
        self._orders = {"YES": yes_id, "NO": no_id}
        return dict(self._orders)

    def on_book(self, prices: dict) -> None:  # parity with paper executor
        pass

    async def get_fills(self, ticker: str) -> tuple[int, int]:
        import asyncio
        counts = {}
        for side in ("YES", "NO"):
            oid = self._orders.get(side)
            if not oid:
                counts[side] = 0
                continue
            try:
                filled = await asyncio.to_thread(
                    self._client.filled_size, oid)
            except Exception as e:
                filelog.warning("Fill check failed for %s: %s", oid, e)
                filled = 0
            counts[side] = int(filled)
        return counts["YES"], counts["NO"]

    async def cancel(self, ticker: str, side: str) -> None:
        import asyncio
        await asyncio.to_thread(self._client.cancel_all)

    async def cancel_all(self, ticker: str) -> None:
        import asyncio
        await asyncio.to_thread(self._client.cancel_all)

    async def hedge(
        self, ticker: str, side: str, max_price_cents: int, count: int,
        prices: Optional[dict] = None,
    ) -> int:
        import asyncio
        assert self._ref is not None
        token = self._ref.token_for(side)
        price = max_price_cents / 100.0
        try:
            oid = await asyncio.to_thread(
                self._client.buy_limit, token, price, count * price)
        except Exception as e:
            filelog.warning("Hedge order rejected: %s", e)
            return 0
        self._orders[side] = oid
        await asyncio.sleep(1.0)
        try:
            return int(await asyncio.to_thread(self._client.filled_size, oid))
        except Exception:
            return 0

    async def get_balance(self) -> Optional[float]:
        import asyncio
        return await asyncio.to_thread(self._client.get_usdc_balance)
