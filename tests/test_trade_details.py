"""Pag-decode ng Kalshi game ticker para sa detail modal.

Ang mga ticker ay cryptic (KXMLBGAME-26JUL241840CHCPIT-CHC). Dapat
mabasa ng tao kung anong laro, kailan, at sino ang naglalaban — pero
kailanman ay hindi dapat mag-crash sa hindi inaasahang hugis.
"""
import unittest

from src.ui.trade_details import (
    parse_ticker,
    summarise,
    summarise_directional,
)


def _row(side, action="BUY", price=0.49, size=0.0, pnl=None):
    return {"side": side, "action": action, "price": price, "size": size,
            "pnl": pnl}


class SummariseTest(unittest.TestCase):
    def test_balanced_straddle_from_real_partial_fills(self) -> None:
        """Totoong CHCPIT fills: 28 YES at 28 NO, hati sa partials.

        Ang 6.63/0.49 + 0.23/0.49 + … ay 27.99999… sa floating point —
        dapat 28 pa rin ang labas, hindi 27, at hindi "unbalanced".
        """
        rows = [
            _row("NO", size=6.63), _row("NO", size=0.23),
            _row("NO", size=2.94), _row("NO", size=3.92),
            _row("YES", size=3.92), _row("YES", size=9.80),
            _row("PAIR", action="SETTLE", price=0.0, size=27.44, pnl=0.3149),
        ]
        got = summarise(rows)
        self.assertEqual(got["yes"], 28)
        self.assertEqual(got["no"], 28)
        self.assertEqual(got["yes"], got["no"])   # walang maling babala
        self.assertAlmostEqual(got["cost"], 27.44, places=2)
        self.assertAlmostEqual(got["pnl"], 0.3149, places=4)

    def test_settle_row_excluded_from_cost(self) -> None:
        """Ang SETTLE ay resulta, hindi pagbili — hindi dapat kasama sa
        cost o sa bilang ng contracts."""
        rows = [_row("YES", size=2.45), _row("NO", size=2.45),
                _row("PAIR", action="SETTLE", price=0.0, size=4.90, pnl=0.05)]
        got = summarise(rows)
        self.assertAlmostEqual(got["cost"], 4.90, places=2)
        self.assertEqual(got["yes"], 5)
        self.assertEqual(got["no"], 5)

    def test_open_straddle_has_no_pnl(self) -> None:
        got = summarise([_row("YES", size=2.45), _row("NO", size=2.45)])
        self.assertIsNone(got["pnl"])

    def test_one_sided_fill_is_reported_unbalanced(self) -> None:
        """Ito ang tunay na panganib — dapat malinaw na hindi pantay."""
        got = summarise([_row("YES", size=2.45)])
        self.assertEqual((got["yes"], got["no"]), (5, 0))

    def test_empty_rows(self) -> None:
        got = summarise([])
        self.assertEqual((got["yes"], got["no"], got["cost"]), (0, 0, 0.0))
        self.assertIsNone(got["pnl"])


class SummariseDirectionalTest(unittest.TestCase):
    """Polymarket mean-reversion: isang panig (UP/DOWN), entry + exit.

    Ang lumang Kalshi na summarise() ay YES/NO lang ang binibilang, kaya
    0/0 ang lumalabas para sa DOWN — dito naaayos iyon.
    """

    def test_directional_buy_then_sell_with_profit(self) -> None:
        # Totoong Polymarket trade: BUY DOWN @ 0.25, SELL @ 0.27 -> +8.86
        rows = [
            _row("DOWN", action="BUY", price=0.25, size=100.0),
            _row("DOWN", action="SELL", price=0.27, size=108.86, pnl=8.86),
        ]
        got = summarise_directional(rows)
        self.assertEqual(got["side"], "DOWN")
        self.assertEqual(got["contracts"], 400)      # 100 / 0.25
        self.assertAlmostEqual(got["avg"], 0.25, places=2)
        self.assertAlmostEqual(got["cost"], 100.0, places=2)
        self.assertAlmostEqual(got["pnl"], 8.86, places=2)

    def test_open_directional_trade_has_no_pnl(self) -> None:
        got = summarise_directional(
            [_row("UP", action="BUY", price=0.40, size=40.0)])
        self.assertEqual(got["side"], "UP")
        self.assertIsNone(got["pnl"])

    def test_empty_rows(self) -> None:
        got = summarise_directional([])
        self.assertEqual(got["side"], "")
        self.assertEqual((got["contracts"], got["cost"]), (0, 0.0))
        self.assertIsNone(got["pnl"])


class ParseTickerTest(unittest.TestCase):
    def test_decodes_a_real_mlb_ticker(self) -> None:
        got = parse_ticker("KXMLBGAME-26JUL241840CHCPIT-CHC")
        self.assertEqual(got["sport"], "Baseball — MLB")
        self.assertEqual(got["starts"], "Jul 24, 2026 18:40 UTC")
        self.assertEqual(got["matchup"], "CHC vs PIT")
        self.assertEqual(got["side_team"], "CHC")
        self.assertEqual(got["opponent"], "PIT")

    def test_two_letter_team_code(self) -> None:
        """Magkadikit ang team codes — ang YES side ang gabay sa paghati."""
        got = parse_ticker("KXMLBGAME-26JUL241845AZWSH-AZ")
        self.assertEqual(got["matchup"], "AZ vs WSH")
        self.assertEqual(got["opponent"], "WSH")

    def test_side_team_at_the_end(self) -> None:
        got = parse_ticker("KXMLBGAME-26JUL241840CHCPIT-PIT")
        self.assertEqual(got["matchup"], "CHC vs PIT")
        self.assertEqual(got["opponent"], "CHC")

    def test_soccer_series_name(self) -> None:
        got = parse_ticker("KXLIGAMXGAME-26JUL24TIJLEO-TIJ")
        self.assertEqual(got["sport"], "Soccer — Liga MX")

    def test_unknown_series_falls_back_to_raw_code(self) -> None:
        got = parse_ticker("KXCRICKET-26JUL241800INDAUS-IND")
        self.assertEqual(got["sport"], "KXCRICKET")
        self.assertEqual(got["matchup"], "IND vs AUS")

    def test_malformed_tickers_do_not_crash(self) -> None:
        for bad in ("", "GARBAGE", "A-B", "KXMLBGAME-", "---",
                    "KXMLBGAME-99ZZZ999999XX-XX"):
            got = parse_ticker(bad)
            self.assertEqual(got["ticker"], bad)
            self.assertIsInstance(got["matchup"], str)

    def test_invalid_date_keeps_teams(self) -> None:
        """Masamang petsa: walang oras, pero mababasa pa rin ang laban."""
        got = parse_ticker("KXMLBGAME-26JUL991840CHCPIT-CHC")
        self.assertEqual(got["starts"], "")
        self.assertEqual(got["matchup"], "CHC vs PIT")


if __name__ == "__main__":
    unittest.main()
