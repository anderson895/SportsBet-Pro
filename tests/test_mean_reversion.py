"""Unit tests para sa mean reversion strategy logic.

Run:  .\\venv\\Scripts\\python.exe -m unittest tests.test_mean_reversion -v
"""
from __future__ import annotations

import datetime as dt
import unittest

from src.execution.paper import estimate_otm_share_price, position_share_price
from src.strategy.mean_reversion import (
    Action,
    Position,
    StrategyConfig,
    evaluate_entry,
    evaluate_exit,
    target_side,
)

CFG = StrategyConfig()


def utc(hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(2026, 7, 11, hour, minute, tzinfo=dt.timezone.utc)


class TestEntry(unittest.TestCase):
    def test_no_entry_before_window(self) -> None:
        # 02:00 UTC — masyadong maaga kahit tamang-tama ang stretch
        sig = evaluate_entry(utc(2), 2.0, 0.20, 0, CFG)
        self.assertIs(sig.action, Action.NONE)
        self.assertIn("entry window", sig.reason)

    def test_no_entry_after_window(self) -> None:
        # 13:00 UTC — sarado na ang window
        sig = evaluate_entry(utc(13), 2.0, 0.20, 0, CFG)
        self.assertIs(sig.action, Action.NONE)

    def test_entry_on_pump_buys_down(self) -> None:
        # +1.9% stretch sa loob ng window, share sa 20c -> BUY DOWN
        sig = evaluate_entry(utc(8), 1.9, 0.20, 0, CFG)
        self.assertIs(sig.action, Action.ENTER)
        self.assertEqual(sig.side, "DOWN")

    def test_entry_on_dump_buys_up(self) -> None:
        sig = evaluate_entry(utc(8), -1.8, 0.22, 0, CFG)
        self.assertIs(sig.action, Action.ENTER)
        self.assertEqual(sig.side, "UP")

    def test_no_entry_small_stretch(self) -> None:
        sig = evaluate_entry(utc(8), 0.8, 0.35, 0, CFG)
        self.assertIs(sig.action, Action.NONE)

    def test_no_entry_death_trap(self) -> None:
        # +3.5% = momentum expansion day, dapat i-skip
        sig = evaluate_entry(utc(8), 3.5, 0.10, 0, CFG)
        self.assertIs(sig.action, Action.NONE)
        self.assertIn("death trap", sig.reason)

    def test_no_entry_share_too_expensive(self) -> None:
        sig = evaluate_entry(utc(8), 1.6, 0.30, 0, CFG)
        self.assertIs(sig.action, Action.NONE)

    def test_no_entry_share_too_cheap(self) -> None:
        # Masyadong mura = malamang malayo na talaga, hindi na babalik
        sig = evaluate_entry(utc(8), 2.4, 0.10, 0, CFG)
        self.assertIs(sig.action, Action.NONE)

    def test_max_trades_per_day(self) -> None:
        sig = evaluate_entry(utc(8), 1.9, 0.20, 1, CFG)
        self.assertIs(sig.action, Action.NONE)
        self.assertIn("max trades", sig.reason)

    def test_no_data_no_entry(self) -> None:
        self.assertIs(evaluate_entry(utc(8), None, None, 0, CFG).action, Action.NONE)


class TestExit(unittest.TestCase):
    def _pos(self, entry: float = 0.20) -> Position:
        return Position(side="DOWN", entry_price=entry, shares=100, entry_ts=utc(8))

    def test_exit_at_profit_target(self) -> None:
        # 0.20 -> 0.50 = +150% -> SELL
        sig = evaluate_exit(utc(14), self._pos(0.20), 0.50, CFG)
        self.assertIs(sig.action, Action.EXIT)
        self.assertIn("profit target", sig.reason)

    def test_hold_below_target(self) -> None:
        # 0.20 -> 0.35 = +75%, hawak pa
        sig = evaluate_exit(utc(14), self._pos(0.20), 0.35, CFG)
        self.assertIs(sig.action, Action.NONE)

    def test_exit_at_stop_loss(self) -> None:
        # 0.20 -> 0.09 = -55% -> cut loss
        sig = evaluate_exit(utc(14), self._pos(0.20), 0.09, CFG)
        self.assertIs(sig.action, Action.EXIT)
        self.assertIn("stop loss", sig.reason)

    def test_eod_force_exit(self) -> None:
        # 23:45 UTC — force exit kahit walang target/stop
        sig = evaluate_exit(utc(23, 45), self._pos(0.20), 0.30, CFG)
        self.assertIs(sig.action, Action.EXIT)
        self.assertIn("end-of-period", sig.reason)


class TestHelpers(unittest.TestCase):
    def test_target_side(self) -> None:
        self.assertEqual(target_side(2.0), "DOWN")
        self.assertEqual(target_side(-2.0), "UP")

    def test_price_model_matches_reference(self) -> None:
        # details.txt: stretch ~2% -> OTM share ~20c
        self.assertAlmostEqual(estimate_otm_share_price(2.0), 0.20, places=2)
        # walang stretch -> 50/50
        self.assertAlmostEqual(estimate_otm_share_price(0.0), 0.50, places=2)
        # retrace sa +0.6% -> ~41c (reference: "45c to 50c" zone)
        self.assertAlmostEqual(estimate_otm_share_price(0.6), 0.41, places=2)
        # floor: hindi bababa sa 0.03 kahit sobrang layo
        self.assertAlmostEqual(estimate_otm_share_price(10.0), 0.03, places=2)

    def test_position_price_direction(self) -> None:
        # Hawak DOWN, BTC nasa +2% pa rin -> mura pa rin ang DOWN (~0.20)
        self.assertAlmostEqual(position_share_price(2.0, "DOWN"), 0.20, places=2)
        # Hawak DOWN, bumagsak na sa -0.5% (nag-cross na!) -> mahal na (~0.575)
        self.assertGreater(position_share_price(-0.5, "DOWN"), 0.5)


class TestFullCycle(unittest.TestCase):
    """Simulahin ang buong araw: pump -> entry -> revert -> profitable exit."""

    def test_reference_scenario(self) -> None:
        # Morning: BTC pumps +1.9% (95,000 -> 96,800 scenario sa details.txt)
        stretch = 1.9
        share = estimate_otm_share_price(stretch)
        sig = evaluate_entry(utc(9), stretch, share, 0, CFG)
        self.assertIs(sig.action, Action.ENTER)
        self.assertEqual(sig.side, "DOWN")

        pos = Position(side="DOWN", entry_price=share, shares=100 / share,
                       entry_ts=utc(9))

        # Hapon: nag-retrace ang BTC pabalik sa +0.3% (still "UP" for the day)
        retrace_stretch = 0.3
        new_price = position_share_price(retrace_stretch, "DOWN")
        sig = evaluate_exit(utc(15), pos, new_price, CFG)
        self.assertIs(sig.action, Action.EXIT)  # profit target hit
        pnl_pct = (new_price - pos.entry_price) / pos.entry_price * 100
        self.assertGreater(pnl_pct, 100)  # lampas +100% ang profit


if __name__ == "__main__":
    unittest.main()
