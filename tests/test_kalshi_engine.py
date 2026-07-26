"""End-to-end PAPER buy/sell through the real KalshiEngine pipeline.

Same mean-reversion scenario as the Polymarket engine test (buy DOWN at ~20¢
on a +2.0% stretch inside the window, sell at the +100% target on reversion),
driven through ``KalshiEngine._evaluate_strategy`` on the daily timeframe — the
strategy is identical across venues, only the executor/market differ.
"""
from __future__ import annotations

import datetime as dt
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import src.core.engine_kalshi as engine_mod
from src.core.engine_kalshi import BotState, KalshiEngine
from src.storage.db import Database

FIXED_OPEN = 64_000.0


def _fake_dt(hour: int, minute: int = 0):
    fixed = dt.datetime(2026, 7, 11, hour, minute, tzinfo=dt.timezone.utc)

    class _FakeDateTime:
        @staticmethod
        def now(tz=None):
            return fixed

    return SimpleNamespace(datetime=_FakeDateTime, timezone=dt.timezone,
                           date=dt.date)


class TestKalshiPaperE2E(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self._raw_db = Database(Path(self._tmp.name) / "test.db")
        self.db = self._raw_db.scope("kalshi")
        self.db.set_setting("risk_usd", 200.0)
        self.db.set_setting("trading_mode", "paper")
        self.db.set_setting("market_timeframe", "daily")  # reuse daily windows
        self.engine = KalshiEngine(self.db)
        self.engine.state = BotState.RUNNING
        self.engine.config = self.engine._load_config()
        self.engine._feed.daily_open = FIXED_OPEN
        self.engine._feed.hourly_volumes = [100.0] * 23
        self.engine._coinbase.last_price = None
        self._real_dt = engine_mod.dt

    def tearDown(self) -> None:
        engine_mod.dt = self._real_dt
        self._raw_db.close()
        self._tmp.cleanup()

    def _tick(self, hour: int, stretch_pct: float, minute: int = 0) -> None:
        engine_mod.dt = _fake_dt(hour, minute)
        price = FIXED_OPEN * (1 + stretch_pct / 100)
        self.engine._feed.last_price = price
        self.engine._evaluate_strategy(stretch_pct)

    def test_full_buy_then_sell_cycle(self) -> None:
        eng = self.engine

        # Window still closed early in the period, even with a good stretch
        self._tick(18, 2.0)
        self.assertIsNone(eng.executor.position)

        # In window but not enough stretch
        self._tick(22, 0.5)
        self.assertIsNone(eng.executor.position)

        # All conditions pass -> BUY DOWN at ~20¢
        self._tick(22, 2.0)
        pos = eng.executor.position
        self.assertIsNotNone(pos)
        self.assertEqual(pos.side, "DOWN")
        self.assertAlmostEqual(pos.entry_price, 0.20, places=2)
        self.assertAlmostEqual(pos.shares, 1000.0, places=0)

        trades = self.db.recent_trades()
        self.assertEqual(trades[0]["action"], "BUY")
        self.assertEqual(trades[0]["side"], "DOWN")
        self.assertIsNotNone(self.db.load_open_position())

        # Holding — not at target yet
        self._tick(23, 1.0)
        self.assertIsNotNone(eng.executor.position)

        # Reversion to +0.6% -> ~41¢ = +105% -> SELL at profit
        self._tick(23, 0.6, minute=30)
        self.assertIsNone(eng.executor.position)
        trades = self.db.recent_trades()
        self.assertEqual(trades[0]["action"], "SELL")
        self.assertGreater(trades[0]["pnl"], 150.0)

    def test_stop_loss_cycle(self) -> None:
        eng = self.engine
        self._tick(22, 2.0)
        self.assertIsNotNone(eng.executor.position)
        # Deeper pump -> DOWN share collapses -> stop loss
        self._tick(23, 2.8)
        self.assertIsNone(eng.executor.position)
        self.assertLess(self.db.recent_trades()[0]["pnl"], 0)

    def test_max_one_trade_per_period(self) -> None:
        eng = self.engine
        self._tick(22, 2.0)
        self._tick(23, 0.6)
        self.assertIsNone(eng.executor.position)
        self._tick(23, 2.0, minute=30)
        self.assertIsNone(eng.executor.position, "exceeded 1 trade/period")


if __name__ == "__main__":
    unittest.main()
