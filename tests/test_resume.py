"""Unit tests para sa position resume (restart recovery).

Run:  .\\venv\\Scripts\\python.exe -m pytest tests\\test_resume.py -v
"""
from __future__ import annotations

import datetime as dt
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.execution.paper import PaperExecutor
from src.execution.resume import decide_restore
from src.storage.db import Database

# Kasalukuyang market period: nagsimula 08:00 UTC; ang entries sa 08:30
# ay kabilang dito, ang mas luma ay stale
PERIOD_START = dt.datetime(2026, 7, 11, 8, 0, tzinfo=dt.timezone.utc)


def saved(mode: str = "PAPER",
          entry: dt.datetime | None = None, **overrides) -> dict:
    if entry is None:
        entry = dt.datetime(2026, 7, 11, 8, 30, tzinfo=dt.timezone.utc)
    base = {
        "mode": mode,
        "market": "BTC Up/Down 2026-07-11 [PAPER]",
        "side": "DOWN",
        "entry_price": 0.20,
        "shares": 1000.0,
        "entry_ts": entry.isoformat(timespec="seconds"),
    }
    base.update(overrides)
    return base


class TestDecideRestore(unittest.TestCase):
    def test_no_saved_position(self) -> None:
        pos, level, msg = decide_restore(None, "PAPER", PERIOD_START)
        self.assertIsNone(pos)
        self.assertEqual(msg, "")

    def test_restore_same_period_same_mode(self) -> None:
        pos, level, msg = decide_restore(saved(), "PAPER", PERIOD_START)
        self.assertIsNotNone(pos)
        self.assertEqual(level, "INFO")
        self.assertEqual(pos.side, "DOWN")
        self.assertEqual(pos.entry_price, 0.20)
        self.assertEqual(pos.shares, 1000.0)

    def test_stale_previous_period_discarded(self) -> None:
        pos, level, msg = decide_restore(
            saved(entry=PERIOD_START - dt.timedelta(hours=1)),
            "PAPER", PERIOD_START,
        )
        self.assertIsNone(pos)
        self.assertEqual(level, "WARN")
        self.assertIn("Stale", msg)

    def test_same_period_across_utc_midnight_is_restored(self) -> None:
        # Daily market = tanghali-ET -> tanghali-ET: ang position na binili
        # 23:00 UTC ay dapat ma-restore pagkalampas ng UTC midnight basta
        # hindi pa tapos ang period
        ps = dt.datetime(2026, 7, 11, 16, 0, tzinfo=dt.timezone.utc)  # noon EDT
        entry = dt.datetime(2026, 7, 11, 23, 0, tzinfo=dt.timezone.utc)
        pos, level, msg = decide_restore(saved(entry=entry), "PAPER", ps)
        self.assertIsNotNone(pos)
        self.assertEqual(level, "INFO")

    def test_live_position_in_paper_mode_is_loud_error(self) -> None:
        # May totoong pera pa sa Polymarket — dapat ERROR, hindi tahimik
        pos, level, msg = decide_restore(
            saved(mode="LIVE"), "PAPER", PERIOD_START
        )
        self.assertIsNone(pos)
        self.assertEqual(level, "ERROR")
        self.assertIn("LIVE position", msg)

    def test_paper_position_in_live_mode_discarded(self) -> None:
        pos, level, msg = decide_restore(
            saved(mode="PAPER"), "LIVE", PERIOD_START
        )
        self.assertIsNone(pos)
        self.assertEqual(level, "WARN")

    def test_corrupt_record_discarded(self) -> None:
        pos, level, msg = decide_restore(
            {"mode": "PAPER"}, "PAPER", PERIOD_START
        )
        self.assertIsNone(pos)
        self.assertEqual(level, "WARN")
        self.assertIn("Corrupt", msg)


class TestExecutorPersistence(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self._raw_db = Database(Path(self._tmp.name) / "test.db")
        self.db = self._raw_db.scope("polymarket")

    def tearDown(self) -> None:
        self._raw_db.close()
        self._tmp.cleanup()

    def test_buy_saves_and_sell_clears(self) -> None:
        ex = PaperExecutor(self.db)
        ex.buy("BTC Up/Down test", "DOWN", 0.20, 200.0)

        record = self.db.load_open_position()
        self.assertIsNotNone(record)
        self.assertEqual(record["mode"], "PAPER")
        self.assertEqual(record["side"], "DOWN")
        self.assertEqual(record["entry_price"], 0.20)
        self.assertEqual(record["shares"], 1000.0)

        ex.sell("BTC Up/Down test", 0.40)
        self.assertIsNone(self.db.load_open_position())

    def test_full_restart_roundtrip(self) -> None:
        # Simulate: buy -> restart (bagong executor) -> restore -> sell
        ex1 = PaperExecutor(self.db)
        ex1.buy("BTC Up/Down test", "DOWN", 0.20, 200.0)

        ex2 = PaperExecutor(self.db)  # "restart" — walang in-memory position
        self.assertIsNone(ex2.position)
        pos, level, msg = decide_restore(
            self.db.load_open_position(), ex2.MODE,
            dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1),
        )
        self.assertIsNotNone(pos)
        ex2.position = pos

        pnl = ex2.sell("BTC Up/Down test", 0.40)
        self.assertAlmostEqual(pnl, 200.0)  # 1000 shares × (0.40 − 0.20)
        self.assertIsNone(self.db.load_open_position())


if __name__ == "__main__":
    unittest.main()
