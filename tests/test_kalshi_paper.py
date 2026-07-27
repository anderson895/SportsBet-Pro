"""Unit tests para sa Kalshi paper executor (simulated fills).

Canned orderbook snapshots — walang network.

Run:  .\\venv\\Scripts\\python.exe -m pytest tests\\test_kalshi_paper.py -v
"""
from __future__ import annotations

import asyncio
import unittest

from src.execution.kalshi_client import best_prices_from_orderbook
from src.execution.kalshi_paper import KalshiPaperExecutor


def run(coro):
    return asyncio.run(coro)


class TestPaperFills(unittest.TestCase):
    def setUp(self) -> None:
        self.ex = KalshiPaperExecutor()
        run(self.ex.place_straddle("KXTEST", 49, 100))

    def test_no_fill_when_ask_above_bid(self) -> None:
        # Ask 51¢ > ang 49¢ resting bid natin — walang fill
        self.ex.on_book({"yes_ask": 51, "no_ask": 51})
        self.ex.on_book({"yes_ask": 51, "no_ask": 51})
        self.assertEqual(run(self.ex.get_fills("KXTEST")), (0, 0))

    def test_fill_requires_two_consecutive_sightings(self) -> None:
        # Unang sighting sa <=49 — hindi pa fill (persistence rule)
        self.ex.on_book({"yes_ask": 49, "no_ask": 51})
        self.assertEqual(run(self.ex.get_fills("KXTEST")), (0, 0))
        # Pangalawang sunod na sighting — fill na
        self.ex.on_book({"yes_ask": 49, "no_ask": 51})
        self.assertEqual(run(self.ex.get_fills("KXTEST")), (100, 0))

    def test_flicker_does_not_fill(self) -> None:
        self.ex.on_book({"yes_ask": 49, "no_ask": 51})   # touch
        self.ex.on_book({"yes_ask": 52, "no_ask": 51})   # bounce pabalik
        self.ex.on_book({"yes_ask": 49, "no_ask": 51})   # touch ulit (1st)
        self.assertEqual(run(self.ex.get_fills("KXTEST")), (0, 0))

    def test_both_sides_fill(self) -> None:
        book = {"yes_ask": 49, "no_ask": 49}
        self.ex.on_book(book)
        self.ex.on_book(book)
        self.assertEqual(run(self.ex.get_fills("KXTEST")), (100, 100))

    def test_cancel_stops_fills(self) -> None:
        run(self.ex.cancel("KXTEST", "NO"))
        book = {"yes_ask": 49, "no_ask": 49}
        self.ex.on_book(book)
        self.ex.on_book(book)
        self.assertEqual(run(self.ex.get_fills("KXTEST")), (100, 0))

    def test_hedge_fills_at_or_below_max(self) -> None:
        filled = run(self.ex.hedge("KXTEST", "NO", 51, 100,
                                   prices={"no_ask": 51}))
        self.assertEqual(filled, 100)
        self.assertEqual(run(self.ex.get_fills("KXTEST")), (0, 100))

    def test_hedge_refuses_above_max(self) -> None:
        filled = run(self.ex.hedge("KXTEST", "NO", 51, 100,
                                   prices={"no_ask": 53}))
        self.assertEqual(filled, 0)


class TestOrderbookParsing(unittest.TestCase):
    def test_best_prices(self) -> None:
        book = {"yes": [[45, 100], [48, 50]], "no": [[47, 200], [50, 10]]}
        prices = best_prices_from_orderbook(book)
        self.assertEqual(prices["yes_bid"], 48)
        self.assertEqual(prices["no_bid"], 50)
        # Implied asks: 100 - kabilang bid
        self.assertEqual(prices["yes_ask"], 50)
        self.assertEqual(prices["no_ask"], 52)

    def test_empty_book(self) -> None:
        prices = best_prices_from_orderbook({"yes": [], "no": None})
        self.assertIsNone(prices["yes_bid"])
        self.assertIsNone(prices["yes_ask"])

    def test_new_dollars_format(self) -> None:
        # Bagong Kalshi API (orderbook_fp): dollar-string levels
        book = {
            "yes_dollars": [["0.0100", "847500.00"], ["0.3800", "45.00"]],
            "no_dollars": [["0.0100", "920812.85"], ["0.6000", "45.00"]],
        }
        prices = best_prices_from_orderbook(book)
        self.assertEqual(prices["yes_bid"], 38)
        self.assertEqual(prices["no_bid"], 60)
        self.assertEqual(prices["yes_ask"], 40)   # 100 - 60
        self.assertEqual(prices["no_ask"], 62)    # 100 - 38


if __name__ == "__main__":
    unittest.main()
