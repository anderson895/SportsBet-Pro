"""Paggrupo ng market rows sa game cards.

Mahalaga: hindi lahat ng laro ay 2-way. Ang soccer ay may TATLONG resulta
(panalo / TABLA / panalo). Noong ipinapakita lang ang unang dalawa,
lumalabas na "Tijuana 50% · Leon 26%" — hindi umaabot sa 100% at mukhang
sirang datos, gayong tama naman: nakatago lang ang 24% na tabla.
"""
import unittest

from src.ui.kalshi_cards import group_games


def _row(ticker, title, yes_bid, yes_ask, volume=1000, status="WATCH"):
    return {"ticker": ticker, "title": title, "yes_bid": yes_bid,
            "yes_ask": yes_ask, "volume": volume, "status": status}


class GroupGamesTest(unittest.TestCase):
    def test_two_way_game(self) -> None:
        games = group_games([
            _row("KXMLBGAME-26JUL24LAASF-SF",
                 "Los Angeles A vs San Francisco Winner? (San Francisco)",
                 70, 71, 2504455),
            _row("KXMLBGAME-26JUL24LAASF-LAA",
                 "Los Angeles A vs San Francisco Winner? (Los Angeles A)",
                 29, 30, 1862999),
        ])
        self.assertEqual(len(games), 1)
        g = games[0]
        self.assertEqual(g["matchup"], "Los Angeles A vs San Francisco")
        self.assertEqual([t for t, _ in g["teams"]],
                         ["San Francisco", "Los Angeles A"])
        self.assertAlmostEqual(sum(p for _, p in g["teams"]), 100.0, delta=1.5)

    def test_three_way_soccer_keeps_the_draw(self) -> None:
        """Totoong numero ng Kalshi: 51 + 24 + 26 = 100."""
        games = group_games([
            _row("KXLIGAMXGAME-26JUL24TIJLEO-TIJ",
                 "Tijuana de Caliente vs Leon Winner? (Tijuana de Caliente)",
                 50, 52, 618601),
            _row("KXLIGAMXGAME-26JUL24TIJLEO-TIE",
                 "Tijuana de Caliente vs Leon Winner? (Tie)", 23, 24, 58483),
            _row("KXLIGAMXGAME-26JUL24TIJLEO-LEO",
                 "Tijuana de Caliente vs Leon Winner? (Leon)", 25, 26, 273853),
        ])
        self.assertEqual(len(games), 1)
        teams = games[0]["teams"]
        self.assertEqual(len(teams), 3, "hindi dapat mawala ang tabla")
        self.assertIn("Tie", [t for t, _ in teams])
        self.assertAlmostEqual(sum(p for _, p in teams), 100.0, delta=1.5)

    def test_volume_is_the_max_across_outcomes(self) -> None:
        games = group_games([
            _row("KX-EV-A", "A vs B Winner? (A)", 50, 51, 100),
            _row("KX-EV-B", "A vs B Winner? (B)", 49, 50, 9999),
        ])
        self.assertEqual(games[0]["vol"], 9999)

    def test_ready_if_any_outcome_is_ready(self) -> None:
        games = group_games([
            _row("KX-EV-A", "A vs B Winner? (A)", 50, 51, status="WATCH"),
            _row("KX-EV-B", "A vs B Winner? (B)", 49, 50, status="READY"),
        ])
        self.assertTrue(games[0]["ready"])

    def test_representative_ticker_matches_first_outcome(self) -> None:
        """Ang g['ticker'] ang pino-poll para sa featured card, kaya dapat
        tugma ito sa teams[0] — kung hindi, maling pangalan ang lalabas."""
        games = group_games([
            _row("KX-EV-A", "A vs B Winner? (A)", 60, 61),
            _row("KX-EV-B", "A vs B Winner? (B)", 39, 40),
        ])
        self.assertEqual(games[0]["ticker"], "KX-EV-A")
        self.assertEqual(games[0]["teams"][0][0], "A")

    def test_separate_events_stay_separate(self) -> None:
        games = group_games([
            _row("KX-EV1-A", "A vs B Winner? (A)", 50, 51),
            _row("KX-EV1-B", "A vs B Winner? (B)", 49, 50),
            _row("KX-EV2-C", "C vs D Winner? (C)", 60, 61),
            _row("KX-EV2-D", "C vs D Winner? (D)", 39, 40),
        ])
        self.assertEqual(len(games), 2)
        self.assertEqual([g["matchup"] for g in games], ["A vs B", "C vs D"])


if __name__ == "__main__":
    unittest.main()
