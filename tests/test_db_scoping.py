"""Unit tests para sa per-exchange DB scoping (ScopedDatabase).

Ang Polymarket at Kalshi panel ay iisang bot.db — dapat HINDI sila
magkahalo: trades, logs, settings, at open positions ay isolated.

Run:  .\\venv\\Scripts\\python.exe -m pytest tests\\test_db_scoping.py -v
"""
from __future__ import annotations

import datetime as dt
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.storage.db import Database


class TestScoping(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.raw = Database(Path(self._tmp.name) / "test.db")
        self.poly = self.raw.scope("polymarket")
        self.kalshi = self.raw.scope("kalshi")

    def tearDown(self) -> None:
        self.raw.close()
        self._tmp.cleanup()

    def test_trades_isolated(self) -> None:
        self.poly.add_trade("BTC", "DOWN", "BUY", 0.20, 200.0)
        self.kalshi.add_trade("KXNBA", "YES", "BUY", 0.49, 49.0)
        self.kalshi.add_trade("KXNBA", "PAIR", "SETTLE", 0.49, 100.0,
                              status="FILLED", pnl=1.12)

        self.assertEqual(len(self.poly.recent_trades()), 1)
        self.assertEqual(len(self.kalshi.recent_trades()), 2)
        self.assertEqual(self.poly.recent_trades()[0]["market"], "BTC")

    def test_pnl_and_stats_isolated(self) -> None:
        self.poly.add_trade("BTC", "DOWN", "SELL", 0.40, 400.0,
                            status="FILLED", pnl=200.0)
        self.kalshi.add_trade("KXNBA", "PAIR", "SETTLE", 0.49, 100.0,
                              status="FILLED", pnl=-0.88)

        self.assertAlmostEqual(self.poly.total_pnl(), 200.0)
        self.assertAlmostEqual(self.kalshi.total_pnl(), -0.88)
        self.assertEqual(self.poly.trade_stats(),
                         {"closed": 1, "wins": 1, "losses": 0})
        self.assertEqual(self.kalshi.trade_stats(),
                         {"closed": 1, "wins": 0, "losses": 1})

    def test_logs_isolated_and_clear_scoped(self) -> None:
        self.poly.add_log("INFO", "poly log")
        self.kalshi.add_log("ERROR", "kalshi log")
        self.assertEqual(len(self.poly.recent_logs()), 1)
        self.assertEqual(len(self.kalshi.recent_logs()), 1)

        self.poly.clear_logs()
        self.assertEqual(len(self.poly.recent_logs()), 0)
        self.assertEqual(len(self.kalshi.recent_logs()), 1)  # buhay pa

    def test_settings_namespaced(self) -> None:
        self.poly.set_setting("trading_mode", "live")
        self.kalshi.set_setting("trading_mode", "paper")
        self.assertEqual(self.poly.get_setting("trading_mode"), "live")
        self.assertEqual(self.kalshi.get_setting("trading_mode"), "paper")
        # Raw keys sa ilalim: prefixed
        self.assertEqual(self.raw.get_setting("polymarket.trading_mode"), "live")
        self.assertEqual(self.raw.get_setting("kalshi.trading_mode"), "paper")

    def test_open_position_isolated(self) -> None:
        now = dt.datetime.now(dt.timezone.utc)
        self.poly.save_open_position("PAPER", "BTC", "DOWN", 0.20, 1000.0, now)
        self.assertIsNotNone(self.poly.load_open_position())
        self.assertIsNone(self.kalshi.load_open_position())

        self.poly.clear_open_position()
        self.assertIsNone(self.poly.load_open_position())


if __name__ == "__main__":
    unittest.main()
