"""Pag-import ng realized PnL mula sa Kalshi positions.

Bakit ito kailangan: ang /portfolio/fills ay nagsasabi lang ng BINILI
natin — wala roon ang kita. Ang realized PnL ay nasa /portfolio/positions.
Kung hindi ito kukunin, $0.00 ang ipapakita ng Statistics kahit kumita ang
bot — nangyayari ito kapag na-restart ang app bago matapos ang cycle at
hindi nasulat ng bot ang sariling SETTLE row.
"""
import tempfile
import unittest
from pathlib import Path

from src.core.engine_kalshi import KalshiEngine, _dollars
from src.storage.db import Database


def _pos(ticker, position="0.00", realized="0.0", fees="0.0",
         traded="0.0", ts="2026-07-24T22:44:08.5Z"):
    return {
        "ticker": ticker,
        "position_fp": position,
        "realized_pnl_dollars": realized,
        "fees_paid_dollars": fees,
        "total_traded_dollars": traded,
        "last_updated_ts": ts,
    }


def _settle(ticker, result, yes_count="5.00", no_count="5.00",
            yes_cost="2.450000", no_cost="2.450000", fee="0.0",
            ts="2026-07-25T05:27:26.4Z"):
    """Isang /portfolio/settlements row (hugis ng totoong Kalshi response)."""
    return {
        "ticker": ticker,
        "market_result": result,
        "yes_count_fp": yes_count,
        "no_count_fp": no_count,
        "yes_total_cost_dollars": yes_cost,
        "no_total_cost_dollars": no_cost,
        "fee_cost": fee,
        "settled_time": ts,
    }


class DollarsTest(unittest.TestCase):
    def test_parses_fixed_point_strings(self) -> None:
        self.assertAlmostEqual(_dollars({"x": "0.560000"}, "x"), 0.56)
        self.assertAlmostEqual(_dollars({"x": "27.440000"}, "x"), 27.44)
        self.assertAlmostEqual(_dollars({"x": "5.00"}, "x"), 5.0)

    def test_missing_or_bad_values_are_zero(self) -> None:
        self.assertEqual(_dollars({}, "x"), 0.0)
        self.assertEqual(_dollars({"x": ""}, "x"), 0.0)
        self.assertEqual(_dollars({"x": None}, "x"), 0.0)
        self.assertEqual(_dollars({"x": "abc"}, "x"), 0.0)


class ImportRealizedPnlTest(unittest.TestCase):
    def setUp(self) -> None:
        base = Database(Path(tempfile.mkdtemp()) / "t.db")
        self.db = base.scope("kalshi")
        self.engine = KalshiEngine(self.db)

    def test_records_net_pnl_after_fees(self) -> None:
        """Totoong numero mula sa account: realized 0.56, fees 0.2451."""
        n = self.engine._import_realized_pnl([
            _pos("CHCPIT-CHC", realized="0.560000", fees="0.245100",
                 traded="27.440000"),
        ])
        self.assertEqual(n, 1)
        rows = self.db.recent_trades()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action"], "SETTLE")
        self.assertAlmostEqual(rows[0]["pnl"], 0.3149, places=4)
        self.assertAlmostEqual(rows[0]["size"], 27.44, places=2)
        self.assertAlmostEqual(self.db.total_pnl(), 0.3149, places=4)

    def test_skips_positions_still_open(self) -> None:
        """position != 0 = hindi pa tapos; huwag pang magtala ng PnL."""
        n = self.engine._import_realized_pnl([
            _pos("OPEN-ONE", position="5.00", realized="0.10", fees="0.04"),
        ])
        self.assertEqual(n, 0)
        self.assertEqual(self.db.recent_trades(), [])

    def test_skips_markets_with_no_activity(self) -> None:
        n = self.engine._import_realized_pnl([_pos("QUIET", traded="0.0")])
        self.assertEqual(n, 0)

    def test_is_idempotent(self) -> None:
        """Ligtas pindutin ang Sync nang paulit-ulit — walang dobleng row."""
        positions = [_pos("M", realized="0.10", fees="0.0438", traded="4.90")]
        self.assertEqual(self.engine._import_realized_pnl(positions), 1)
        self.assertEqual(self.engine._import_realized_pnl(positions), 0)
        self.assertEqual(len(self.db.recent_trades()), 1)
        self.assertAlmostEqual(self.db.total_pnl(), 0.0562, places=4)

    def test_updates_when_realized_pnl_changes(self) -> None:
        """Kung nadagdagan ang position, i-update — huwag magdagdag ng row."""
        self.engine._import_realized_pnl(
            [_pos("M", realized="0.10", fees="0.04", traded="4.90")]
        )
        self.engine._import_realized_pnl(
            [_pos("M", realized="0.30", fees="0.09", traded="14.70")]
        )
        rows = self.db.recent_trades()
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["pnl"], 0.21, places=4)
        self.assertAlmostEqual(rows[0]["size"], 14.70, places=2)

    def test_handles_a_loss(self) -> None:
        n = self.engine._import_realized_pnl([
            _pos("BAD", realized="-1.500000", fees="0.100000", traded="9.80"),
        ])
        self.assertEqual(n, 1)
        self.assertAlmostEqual(self.db.total_pnl(), -1.60, places=4)

    def test_ignores_rows_without_ticker(self) -> None:
        self.assertEqual(
            self.engine._import_realized_pnl([{"realized_pnl_dollars": "1"}]), 0
        )

    def test_two_markets_sum_to_account_total(self) -> None:
        """Dapat tumugma sa totoong +$0.3711 na kita ng account."""
        n = self.engine._import_realized_pnl([
            _pos("AZWSH-AZ", realized="0.100000", fees="0.043800",
                 traded="4.90"),
            _pos("CHCPIT-CHC", realized="0.560000", fees="0.245100",
                 traded="27.44"),
        ])
        self.assertEqual(n, 2)
        self.assertAlmostEqual(self.db.total_pnl(), 0.3711, places=4)


