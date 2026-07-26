"""Reconcile-on-start: linisin ang orphaned resting orders sa Kalshi.

Bakit mahalaga: kapag na-restart (o nag-crash) ang app habang may
nakalatag na LIVE straddle, naiiwan ang totoong orders sa exchange pero
bagong walang-laman na executor ang bumubukas — kaya wala nang
nagba-bantay o makakakansela sa kanila (orphaned real-money exposure).
Pagka-START, dapat ito ang mag-cancel ng mga orphan, pero IWAN ang
orders ng na-restore pang cycle.
"""
import asyncio
import tempfile
import types
import unittest
from pathlib import Path

from src.core.engine_kalshi import KalshiEngine
from src.execution.kalshi_live import KalshiLiveExecutor
from src.execution.kalshi_paper import KalshiPaperExecutor
from src.storage.db import Database


class _FakeClient:
    def __init__(self, resting=None, raise_on_list=False) -> None:
        self._resting = resting or []
        self._raise = raise_on_list
        self.cancelled: list[str] = []

    async def get_resting_orders(self, ticker=None) -> list[dict]:
        if self._raise:
            raise RuntimeError("network down")
        return list(self._resting)

    async def cancel_order(self, order_id: str) -> dict:
        self.cancelled.append(order_id)
        return {"order_id": order_id}


def _order(ticker: str, oid: str) -> dict:
    return {"ticker": ticker, "order_id": oid, "status": "resting"}


class ReconcileRestingOrdersTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = Database(Path(tempfile.mkdtemp()) / "t.db").scope("kalshi")
        self.engine = KalshiEngine(self.db)

    def _wire(self, client, cycle_ticker=None) -> None:
        self.engine.executor = KalshiLiveExecutor(client)
        self.engine._client = client
        self.engine._cycle = (
            types.SimpleNamespace(ticker=cycle_ticker)
            if cycle_ticker else None
        )

    def test_cancels_all_when_no_active_cycle(self) -> None:
        client = _FakeClient(resting=[
            _order("ATLBAL-ATL", "a1"), _order("ATLBAL-ATL", "a2"),
            _order("HOUCWS-CWS", "h1"),
        ])
        self._wire(client, cycle_ticker=None)
        asyncio.run(self.engine._reconcile_resting_orders())
        self.assertEqual(set(client.cancelled), {"a1", "a2", "h1"})

    def test_keeps_restored_cycle_orders_cancels_the_rest(self) -> None:
        client = _FakeClient(resting=[
            _order("ATLBAL-ATL", "keep1"), _order("ATLBAL-ATL", "keep2"),
            _order("HOUCWS-CWS", "orphan1"),
        ])
        self._wire(client, cycle_ticker="ATLBAL-ATL")
        asyncio.run(self.engine._reconcile_resting_orders())
        # Iwan ang cycle ticker, kanselahin lang ang orphan
        self.assertEqual(client.cancelled, ["orphan1"])

    def test_no_resting_orders_is_a_noop(self) -> None:
        client = _FakeClient(resting=[])
        self._wire(client, cycle_ticker=None)
        asyncio.run(self.engine._reconcile_resting_orders())
        self.assertEqual(client.cancelled, [])

    def test_paper_executor_is_skipped(self) -> None:
        """Walang totoong order sa paper mode — huwag tumawag sa exchange."""
        client = _FakeClient(resting=[_order("X", "x1")])
        self.engine.executor = KalshiPaperExecutor()
        self.engine._client = client
        self.engine._cycle = None
        asyncio.run(self.engine._reconcile_resting_orders())
        self.assertEqual(client.cancelled, [])

    def test_list_failure_is_safe(self) -> None:
        """Kung pumalya ang query, huwag mag-crash ang buong start."""
        client = _FakeClient(raise_on_list=True)
        self._wire(client, cycle_ticker=None)
        asyncio.run(self.engine._reconcile_resting_orders())  # walang exception
        self.assertEqual(client.cancelled, [])


if __name__ == "__main__":
    unittest.main()
