"""Unit tests para sa death-trap filters.

Run:  .\\venv\\Scripts\\python.exe -m unittest tests.test_filters -v
"""
from __future__ import annotations

import unittest

from src.strategy.filters import (
    coinbase_premium_pct,
    is_premium_exploding,
    is_volume_escalating,
)


def volumes(baseline: float, recent: list[float], baseline_n: int = 20) -> list[float]:
    """Gumawa ng volume series: flat baseline tapos custom recent hours."""
    return [baseline] * baseline_n + recent


class TestVolumeEscalation(unittest.TestCase):
    def test_normal_volume_passes(self) -> None:
        # Recent ~ pareho lang ng baseline -> hindi escalating
        esc, why = is_volume_escalating(volumes(1000, [1100, 950, 1050]))
        self.assertFalse(esc)
        self.assertIn("normal", why)

    def test_escalating_volume_blocks(self) -> None:
        # Recent = 3x ng baseline -> momentum day, block
        esc, why = is_volume_escalating(volumes(1000, [2800, 3200, 3000]))
        self.assertTrue(esc)
        self.assertIn("escalating", why)

    def test_exactly_at_threshold_blocks(self) -> None:
        # Eksaktong 2.0x -> block (>= ang comparison)
        esc, _ = is_volume_escalating(volumes(1000, [2000, 2000, 2000]))
        self.assertTrue(esc)

    def test_single_spike_averaged_out(self) -> None:
        # Isang spike lang na na-average palabas -> hindi block
        esc, _ = is_volume_escalating(volumes(1000, [2500, 900, 1000]))
        self.assertFalse(esc)  # avg = 1466 = 1.47x < 2.0x

    def test_insufficient_data_fails_open(self) -> None:
        # Kulang ang data -> huwag mag-block (fail-open) pero i-report
        esc, why = is_volume_escalating([1000.0] * 5)
        self.assertFalse(esc)
        self.assertIn("insufficient", why)

    def test_zero_baseline(self) -> None:
        esc, _ = is_volume_escalating(volumes(0, [100, 100, 100]))
        self.assertFalse(esc)

    def test_custom_threshold(self) -> None:
        # 1.5x threshold: ang 1.6x recent ay dapat ma-block
        esc, _ = is_volume_escalating(
            volumes(1000, [1600, 1600, 1600]), spike_mult=1.5
        )
        self.assertTrue(esc)


class TestCoinbasePremium(unittest.TestCase):
    def test_premium_calculation(self) -> None:
        # Coinbase $64,128, Binance $64,000 -> +0.20% premium
        self.assertAlmostEqual(coinbase_premium_pct(64128, 64000), 0.20, places=2)
        # Discount naman
        self.assertAlmostEqual(coinbase_premium_pct(63872, 64000), -0.20, places=2)

    def test_pump_with_big_premium_blocks_down_entry(self) -> None:
        # BTC +2% at Coinbase +0.2% premium -> aggressive US buying, block
        exploding, why = is_premium_exploding(0.20, stretch_pct=2.0)
        self.assertTrue(exploding)
        self.assertIn("buying", why)

    def test_pump_with_normal_premium_allows(self) -> None:
        exploding, _ = is_premium_exploding(0.05, stretch_pct=2.0)
        self.assertFalse(exploding)

    def test_dump_with_big_discount_blocks_up_entry(self) -> None:
        # BTC -2% at Coinbase -0.2% discount -> aggressive US selling, block
        exploding, why = is_premium_exploding(-0.20, stretch_pct=-2.0)
        self.assertTrue(exploding)
        self.assertIn("selling", why)

    def test_direction_mismatch_allows(self) -> None:
        # BTC pumped pero Coinbase DISCOUNT -> hindi aggressive buying,
        # OK lang mag-mean-reversion
        exploding, _ = is_premium_exploding(-0.30, stretch_pct=2.0)
        self.assertFalse(exploding)
        # BTC dumped pero Coinbase PREMIUM -> ok mag-UP entry
        exploding, _ = is_premium_exploding(0.30, stretch_pct=-2.0)
        self.assertFalse(exploding)

    def test_custom_threshold(self) -> None:
        exploding, _ = is_premium_exploding(0.12, stretch_pct=2.0, threshold_pct=0.10)
        self.assertTrue(exploding)


if __name__ == "__main__":
    unittest.main()