class ImportSettlementsTest(unittest.TestCase):
    """Ang settled na market ay INAALIS sa /portfolio/positions, kaya walang
    PnL na malalaman doon — dito, mula sa /portfolio/settlements, kinukuha
    ang totoong kita ng bawat natapos nang straddle."""

    def setUp(self) -> None:
        base = Database(Path(tempfile.mkdtemp()) / "t.db")
        self.db = base.scope("kalshi")
        self.engine = KalshiEngine(self.db)

    def test_records_pnl_for_a_yes_result(self) -> None:
        """28-pair straddle, CHC nanalo: 28×$1 − $27.44 − $0.2451 = +0.3149."""
        n = self.engine._import_settlements([
            _settle("CHCPIT-CHC", "yes", yes_count="28.00", no_count="28.00",
                    yes_cost="13.720000", no_cost="13.720000",
                    fee="0.245100"),
        ])
        self.assertEqual(n, 1)
        rows = self.db.recent_trades()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action"], "SETTLE")
        self.assertAlmostEqual(rows[0]["pnl"], 0.3149, places=4)
        self.assertAlmostEqual(rows[0]["size"], 27.44, places=2)

    def test_records_pnl_for_a_no_result(self) -> None:
        """Result 'no' — ang NO count ang nagbabayad: 5 − 4.90 − 0.0438."""
        n = self.engine._import_settlements([
            _settle("LAASF-LAA", "no", fee="0.043800"),
        ])
        self.assertEqual(n, 1)
        self.assertAlmostEqual(self.db.total_pnl(), 0.0562, places=4)

    def test_all_four_real_settlements_sum_up(self) -> None:
        """Totoong account: apat na settlement -> +$0.5273."""
        n = self.engine._import_settlements([
            _settle("CHCPIT-CHC", "yes", yes_count="28.00", no_count="28.00",
                    yes_cost="13.720000", no_cost="13.720000",
                    fee="0.245100"),
            _settle("AZWSH-AZ", "yes", fee="0.043800"),
            _settle("TIJLEO-TIJ", "yes", fee="0.000000"),
            _settle("LAASF-LAA", "no", fee="0.043800"),
        ])
        self.assertEqual(n, 4)
        self.assertAlmostEqual(self.db.total_pnl(), 0.5273, places=4)

    def test_skips_unresolved_markets(self) -> None:
        n = self.engine._import_settlements([_settle("PENDING", "")])
        self.assertEqual(n, 0)
        self.assertEqual(self.db.recent_trades(), [])

    def test_is_idempotent(self) -> None:
        """Ligtas i-sync nang paulit-ulit — walang dobleng row."""
        rows = [_settle("AZWSH-AZ", "yes", fee="0.043800")]
        self.assertEqual(self.engine._import_settlements(rows), 1)
        self.assertEqual(self.engine._import_settlements(rows), 0)
        self.assertEqual(len(self.db.recent_trades()), 1)

    def test_does_not_double_count_with_positions(self) -> None:
        """Parehong meta key sa _import_realized_pnl — kung nauna ang isa,
        hindi na magdadagdag ang isa pa (i-update lang kung nagbago)."""
        self.engine._import_realized_pnl(
            [_pos("AZWSH-AZ", realized="0.10", fees="0.0438", traded="4.90")]
        )
        added = self.engine._import_settlements(
            [_settle("AZWSH-AZ", "yes", fee="0.043800")]
        )
        self.assertEqual(added, 0)
        self.assertEqual(len(self.db.recent_trades()), 1)
        self.assertAlmostEqual(self.db.total_pnl(), 0.0562, places=4)

    def test_ignores_rows_without_ticker(self) -> None:
        self.assertEqual(
            self.engine._import_settlements([{"market_result": "yes"}]), 0
        )


if __name__ == "__main__":
    unittest.main()
