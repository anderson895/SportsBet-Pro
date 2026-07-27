"""Unit tests para sa straddle math: fees, sizing, PnL, candidate filter.

Run:  .\\venv\\Scripts\\python.exe -m pytest tests\\test_straddle_math.py -v
"""
from __future__ import annotations

import unittest

from src.strategy.straddle import (
    MarketCandidate,
    ScanConfig,
    TAKER_FEE_COEF,
    fee_cents,
    is_candidate,
    locked_pnl_cents,
    rank_candidates,
    straddle_sizing,
)

NOW = 1_800_000_000.0  # arbitrary unix seconds


def candidate(**overrides) -> MarketCandidate:
    base = dict(
        ticker="KXNBAGAME-TEST", title="Team A vs Team B",
        yes_bid=48, yes_ask=50, no_bid=48, no_ask=50,
        volume=20_000, close_ts=NOW + 3 * 3600,
    )
    base.update(overrides)
    return MarketCandidate(**base)


class TestFees(unittest.TestCase):
    def test_maker_fee_at_49_cents(self) -> None:
        # 0.0175 * 100 * 0.49 * 0.51 = $0.437 -> rounded UP sa 44¢
        self.assertEqual(fee_cents(100, 49), 44)

    def test_fee_rounds_up(self) -> None:
        # 0.0175 * 1 * 0.49 * 0.51 = $0.0044 -> 1¢ (hindi 0)
        self.assertEqual(fee_cents(1, 49), 1)

    def test_taker_fee_higher(self) -> None:
        self.assertGreater(
            fee_cents(100, 51, TAKER_FEE_COEF), fee_cents(100, 51)
        )


class TestSizingAndPnl(unittest.TestCase):
    def test_sizing_within_budget(self) -> None:
        # $100 budget @ 49+49=98¢/pair -> ~101 pairs pero may fees pa
        count = straddle_sizing(100.0, 49, 49)
        self.assertGreaterEqual(count, 1)
        total = (count * 98 + fee_cents(count, 49) * 2)
        self.assertLessEqual(total, 100 * 100)

    def test_sizing_too_small(self) -> None:
        self.assertEqual(straddle_sizing(0.50, 49, 49), 0)

    def test_locked_pnl_positive_at_49_49(self) -> None:
        # 100 pairs: payout $100, cost $98, fees ~$0.88 -> +$1.12
        pnl = locked_pnl_cents(100, 49, 49)
        self.assertGreater(pnl, 0)
        self.assertEqual(pnl, 100 * 100 - 100 * 98 - 2 * fee_cents(100, 49))

    def test_scratch_at_49_51_loses_only_fees(self) -> None:
        # Sentinel scratch: 49¢ + 51¢ = $1.00 cost sa $1.00 payout
        pnl = locked_pnl_cents(100, 49, 51)
        self.assertLessEqual(pnl, 0)
        self.assertGreater(pnl, -200)  # fees lang ang talo, hindi capital


class TestCandidateFilter(unittest.TestCase):
    def test_good_candidate_passes(self) -> None:
        ok, reason = is_candidate(candidate(), NOW)
        self.assertTrue(ok, reason)

    def test_low_volume_rejected(self) -> None:
        ok, reason = is_candidate(candidate(volume=100), NOW)
        self.assertFalse(ok)
        self.assertIn("volume", reason)

    def test_lopsided_market_rejected(self) -> None:
        # 80/20 market — hindi 50/50, walang straddle
        ok, reason = is_candidate(
            candidate(yes_bid=78, yes_ask=82, no_bid=18, no_ask=22), NOW
        )
        self.assertFalse(ok)
        self.assertIn("band", reason)

    def test_closing_too_soon_rejected(self) -> None:
        ok, reason = is_candidate(
            candidate(close_ts=NOW + 10 * 60), NOW
        )
        self.assertFalse(ok)
        self.assertIn("close", reason)

    def test_closing_too_far_rejected(self) -> None:
        ok, reason = is_candidate(
            candidate(close_ts=NOW + 48 * 3600), NOW
        )
        self.assertFalse(ok)
        self.assertIn("far", reason)

    def test_empty_book_rejected(self) -> None:
        ok, reason = is_candidate(candidate(yes_bid=0, yes_ask=0), NOW)
        self.assertFalse(ok)

    def test_ranking_prefers_volume(self) -> None:
        low = candidate(ticker="LOW", volume=6000)
        high = candidate(ticker="HIGH", volume=60000)
        ranked = rank_candidates([low, high], NOW)
        self.assertEqual([m.ticker for m in ranked], ["HIGH", "LOW"])

    def test_custom_config_band(self) -> None:
        cfg = ScanConfig(min_entry_cents=45, max_entry_cents=55)
        ok, _ = is_candidate(
            candidate(yes_bid=44, yes_ask=48, no_bid=52, no_ask=56), NOW, cfg
        )
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
