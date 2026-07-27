"""Polymarket box-arb market mapping (Gamma dict -> MarketCandidate + ref).

Pure parsing, no network. Confirms the YES book comes from Gamma bestBid/ask,
the NO book is the binary complement, tokens map to outcomes, the shared
straddle band filter accepts a liquid ~50/50 market, and the scan keeps only
the selected leagues.
"""
import asyncio
import json
import time
import unittest

from src.execution.poly_box import (
    SPORTS_PAGE_SIZE,
    PolyMarketRef,
    prefixes_for,
    scan_markets,
    to_candidate,
)
from src.strategy.straddle import ScanConfig, is_candidate


def _market(yes_bid=0.49, yes_ask=0.51, vol=100_000, outcomes=("Yes", "No"),
            tokens=("TOK_YES", "TOK_NO"), enable=True, cond="0xabc123",
            event_slug=None) -> dict:
    future = time.time() + 3 * 3600
    import datetime as dt
    end = dt.datetime.fromtimestamp(future, dt.timezone.utc).isoformat()
    m = {
        "conditionId": cond,
        "question": "Team A vs Team B — winner?",
        "outcomes": json.dumps(list(outcomes)),
        "clobTokenIds": json.dumps(list(tokens)),
        "bestBid": yes_bid,
        "bestAsk": yes_ask,
        "volumeNum": vol,
        "endDate": end,
        "enableOrderBook": enable,
    }
    if event_slug is not None:
        m["events"] = [{"slug": event_slug}]
    return m


class _FakeResponse:
    def __init__(self, rows): self._rows = rows
    def raise_for_status(self): return None
    def json(self): return self._rows


class _FakeClient:
    """Returns `rows` on the first page, then an empty page to stop paging."""

    def __init__(self, rows):
        self._rows = rows
        self.calls: list[dict] = []

    async def get(self, url, params=None):
        self.calls.append(params or {})
        page = (params or {}).get("offset", 0) // SPORTS_PAGE_SIZE
        return _FakeResponse(self._rows if page == 0 else [])


class ToCandidateTest(unittest.TestCase):
    def test_parses_yes_book_and_complements_no(self) -> None:
        cand, ref = to_candidate(_market(0.49, 0.51))
        self.assertEqual(cand.ticker, "0xabc123")
        self.assertEqual((cand.yes_bid, cand.yes_ask), (49, 51))
        # NO book = binary complement of the YES book
        self.assertEqual(cand.no_bid, 100 - 51)   # 49
        self.assertEqual(cand.no_ask, 100 - 49)   # 51
        self.assertEqual(cand.volume, 100_000)
        self.assertIsInstance(ref, PolyMarketRef)

    def test_maps_tokens_to_outcomes_regardless_of_order(self) -> None:
        _, ref = to_candidate(_market(outcomes=("No", "Yes"),
                                      tokens=("TOK_NO", "TOK_YES")))
        self.assertEqual(ref.yes_token, "TOK_YES")
        self.assertEqual(ref.no_token, "TOK_NO")
        self.assertEqual(ref.token_for("YES"), "TOK_YES")
        self.assertEqual(ref.token_for("NO"), "TOK_NO")

    def test_rejects_non_binary_or_orderbookless(self) -> None:
        self.assertIsNone(to_candidate(_market(outcomes=("A", "B", "C"),
                                               tokens=("1", "2", "3"))))
        self.assertIsNone(to_candidate(_market(enable=False)))
        self.assertIsNone(to_candidate(_market(yes_bid=0.0, yes_ask=0.0)))

    def test_liquid_5050_market_passes_the_band_filter(self) -> None:
        cand, _ = to_candidate(_market(0.49, 0.51, vol=100_000))
        ok, reason = is_candidate(cand, time.time(),
                                  ScanConfig(min_volume=5000))
        self.assertTrue(ok, reason)

    def test_lopsided_market_is_rejected_by_band(self) -> None:
        cand, _ = to_candidate(_market(0.84, 0.86, vol=100_000))
        ok, _ = is_candidate(cand, time.time(), ScanConfig(min_volume=5000))
        self.assertFalse(ok)


class LeagueFilterTest(unittest.TestCase):
    def test_labels_map_to_event_slug_prefixes(self) -> None:
        self.assertEqual(prefixes_for(["Baseball — MLB"]), {"mlb"})
        self.assertIn("nba", prefixes_for(["Basketball — NBA"]))
        # Unknown labels contribute nothing rather than blowing up
        self.assertEqual(prefixes_for(["Curling — Nope"]), set())
        self.assertEqual(prefixes_for([]), set())

    def _scan(self, rows, leagues):
        client = _FakeClient(rows)
        cands, _refs = asyncio.run(scan_markets(client, leagues))
        return {c.ticker for c in cands}, client

    def test_scan_keeps_only_selected_leagues(self) -> None:
        rows = [
            _market(cond="MLB", event_slug="mlb-bal-det-2026-07-27"),
            _market(cond="NBA", event_slug="nba-lal-bos-2026-07-27"),
            _market(cond="DOTA", event_slug="dota2-bald-kw1-2026-07-27"),
        ]
        tickers, _ = self._scan(rows, ["Baseball — MLB"])
        self.assertEqual(tickers, {"MLB"})

    def test_empty_selection_keeps_every_sport(self) -> None:
        rows = [
            _market(cond="MLB", event_slug="mlb-bal-det-2026-07-27"),
            _market(cond="NBA", event_slug="nba-lal-bos-2026-07-27"),
        ]
        tickers, _ = self._scan(rows, [])
        self.assertEqual(tickers, {"MLB", "NBA"})

    def test_scan_requests_the_sports_tag(self) -> None:
        _tickers, client = self._scan([_market(event_slug="mlb-a-b-2026")], [])
        self.assertEqual(client.calls[0]["tag_id"], 1)

    def test_scan_pages_with_offset(self) -> None:
        # A full first page must trigger a second request — Gamma caps
        # `limit` at 100, so a single call silently truncates the scan.
        rows = [_market(cond=f"M{i}", event_slug="mlb-a-b-2026")
                for i in range(SPORTS_PAGE_SIZE)]
        _tickers, client = self._scan(rows, [])
        self.assertGreaterEqual(len(client.calls), 2)
        self.assertEqual(client.calls[1]["offset"], SPORTS_PAGE_SIZE)


if __name__ == "__main__":
    unittest.main()
