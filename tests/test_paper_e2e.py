"""End-to-end test ng PAPER buy/sell logic — buong engine pipeline.

Sine-simulate ang isang buong mean-reversion na daily period. Ang daily
market ay naka-anchor sa TANGHALI ET (16:00 UTC sa EDT / 17:00 sa EST),
kaya ang entry window (4-12h pagkatapos ng anchor) ay ~20:00-04:00 UTC.
Ang mga tick hours dito ay pinili para valid sa PAREHONG EDT at EST:
  1. 22:00 UTC (5-6h sa period): BTC pumped +2.0% mula sa strike
     -> bibili ang bot ng DOWN shares sa ~20c ($200 risk)
  2. Mamaya: bumalik ang BTC sa +0.6% (reversion)
     -> ang DOWN share ay ~41c na = +105% >= +100% profit target
     -> magbebenta ang bot, positive PnL
Dumadaan ito sa TOTOONG PolyEngine._evaluate_strategy (hindi lang ang mga
pure function) kasama ang DB recording at position persistence.

Run:  .\\venv\\Scripts\\python.exe -m pytest tests\\test_paper_e2e.py -v
"""
from __future__ import annotations

import datetime as dt
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import src.core.engine_poly as engine_mod
from src.core.engine_poly import PolyEngine, BotState
from src.storage.db import Database

FIXED_OPEN = 64_000.0


def _fake_dt(hour: int, minute: int = 0):
    """Module-level `dt` replacement para kontrolado ang oras (UTC)."""
    fixed = dt.datetime(2026, 7, 11, hour, minute, tzinfo=dt.timezone.utc)

    class _FakeDateTime:
        @staticmethod
        def now(tz=None):
            return fixed

    return SimpleNamespace(datetime=_FakeDateTime, timezone=dt.timezone,
                           date=dt.date)


class TestPaperBuySellE2E(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self._raw_db = Database(Path(self._tmp.name) / "test.db")
        self.db = self._raw_db.scope("polymarket")
        self.db.set_setting("risk_usdc", 200.0)
        self.db.set_setting("trading_mode", "paper")
        self.engine = PolyEngine(self.db)
        # Gayahin ang START nang hindi bumubukas ng network tasks
        self.engine.state = BotState.RUNNING
        self.engine.config = self.engine._load_config()
        # Feed state na normal (walang volume spike, walang premium data)
        self.engine._feed.daily_open = FIXED_OPEN
        self.engine._feed.hourly_volumes = [100.0] * 23
        self.engine._coinbase.last_price = None  # fail-open ang premium filter
        self._real_dt = engine_mod.dt

    def tearDown(self) -> None:
        engine_mod.dt = self._real_dt
        self._raw_db.close()
        self._tmp.cleanup()

    def _tick(self, hour: int, stretch_pct: float, minute: int = 0) -> None:
        """Isang price tick sa engine sa itinakdang oras at stretch."""
        engine_mod.dt = _fake_dt(hour, minute)
        price = FIXED_OPEN * (1 + stretch_pct / 100)
        self.engine._feed.last_price = price
        self.engine._evaluate_strategy(stretch_pct)

    def test_full_buy_then_sell_cycle(self) -> None:
        eng = self.engine

        # --- 18:00 UTC (1-2h sa period), +2.0%: TAMA ang stretch pero
        #     SARADO pa ang window (bubukas 4h pagkatapos ng tanghali ET)
        self._tick(18, 2.0)
        self.assertIsNone(eng.executor.position, "bumili nang maaga!")

        # --- 22:00 UTC, +0.5%: bukas ang window pero KULANG ang stretch
        self._tick(22, 0.5)
        self.assertIsNone(eng.executor.position, "bumili nang walang stretch!")

        # --- 22:00 UTC, +2.0%: LAHAT pasok -> BUY DOWN sa ~20c
        self._tick(22, 2.0)
        pos = eng.executor.position
        self.assertIsNotNone(pos, "hindi bumili kahit pasok ang kondisyon")
        self.assertEqual(pos.side, "DOWN")
        self.assertAlmostEqual(pos.entry_price, 0.20, places=2)
        self.assertAlmostEqual(pos.shares, 1000.0, places=0)  # $200 / 0.20

        trades = self.db.recent_trades()
        self.assertEqual(trades[0]["action"], "BUY")
        self.assertEqual(trades[0]["side"], "DOWN")
        # Naka-persist ang position para sa restart resume
        self.assertIsNotNone(self.db.load_open_position())

        # --- 23:00 UTC, +1.0% pa rin: HINDI pa profit target (holding)
        self._tick(23, 1.0)
        self.assertIsNotNone(eng.executor.position, "nagbenta nang maaga!")

        # --- 23:30 UTC, +0.6%: reversion! share ~41c = +105% -> SELL
        self._tick(23, 0.6, minute=30)
        self.assertIsNone(eng.executor.position, "hindi nagbenta sa target")

        trades = self.db.recent_trades()
        self.assertEqual(trades[0]["action"], "SELL")
        pnl = trades[0]["pnl"]
        self.assertIsNotNone(pnl)
        self.assertGreater(pnl, 150.0, f"masyadong maliit ang PnL: {pnl}")
        self.assertAlmostEqual(self.db.total_pnl(), pnl, places=2)
        # Malinis na ang persisted position
        self.assertIsNone(self.db.load_open_position())

    def test_stop_loss_cycle(self) -> None:
        eng = self.engine
        # BUY DOWN sa ~20c (22:00 UTC, +2.0%)
        self._tick(22, 2.0)
        self.assertIsNotNone(eng.executor.position)

        # Lumalim pa ang pump: +2.8% -> DOWN share ~ 0.50-0.15*2.8 = 0.08
        # = -60% <= -50% stop loss -> SELL (cut loss)
        self._tick(23, 2.8)
        self.assertIsNone(eng.executor.position, "hindi nag-stop loss")
        trades = self.db.recent_trades()
        self.assertEqual(trades[0]["action"], "SELL")
        self.assertLess(trades[0]["pnl"], 0)

    def test_max_one_trade_per_period(self) -> None:
        eng = self.engine
        self._tick(22, 2.0)  # buy
        self._tick(23, 0.6)  # sell sa profit
        self.assertIsNone(eng.executor.position)
        # Pumasok ulit ang kondisyon SA PAREHONG PERIOD -> bawal na
        self._tick(23, 2.0, minute=30)
        self.assertIsNone(eng.executor.position, "lumampas sa 1 trade/period!")


if __name__ == "__main__":
    unittest.main()
