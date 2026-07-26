"""Trades/Logs display: local time + walang dobleng row.

Dalawang problemang binabantayan dito:
1. UTC ang naka-imbak na timestamps, pero LOCAL ang ginagamit ng mga live
   log entry — magkahalo ang oras sa parehong table kung hindi ico-convert.
2. Ang bot ay nagtatala ng placement row ("RESTING"), at ang sync ay
   nagdadagdag ng totoong fills — kaya lumalabas nang DALAWANG beses ang
   parehong straddle at nadodoble ang size.
"""
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from src.storage.db import Database
from src.ui.pages import local_datetime, local_time


class LocalTimeTest(unittest.TestCase):
    def test_converts_utc_to_local(self) -> None:
        # 22:33:38 UTC -> anuman ang local offset ng makina
        expected = (
            dt.datetime(2026, 7, 24, 22, 33, 38, tzinfo=dt.timezone.utc)
            .astimezone().strftime("%H:%M:%S")
        )
        self.assertEqual(local_time("2026-07-24T22:33:38+00:00"), expected)

    def test_handles_kalshi_z_suffix_with_microseconds(self) -> None:
        """Ang Kalshi ay nagbabalik ng "…Z" na may microseconds — ibang
        hugis sa isinusulat natin, pero dapat pareho ang resulta."""
        ours = local_time("2026-07-24T22:44:08+00:00")
        theirs = local_time("2026-07-24T22:44:08.505604Z")
        self.assertEqual(ours, theirs)

    def test_naive_timestamp_assumed_utc(self) -> None:
        expected = (
            dt.datetime(2026, 7, 24, 12, 0, 0, tzinfo=dt.timezone.utc)
            .astimezone().strftime("%H:%M:%S")
        )
        self.assertEqual(local_time("2026-07-24T12:00:00"), expected)

    def test_unparseable_degrades_gracefully(self) -> None:
        """Hindi dapat mag-crash ang buong table dahil sa isang masamang
        timestamp — ibabalik ang hilaw na hiwa kaysa magkamali ng oras."""
        self.assertEqual(local_time("2026-07-24T99:99:99+00:00"), "99:99:99")
        self.assertEqual(local_time(""), "")
        self.assertIsInstance(local_time("garbage"), str)


class LocalDateTimeTest(unittest.TestCase):
    """Trades table: petsa + 12-hour AM/PM (mas madaling basahin)."""

    def test_includes_date_and_12hour_ampm(self) -> None:
        expected = (
            dt.datetime(2026, 7, 26, 21, 27, 36, tzinfo=dt.timezone.utc)
            .astimezone().strftime("%b %d, %Y  %I:%M:%S %p")
        )
        got = local_datetime("2026-07-26T21:27:36+00:00")
        self.assertEqual(got, expected)
        self.assertRegex(got, r"(AM|PM)$")            # may AM/PM
        self.assertRegex(got, r"^[A-Z][a-z]{2} \d{2}, \d{4}")  # may petsa

    def test_handles_kalshi_z_suffix(self) -> None:
        ours = local_datetime("2026-07-24T22:44:08+00:00")
        theirs = local_datetime("2026-07-24T22:44:08.505604Z")
        self.assertEqual(ours, theirs)

    def test_unparseable_returns_raw(self) -> None:
        self.assertEqual(local_datetime("garbage"), "garbage")
        self.assertEqual(local_datetime(""), "")


class SupersedeOpenTradesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = Database(Path(tempfile.mkdtemp()) / "t.db").scope("kalshi")

    def test_open_placement_row_is_hidden_once_fills_arrive(self) -> None:
        self.db.add_trade(market="AZWSH-AZ", side="YES", action="BUY",
                          price=0.49, size=2.45, status="OPEN")
        self.db.add_trade(market="AZWSH-AZ", side="YES", action="BUY",
                          price=0.49, size=2.45, status="FILLED",
                          meta="kalshi_fill:abc")

        changed = self.db.supersede_open_trades("AZWSH-AZ", "YES")
        self.assertEqual(changed, 1)

        statuses = [r["status"] for r in self.db.recent_trades()]
        self.assertIn("SUPERSEDED", statuses)   # nasa DB pa (audit)
        self.assertIn("FILLED", statuses)
        self.assertNotIn("OPEN", statuses)      # wala nang doble

    def test_only_touches_matching_market_and_side(self) -> None:
        self.db.add_trade(market="AZWSH-AZ", side="YES", action="BUY",
                          price=0.49, size=2.45, status="OPEN")
        self.db.add_trade(market="AZWSH-AZ", side="NO", action="BUY",
                          price=0.49, size=2.45, status="OPEN")
        self.db.add_trade(market="OTHER-XX", side="YES", action="BUY",
                          price=0.49, size=2.45, status="OPEN")

        self.assertEqual(self.db.supersede_open_trades("AZWSH-AZ", "YES"), 1)
        remaining = {(r["market"], r["side"]) for r in self.db.recent_trades()
                     if r["status"] == "OPEN"}
        self.assertEqual(remaining, {("AZWSH-AZ", "NO"), ("OTHER-XX", "YES")})

    def test_does_not_touch_already_filled_rows(self) -> None:
        self.db.add_trade(market="M", side="YES", action="BUY", price=0.49,
                          size=1.0, status="FILLED")
        self.assertEqual(self.db.supersede_open_trades("M", "YES"), 0)

    def test_scoped_per_exchange(self) -> None:
        base = Database(Path(tempfile.mkdtemp()) / "t2.db")
        k, p = base.scope("kalshi"), base.scope("polymarket")
        k.add_trade(market="M", side="YES", action="BUY", price=0.49,
                    size=1.0, status="OPEN")
        p.add_trade(market="M", side="YES", action="BUY", price=0.49,
                    size=1.0, status="OPEN")
        self.assertEqual(k.supersede_open_trades("M", "YES"), 1)
        # Hindi dapat nagalaw ang kabilang exchange
        self.assertEqual([r["status"] for r in p.recent_trades()], ["OPEN"])


if __name__ == "__main__":
    unittest.main()
