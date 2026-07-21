"""Mocked tests para sa live Polymarket integration.

Walang totoong network calls dito — lahat naka-mock. Ang tine-test:
tamang paggamit ng py-clob-client API, parsing ng Gamma API responses,
at trade recording ng LiveExecutor.

Run:  .\\venv\\Scripts\\python.exe -m unittest tests.test_polymarket -v
"""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from py_clob_client_v2 import Side

from src.execution.polymarket import (
    DailyBtcMarket,
    LiveExecutor,
    PolymarketClient,
    PolymarketError,
    find_daily_btc_market,
)
from src.storage.db import Database


def make_client(mock_clob: MagicMock) -> PolymarketClient:
    return PolymarketClient(
        private_key="0xfake", funder="0xfunder", clob_client=mock_clob
    )


class TestPolymarketClient(unittest.TestCase):
    def test_connect_derives_and_sets_creds(self) -> None:
        clob = MagicMock()
        clob.create_or_derive_api_key.return_value = {"apiKey": "k"}
        client = make_client(clob)
        client.connect()
        clob.create_or_derive_api_key.assert_called_once()
        clob.set_api_creds.assert_called_once_with({"apiKey": "k"})

    def test_usdc_balance_parses_6_decimals(self) -> None:
        clob = MagicMock()
        clob.get_balance_allowance.return_value = {"balance": "250000000"}
        self.assertEqual(make_client(clob).get_usdc_balance(), 250.0)
        # Sig 1 (default): WALANG explicit signature_type sa request
        params = clob.get_balance_allowance.call_args[0][0]
        self.assertEqual(params.signature_type, -1)

    def test_usdc_balance_deposit_wallet_passes_sig_type(self) -> None:
        # Deposit Wallet accounts (sig 3): dapat KASAMA ang signature_type
        # sa balance request — kung hindi, 0.00 ang ibabalik ng server
        clob = MagicMock()
        clob.get_balance_allowance.return_value = {"balance": "96580000"}
        client = PolymarketClient(
            private_key="0xfake", funder="0xdeposit",
            signature_type=3, clob_client=clob,
        )
        self.assertAlmostEqual(client.get_usdc_balance(), 96.58)
        params = clob.get_balance_allowance.call_args[0][0]
        self.assertEqual(params.signature_type, 3)

    def test_best_prices_from_order_book(self) -> None:
        # CLOB V2: dict ang order book response
        clob = MagicMock()
        clob.get_order_book.return_value = {
            "bids": [{"price": "0.18"}, {"price": "0.19"}],
            "asks": [{"price": "0.22"}, {"price": "0.21"}],
        }
        bid, ask = make_client(clob).get_best_prices("tok")
        self.assertEqual(bid, 0.19)  # pinakamataas na bid
        self.assertEqual(ask, 0.21)  # pinakamababang ask

    def test_best_prices_v1_object_book(self) -> None:
        # Backward-compat: V1-style object na may .bids/.asks attrs
        clob = MagicMock()
        clob.get_order_book.return_value = SimpleNamespace(
            bids=[SimpleNamespace(price="0.18")],
            asks=[SimpleNamespace(price="0.22")],
        )
        self.assertEqual(make_client(clob).get_best_prices("tok"), (0.18, 0.22))

    def test_best_prices_empty_book(self) -> None:
        clob = MagicMock()
        clob.get_order_book.return_value = {"bids": [], "asks": []}
        self.assertEqual(make_client(clob).get_best_prices("tok"), (None, None))

    def test_buy_limit_computes_shares(self) -> None:
        clob = MagicMock()
        clob.create_and_post_order.return_value = {"success": True, "orderID": "ord1"}
        order_id = make_client(clob).buy_limit("tok", price=0.20, usdc=20.0)
        self.assertEqual(order_id, "ord1")
        args = clob.create_and_post_order.call_args[0][0]
        self.assertEqual(args.token_id, "tok")
        self.assertEqual(args.price, 0.20)
        self.assertEqual(args.size, 100.0)  # 20 USDC / 0.20 = 100 shares
        self.assertEqual(args.side, Side.BUY)

    def test_sell_limit(self) -> None:
        clob = MagicMock()
        clob.create_and_post_order.return_value = {"success": True, "orderID": "ord2"}
        make_client(clob).sell_limit("tok", price=0.45, shares=100.0)
        args = clob.create_and_post_order.call_args[0][0]
        self.assertEqual(args.side, Side.SELL)
        self.assertEqual(args.size, 100.0)

    def test_rejected_order_raises(self) -> None:
        clob = MagicMock()
        clob.create_and_post_order.return_value = {
            "success": False, "errorMsg": "not enough balance",
        }
        with self.assertRaises(PolymarketError):
            make_client(clob).buy_limit("tok", 0.20, 20.0)


