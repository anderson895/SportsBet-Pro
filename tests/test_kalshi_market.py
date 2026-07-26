"""Kalshi BTC market discovery + up/down mapping (mean reversion).

Uses canned KXBTCD ladder JSON — no network — to verify that
``find_btc_market`` locks onto the strike nearest the period open in the
settlement group matching this period's end, and that the UP/DOWN <-> yes/no
mapping and share-price reads are correct.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import unittest

from src.execution.kalshi_market import (
    best_prices_for_side,
    find_btc_market,
)


def _mkt(strike: float, exp: str) -> dict:
    return {
        "ticker": f"KXBTCD-TEST-T{strike}",
        "floor_strike": strike,
        "strike_type": "greater",
        "expected_expiration_time": exp,
    }


class _FakeClient:
    """Minimal async stand-in exposing get_markets with canned data."""

    def __init__(self, markets: list[dict]) -> None:
        self._markets = markets

    async def get_markets(self, series_ticker=None, limit=100, **kw) -> dict:
        return {"markets": self._markets}


class FindBtcMarketTest(unittest.TestCase):
    # Period: 13:00-14:00 UTC; the market settling ~14:00 is "this period".
    PERIOD_START = dt.datetime(2026, 7, 26, 13, 0, tzinfo=dt.timezone.utc)
    THIS_EXP = "2026-07-26T14:00:00Z"
    NEXT_EXP = "2026-07-26T15:00:00Z"

    def _markets(self) -> list[dict]:
        return [
            _mkt(63_900.99, self.THIS_EXP),
            _mkt(64_000.99, self.THIS_EXP),   # nearest to open 64_000
            _mkt(64_100.99, self.THIS_EXP),
            _mkt(64_000.99, self.NEXT_EXP),   # right strike, wrong period
        ]

    def _find(self, open_price: float):
        client = _FakeClient(self._markets())
        return asyncio.run(
            find_btc_market(client, "1h", self.PERIOD_START, open_price))

    def test_picks_nearest_strike_in_this_period(self) -> None:
        m = self._find(64_000.0)
        self.assertEqual(m.strike, 64_000.99)
        self.assertEqual(m.ticker, "KXBTCD-TEST-T64000.99")
        # settlement matches THIS period's end, not the next hour
        self.assertEqual(
            dt.datetime.fromtimestamp(m.expiration_ts, dt.timezone.utc),
            dt.datetime(2026, 7, 26, 14, 0, tzinfo=dt.timezone.utc),
        )

    def test_nearest_strike_tracks_the_open(self) -> None:
        # An open close to the upper strike selects it instead
        m = self._find(64_090.0)
        self.assertEqual(m.strike, 64_100.99)

    def test_side_mapping_up_is_yes_down_is_no(self) -> None:
        m = self._find(64_000.0)
        self.assertEqual(m.side_key("UP"), "yes")
        self.assertEqual(m.side_key("DOWN"), "no")


class BestPricesForSideTest(unittest.TestCase):
    PRICES = {"yes_bid": 15, "yes_ask": 16, "no_bid": 84, "no_ask": 85}

    def test_up_reads_yes_book_in_dollars(self) -> None:
        bid, ask = best_prices_for_side(self.PRICES, "UP")
        self.assertAlmostEqual(bid, 0.15)
        self.assertAlmostEqual(ask, 0.16)

    def test_down_reads_no_book_in_dollars(self) -> None:
        bid, ask = best_prices_for_side(self.PRICES, "DOWN")
        self.assertAlmostEqual(bid, 0.84)
        self.assertAlmostEqual(ask, 0.85)

    def test_missing_level_is_none(self) -> None:
        bid, ask = best_prices_for_side({"yes_bid": None, "yes_ask": 16}, "UP")
        self.assertIsNone(bid)
        self.assertAlmostEqual(ask, 0.16)


if __name__ == "__main__":
    unittest.main()
