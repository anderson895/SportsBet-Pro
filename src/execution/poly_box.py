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

# Gamma's umbrella "Sports" tag. One paginated query on this tag returns every
# sports market ordered by volume, which is far cheaper than one query per
# league (~12 requests vs ~40) and empirically surfaces the same tradeable
# ~50/50 games.
SPORTS_TAG_ID = 1
SPORTS_PAGE_SIZE = 100
SPORTS_MAX_PAGES = 12

# Friendly league name -> the prefixes Gamma puts on that league's EVENT slug.
# Game events are slugged "<league>-<away>-<home>-<date>" (e.g.
# "mlb-bal-det-2026-07-27"), so the prefix identifies the league without a
# second API call.
#
# Prefixes confirmed live against the API: mlb, nba, wnba, nhl, epl, serie,
# uefa, mex/liga, atp, wta, ncaa, mls, laliga, lol, cs2, dota2. NFL and
# Ligue 1 had no in-season game events at the time of writing, so their
# prefixes follow the same scheme but are unverified — a wrong guess only
# means that league matches nothing, never a wrong trade.
SPORT_LEAGUES: list[tuple[str, tuple[str, ...]]] = [
    ("Baseball — MLB", ("mlb",)),
    ("Basketball — NBA", ("nba",)),
    ("Basketball — WNBA", ("wnba",)),
    ("Basketball — College", ("ncaab", "cbb")),
    ("Football — NFL", ("nfl",)),
    ("Football — College", ("ncaa", "ncaaf", "cfb")),
    ("Hockey — NHL", ("nhl",)),
    ("Soccer — EPL", ("epl",)),
    ("Soccer — Champions League", ("uefa",)),
    ("Soccer — La Liga", ("laliga",)),
    ("Soccer — Serie A", ("serie",)),
    ("Soccer — Ligue 1", ("ligue1",)),
    ("Soccer — MLS", ("mls",)),
    ("Soccer — Liga MX", ("mex", "liga")),
    ("Tennis — ATP/WTA", ("atp", "wta")),
    ("Esports — LoL / CS2 / Dota 2", ("lol", "cs2", "dota2", "val")),
]


def _event_slug(m: dict) -> str:
    events = m.get("events") or []
    return str(events[0].get("slug") or "") if events else ""


def _league_of(m: dict) -> str:
    """First path segment of the event slug — the league key (e.g. "mlb")."""
    return _event_slug(m).split("-")[0].lower()


def prefixes_for(labels: list[str]) -> set[str]:
    """Selected league labels -> the set of event-slug prefixes to keep."""
    wanted = set(labels)
    return {p for label, prefixes in SPORT_LEAGUES if label in wanted
            for p in prefixes}


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

    Most sports GAME markets are not labelled Yes/No — moneylines are named
    after the teams ("Boston Red Sox" / "New York Yankees") and totals are
    "Over"/"Under". They are still two complementary CLOB tokens, so box arb
    works exactly the same; requiring literal Yes/No silently dropped every
    game market. For those we map positionally: Gamma's bestBid/bestAsk always
    quote outcomes[0] (verified against outcomePrices), so outcomes[0] is the
    "YES" side and outcomes[1] the "NO" side.
    """
    if not m.get("enableOrderBook", True):
        return None
    outcomes = _as_list(m.get("outcomes"))
    tokens = _as_list(m.get("clobTokenIds"))
    if len(outcomes) != 2 or len(tokens) != 2:
        return None
    idx = {str(o).strip().upper(): i for i, o in enumerate(outcomes)}
    if "YES" in idx and "NO" in idx:
        yes_i, no_i = idx["YES"], idx["NO"]
    else:
        yes_i, no_i = 0, 1
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
        yes_token=str(tokens[yes_i]),
        no_token=str(tokens[no_i]),
    )
    return cand, ref


async def scan_markets(
    client: Optional[httpx.AsyncClient] = None,
    leagues: Optional[list[str]] = None,
) -> tuple[list[MarketCandidate], dict[str, PolyMarketRef]]:
    """Scan active Polymarket SPORTS markets. Returns (candidates, refs).

    `leagues` are labels from `SPORT_LEAGUES`; an empty/None list means every
    sport. The `straddle.is_candidate` band + volume filter then picks the
    tradeable ~50/50 ones.

    Gamma caps `limit` at 100 regardless of what we ask for, so the market list
    is paged with `offset` — requesting 500 in one call silently returned 100.
    """
    owned = client is None
    http = client or httpx.AsyncClient(timeout=20)
    keep = prefixes_for(leagues or [])
    rows: list[dict] = []
    try:
        for page in range(SPORTS_MAX_PAGES):
            resp = await http.get(f"{GAMMA_API}/markets", params={
                "closed": "false", "active": "true",
                "limit": SPORTS_PAGE_SIZE, "offset": page * SPORTS_PAGE_SIZE,
                "tag_id": SPORTS_TAG_ID,
                "order": "volumeNum", "ascending": "false",
            })
            resp.raise_for_status()
            data = resp.json()
            batch = data if isinstance(data, list) else data.get("data", [])
            rows.extend(batch)
            if len(batch) < SPORTS_PAGE_SIZE:
                break
    finally:
        if owned:
            await http.aclose()
    cands: list[MarketCandidate] = []
    refs: dict[str, PolyMarketRef] = {}
    for m in rows:
        if keep and _league_of(m) not in keep:
            continue
        parsed = to_candidate(m)
        if parsed is None:
            continue
        cand, ref = parsed
        cands.append(cand)
        refs[cand.ticker] = ref
    filelog.debug("Scanned %d sports markets -> %d candidates (leagues: %s)",
                  len(rows), len(cands), ", ".join(leagues or ["all"]))
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