class FakeResponse:
    def __init__(self, data: object) -> None:
        self._data = data

    def raise_for_status(self) -> None:
        pass

    def json(self) -> object:
        return self._data


class TestMarketDiscovery(unittest.TestCase):
    def test_finds_and_maps_tokens(self) -> None:
        http = MagicMock()
        http.get.return_value = FakeResponse([{
            "question": "Bitcoin Up or Down on July 11?",
            "outcomes": '["Down", "Up"]',           # sadyang baligtad ang order
            "clobTokenIds": '["tok_down", "tok_up"]',
        }])
        market = find_daily_btc_market(dt.date(2026, 7, 11), http_client=http)
        # Tamang slug ang hiniling — may year suffix (verified 2026-07-11)
        self.assertIn("bitcoin-up-or-down-on-july-11-2026",
                      str(http.get.call_args))
        # Tamang mapping kahit baligtad ang outcomes order
        self.assertEqual(market.token_up, "tok_up")
        self.assertEqual(market.token_down, "tok_down")
        self.assertEqual(market.token_for("DOWN"), "tok_down")

    def test_falls_back_to_legacy_slug_without_year(self) -> None:
        http = MagicMock()
        http.get.side_effect = [
            FakeResponse([]),  # walang market sa year slug
            FakeResponse([{
                "question": "Bitcoin Up or Down on July 11?",
                "outcomes": '["Up", "Down"]',
                "clobTokenIds": '["tok_up", "tok_down"]',
            }]),
        ]
        market = find_daily_btc_market(dt.date(2026, 7, 11), http_client=http)
        self.assertEqual(market.token_up, "tok_up")
        self.assertEqual(http.get.call_count, 2)
        # Ang pangalawang tawag ay ang legacy slug na walang year
        legacy_call = str(http.get.call_args_list[1])
        self.assertIn("bitcoin-up-or-down-on-july-11", legacy_call)
        self.assertNotIn("-2026", legacy_call)

    def test_no_market_found_raises(self) -> None:
        http = MagicMock()
        http.get.return_value = FakeResponse([])
        with self.assertRaises(PolymarketError):
            find_daily_btc_market(dt.date(2026, 7, 11), http_client=http)

    def test_unexpected_outcomes_raises(self) -> None:
        http = MagicMock()
        http.get.return_value = FakeResponse([{
            "question": "?", "outcomes": '["Yes", "No"]',
            "clobTokenIds": '["a", "b"]',
        }])
        with self.assertRaises(PolymarketError):
            find_daily_btc_market(dt.date(2026, 7, 11), http_client=http)


class TestLiveExecutor(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._raw_db = Database(Path(self._tmp.name) / "test.db")
        self.db = self._raw_db.scope("polymarket")
        self.client = MagicMock(spec=PolymarketClient)
        self.executor = LiveExecutor(self.db, self.client)
        self.executor.set_market(
            DailyBtcMarket("BTC Jul 11?", token_up="tok_up", token_down="tok_down")
        )

    def tearDown(self) -> None:
        self._raw_db.close()
        self._tmp.cleanup()

    def test_buy_posts_order_and_records_trade(self) -> None:
        self.client.buy_limit.return_value = "ord1"
        pos = self.executor.buy("BTC [LIVE]", "DOWN", share_price=0.20, usdc=20.0)
        self.client.buy_limit.assert_called_once_with("tok_down", 0.20, 20.0)
        self.assertEqual(pos.shares, 100.0)
        trades = self.db.recent_trades()
        self.assertEqual(trades[0]["action"], "BUY")
        self.assertEqual(trades[0]["side"], "DOWN")

    def test_sell_computes_pnl_and_clears_position(self) -> None:
        self.client.buy_limit.return_value = "ord1"
        self.client.sell_limit.return_value = "ord2"
        self.executor.buy("BTC [LIVE]", "DOWN", 0.20, 20.0)
        pnl = self.executor.sell("BTC [LIVE]", share_price=0.45)
        self.client.sell_limit.assert_called_once_with("tok_down", 0.45, 100.0)
        self.assertAlmostEqual(pnl, 25.0)  # 100 shares x (0.45 - 0.20)
        self.assertIsNone(self.executor.position)
        self.assertAlmostEqual(self.db.total_pnl(), 25.0)


if __name__ == "__main__":
    unittest.main()
