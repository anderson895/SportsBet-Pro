"""KalshiLiveExecutor — buy opens, sell closes the SAME side (mean reversion).

A fake Kalshi client records ``create_order`` calls so we can assert the
directional mapping (UP->yes buy, exit-> sell the held side) and the
dollars->cents conversion, without any network.
"""
from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.execution.kalshi_live import KalshiLiveExecutor
from src.execution.kalshi_market import KalshiBtcMarket
from src.storage.db import Database


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create_order(self, ticker, side, count, price_cents,
                           action="buy", post_only=True,
                           client_order_id=None) -> dict:
        self.calls.append(dict(
            ticker=ticker, side=side, count=count, price_cents=price_cents,
            action=action, post_only=post_only))
        return {"order_id": f"OID-{len(self.calls)}"}

    async def get_balance(self) -> float:
        return 500.0


class KalshiLiveExecutorTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self._raw = Database(Path(self._tmp.name) / "t.db")
        self.db = self._raw.scope("kalshi")
        self.client = _FakeClient()
        self.ex = KalshiLiveExecutor(self.db, self.client)
        self.ex.set_market(KalshiBtcMarket(
            ticker="KXBTCD-TEST-T64000.99", strike=64_000.99,
            question="q", expiration_ts=0.0))

    def tearDown(self) -> None:
        self._raw.close()
        self._tmp.cleanup()

    def test_buy_up_opens_a_yes_buy_in_cents(self) -> None:
        pos = asyncio.run(self.ex.buy("m", "UP", 0.16, 5.0))
        call = self.client.calls[0]
        self.assertEqual(call["action"], "buy")
        self.assertEqual(call["side"], "yes")   # UP -> yes
        self.assertEqual(call["price_cents"], 16)
        self.assertTrue(call["post_only"])
        self.assertEqual(call["count"], int(5.0 / 0.16))  # 31 contracts
        self.assertEqual(pos.side, "UP")
        self.assertAlmostEqual(pos.entry_price, 0.16)
        self.assertEqual(self.db.load_open_position()["side"], "UP")

    def test_buy_down_opens_a_no_buy(self) -> None:
        asyncio.run(self.ex.buy("m", "DOWN", 0.20, 10.0))
        call = self.client.calls[0]
        self.assertEqual(call["side"], "no")    # DOWN -> no
        self.assertEqual(call["price_cents"], 20)

    def test_sell_closes_the_held_side_and_returns_pnl(self) -> None:
        asyncio.run(self.ex.buy("m", "UP", 0.16, 5.0))
        pnl = asyncio.run(self.ex.sell("m", 0.40))
        close = self.client.calls[1]
        self.assertEqual(close["action"], "sell")
        self.assertEqual(close["side"], "yes")   # sell the SAME side we hold
        self.assertEqual(close["price_cents"], 40)
        self.assertFalse(close["post_only"])     # cross to guarantee the fill
        # 31 contracts: (0.40 - 0.16) * 31 = 7.44
        self.assertAlmostEqual(pnl, (0.40 - 0.16) * int(5.0 / 0.16), places=6)
        self.assertIsNone(self.ex.position)
        self.assertIsNone(self.db.load_open_position())

    def test_buy_rejects_risk_too_small_for_one_contract(self) -> None:
        with self.assertRaises(ValueError):
            asyncio.run(self.ex.buy("m", "UP", 0.50, 0.10))


if __name__ == "__main__":
    unittest.main()
