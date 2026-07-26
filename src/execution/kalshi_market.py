"""Kalshi BTC Up/Down market discovery for the mean-reversion strategy.

Kalshi has no single "Up or Down" contract like Polymarket. Instead the
**KXBTCD** series ("Bitcoin price Above/below", hourly) is a dense ladder of
"BTC above $STRIKE at the hour's end" markets (``strike_type='greater'``,
~$100 apart). We SYNTHESIZE an up/down market for a period by locking onto the
strike nearest to that period's OPEN price ("price to beat"):

    YES (above strike) = UP      NO (below strike) = DOWN

So when BTC is pumped above the open we buy the cheap NO (=DOWN) side, and when
dumped we buy the cheap YES (=UP) side — exactly the Polymarket mean-reversion
mapping, just assembled from a threshold ladder.

Verified live (2026-07-27): series ``KXBTCD``, ticker
``KXBTCD-{YYMMMDD}{HH}-T{strike}``, field ``floor_strike``,
``expected_expiration_time`` ~5 min past the top of the ET/UTC hour;
near-the-money strikes carry liquid ~50/50 order books.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

from src.execution.kalshi_client import (
    KalshiClient,
    KalshiError,
    best_prices_from_orderbook,
)

# Kalshi series that expose the BTC above/below ladder, per timeframe.
# Only the hourly ladder (KXBTCD) is reliably populated; daily above/below
# (BTCD/BTCD-B) is often empty, so the Kalshi bot defaults to the 1h market.
TF_TO_SERIES: dict[str, str] = {
    "1h": "KXBTCD",
    "daily": "BTCD",
}

# How far the chosen market's settlement may sit from the period end and still
# count as "this period's" market (the hourly ladder settles ~5 min past).
EXPIRY_TOLERANCE_SECS = 20 * 60


@dataclass(frozen=True)
class KalshiBtcMarket:
    """A synthesized BTC Up/Down market pinned to a period-open strike."""

    ticker: str
    strike: float
    question: str
    expiration_ts: float

    def side_key(self, side: str) -> str:
        """UP -> 'yes' (above strike), DOWN -> 'no' (below strike)."""
        return "yes" if side == "UP" else "no"


def _period_seconds(timeframe: str) -> float:
    return {"1h": 3600.0, "daily": 86400.0, "4h": 14400.0, "15m": 900.0}[
        timeframe
    ]


def _parse_ts(raw: object) -> Optional[float]:
    if not raw:
        return None
    try:
        return dt.datetime.fromisoformat(
            str(raw).replace("Z", "+00:00")
        ).timestamp()
    except ValueError:
        return None


async def find_btc_market(
    client: KalshiClient,
    timeframe: str,
    period_start: dt.datetime,
    open_price: float,
) -> KalshiBtcMarket:
    """Resolve the Kalshi BTC up/down market for the given period.

    Picks the ladder market settling at this period's end whose strike is
    nearest to ``open_price``. Raises ``KalshiError`` if none is found.
    """
    series = TF_TO_SERIES.get(timeframe)
    if series is None:
        raise KalshiError(
            f"Kalshi has no BTC up/down ladder for timeframe {timeframe!r}; "
            "use the 1h (or daily) market"
        )
    period_end = period_start.timestamp() + _period_seconds(timeframe)

    data = await client.get_markets(series_ticker=series, limit=1000)
    ladder = [
        m for m in data.get("markets", [])
        if str(m.get("strike_type")) == "greater"
        and m.get("floor_strike") is not None
        and _parse_ts(m.get("expected_expiration_time")) is not None
    ]
    if not ladder:
        raise KalshiError(
            f"No open {series} above/below markets found for BTC"
        )

    # Group by settlement time, then pick the group settling at this period's
    # end (closest expiry to period_end within tolerance).
    groups: dict[float, list[dict]] = {}
    for m in ladder:
        exp = _parse_ts(m["expected_expiration_time"])
        groups.setdefault(exp, []).append(m)  # type: ignore[arg-type]

    best_exp = min(groups, key=lambda e: abs(e - period_end))
    if abs(best_exp - period_end) > EXPIRY_TOLERANCE_SECS:
        # Nothing settles at our period end (e.g. between hourly listings) —
        # fall back to the nearest future settlement so trading can proceed.
        future = [e for e in groups if e > period_start.timestamp()]
        if not future:
            raise KalshiError(
                f"No {series} market settles near this period "
                f"(end {dt.datetime.utcfromtimestamp(period_end)}Z)"
            )
        best_exp = min(future)

    group = groups[best_exp]
    market = min(group, key=lambda m: abs(float(m["floor_strike"]) - open_price))
    strike = float(market["floor_strike"])
    exp_iso = dt.datetime.fromtimestamp(
        best_exp, dt.timezone.utc
    ).strftime("%Y-%m-%d %H:%MZ")
    question = (
        f"BTC above ${strike:,.0f} at {exp_iso} (open ${open_price:,.0f})"
    )
    return KalshiBtcMarket(
        ticker=str(market["ticker"]),
        strike=strike,
        question=question,
        expiration_ts=best_exp,
    )


def best_prices_for_side(
    prices: dict, side: str
) -> tuple[Optional[float], Optional[float]]:
    """(best_bid, best_ask) in DOLLARS (0-1) for the given UP/DOWN side.

    ``prices`` is the dict from ``best_prices_from_orderbook`` (cents).
    UP reads the YES book, DOWN reads the NO book. Mirrors the
    ``PolymarketClient.get_best_prices`` (bid, ask) tuple the engine expects.
    """
    if side == "UP":
        bid, ask = prices.get("yes_bid"), prices.get("yes_ask")
    else:
        bid, ask = prices.get("no_bid"), prices.get("no_ask")
    return (
        None if bid is None else bid / 100.0,
        None if ask is None else ask / 100.0,
    )


async def fetch_side_prices(
    client: KalshiClient, ticker: str, side: str
) -> tuple[Optional[float], Optional[float]]:
    """Convenience: fetch the orderbook and return (bid, ask) dollars for side."""
    book = await client.get_orderbook(ticker)
    return best_prices_for_side(best_prices_from_orderbook(book), side)
