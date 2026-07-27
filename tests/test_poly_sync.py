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

    def test_trade_without_id_is_skipped(self) -> None:
        imported, _ = self._sync_with([{"market": "0xM", "outcome": "Yes",
                                        "price": 0.5, "size": 1.0}])
        self.assertEqual(imported, 0)


if __name__ == "__main__":
    unittest.main()
