"""Polymarket "Sync from exchange" — import real fills into the local DB.

Uses a fake client (no network, no real account) to verify the mapping,
dedup-by-trade-id, and that re-running is idempotent.
"""
from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.core.engine_poly_box import PolyBoxEngine
from src.storage.db import Database


class _FakeClient:
    def __init__(self, trades: list[dict]) -> None:
        self._trades = trades

    def get_trades(self) -> list[dict]:
        return self._trades

    def get_usdc_balance(self) -> float:
        return 123.45


def _trade(tid: str, outcome: str = "Yes", price: float = 0.49,
           size: float = 10.0, side: str = "BUY") -> dict:
    return {"id": tid, "market": "0xMKT", "outcome": outcome, "price": price,
            "size": size, "side": side, "match_time": "2026-07-27T10:00:00Z"}


class PolySyncTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self._raw = Database(Path(self._tmp.name) / "t.db")
        self.db = self._raw.scope("polymarket")
        self.engine = PolyBoxEngine(self.db)

    def tearDown(self) -> None:
        self._raw.close()
        self._tmp.cleanup()

    def _sync_with(self, trades: list[dict]) -> tuple[int, int]:
        self.engine._live = _FakeClient(trades)  # type: ignore[assignment]
        return asyncio.run(self.engine.sync_fills_from_polymarket())

    def test_imports_fills_and_maps_fields(self) -> None:
        imported, total = self._sync_with([
            _trade("T1", "Yes", 0.49, 10.0),
            _trade("T2", "No", 0.49, 10.0),
        ])
        self.assertEqual((imported, total), (2, 2))
        rows = self.db.recent_trades()
        self.assertEqual(len(rows), 2)
        sides = {r["side"] for r in rows}
        self.assertEqual(sides, {"YES", "NO"})
        row = rows[0]
        self.assertEqual(row["status"], "FILLED")
        self.assertEqual(row["market"], "0xMKT")
        self.assertAlmostEqual(row["price"], 0.49)
        self.assertAlmostEqual(row["size"], 10.0 * 0.49)  # size in dollars

    def test_rerun_is_idempotent(self) -> None:
        trades = [_trade("T1"), _trade("T2", "No")]
        self._sync_with(trades)
        imported, total = self._sync_with(trades)   # same history again
        self.assertEqual(imported, 0, "re-sync must not duplicate rows")
        self.assertEqual(total, 2)
        self.assertEqual(len(self.db.recent_trades()), 2)

    def test_new_fill_on_second_sync_is_added(self) -> None:
        self._sync_with([_trade("T1")])
        imported, _ = self._sync_with([_trade("T1"), _trade("T2", "No")])
        self.assertEqual(imported, 1)
        self.assertEqual(len(self.db.recent_trades()), 2)

    def test_sell_side_is_recorded_as_sell(self) -> None:
        self._sync_with([_trade("T9", "Yes", 0.60, 5.0, side="SELL")])
        self.assertEqual(self.db.recent_trades()[0]["action"], "SELL")

    def test_unix_match_time_is_stored_as_formattable_iso(self) -> None:
        """Polymarket returns match_time as a UNIX timestamp; storing it raw
        made the Trades table show a bare number (e.g. 1783857399)."""
        from src.ui.pages import local_datetime
        t = _trade("T5")
        t["match_time"] = "1783857399"
        self._sync_with([t])
        ts = self.db.recent_trades()[0]["ts"]
        self.assertIn("2026", ts, f"expected ISO datetime, got {ts!r}")
        shown = local_datetime(ts)
        self.assertNotEqual(shown, "1783857399")
        self.assertIn("2026", shown)

    def test_iso_match_time_is_preserved(self) -> None:
        t = _trade("T6")
        t["match_time"] = "2026-07-27T10:00:00Z"
        self._sync_with([t])
        self.assertIn("2026-07-27", self.db.recent_trades()[0]["ts"])

    # ---- realized PnL (Statistics page) --------------------------------
    # The Polymarket CLOB has no PnL endpoint, so realized PnL is derived
    # from the fills. Without it the Statistics page stayed at 0.

    def test_closed_round_trip_books_realized_pnl(self) -> None:
        # buy 10 @ 0.47 = 4.70 cost; sell 10 @ 0.46 = 4.60 -> -0.10
        self._sync_with([
            _trade("B1", "Up", 0.47, 10.0, "BUY"),
            _trade("S1", "Up", 0.46, 10.0, "SELL"),
        ])
        closes = [r for r in self.db.recent_trades() if r["action"] == "CLOSE"]
        self.assertEqual(len(closes), 1)
        self.assertAlmostEqual(closes[0]["pnl"], -0.10, places=4)
        stats = self.db.trade_stats()
        self.assertEqual(stats["closed"], 1)
        self.assertEqual(stats["losses"], 1)
        self.assertAlmostEqual(self.db.total_pnl(), -0.10, places=4)

    def test_open_position_books_no_pnl(self) -> None:
        self._sync_with([_trade("B2", "Down", 0.28, 5.0, "BUY")])
        self.assertEqual(
            [r for r in self.db.recent_trades() if r["action"] == "CLOSE"], [])
        self.assertEqual(self.db.trade_stats()["closed"], 0)

    def test_winning_round_trip_counts_as_a_win(self) -> None:
        self._sync_with([
            _trade("B3", "Yes", 0.40, 10.0, "BUY"),
            _trade("S3", "Yes", 0.55, 10.0, "SELL"),
        ])
        self.assertAlmostEqual(self.db.total_pnl(), 1.50, places=4)
        self.assertEqual(self.db.trade_stats()["wins"], 1)

    def test_partial_sell_books_only_the_matched_portion(self) -> None:
        # buy 10 @ 0.40, sell only 4 @ 0.50 -> realized = 4*(0.50-0.40) = 0.40
        self._sync_with([
            _trade("B4", "Yes", 0.40, 10.0, "BUY"),
            _trade("S4", "Yes", 0.50, 4.0, "SELL"),
        ])
        self.assertAlmostEqual(self.db.total_pnl(), 0.40, places=4)

    def test_realized_pnl_is_not_double_counted_on_resync(self) -> None:
        trades = [_trade("B5", "Up", 0.47, 10.0, "BUY"),
                  _trade("S5", "Up", 0.46, 10.0, "SELL")]
        self._sync_with(trades)
        self._sync_with(trades)   # same history again
        self.assertEqual(self.db.trade_stats()["closed"], 1)
        self.assertAlmostEqual(self.db.total_pnl(), -0.10, places=4)

    def test_trade_without_id_is_skipped(self) -> None:
        imported, _ = self._sync_with([{"market": "0xM", "outcome": "Yes",
                                        "price": 0.5, "size": 1.0}])
        self.assertEqual(imported, 0)


if __name__ == "__main__":
    unittest.main()
