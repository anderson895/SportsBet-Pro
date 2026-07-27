"""Polymarket box-arb market mapping (Gamma dict -> MarketCandidate + ref).

Pure parsing, no network. Confirms the YES book comes from Gamma bestBid/ask,
the NO book is the binary complement, tokens map to outcomes, and the shared
straddle band filter accepts a liquid ~50/50 market.
"""
import json
import time
import unittest

from src.execution.poly_box import PolyMarketRef, to_candidate
from src.strategy.straddle import ScanConfig, is_candidate


def _market(yes_bid=0.49, yes_ask=0.51, vol=100_000, outcomes=("Yes", "No"),
            tokens=("TOK_YES", "TOK_NO"), enable=True) -> dict:
    future = time.time() + 3 * 3600
    import datetime as dt
    end = dt.datetime.fromtimestamp(future, dt.timezone.utc).isoformat()
    return {
        "conditionId": "0xabc123",
        "question": "Team A vs Team B — winner?",
        "outcomes": json.dumps(list(outcomes)),
        "clobTokenIds": json.dumps(list(tokens)),
        "bestBid": yes_bid,
        "bestAsk": yes_ask,
        "volumeNum": vol,
        "endDate": end,
        "enableOrderBook": enable,
    }


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


if __name__ == "__main__":
    unittest.main()
