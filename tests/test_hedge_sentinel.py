"""Unit tests para sa StraddleCycle state machine + Hedge Sentinel.

Injected clock — lahat ng transitions deterministic at offline.

Run:  .\\venv\\Scripts\\python.exe -m pytest tests\\test_hedge_sentinel.py -v
"""
from __future__ import annotations

import unittest

from src.strategy.straddle import (
    CycleState,
    SentinelConfig,
    StraddleCycle,
)

T0 = 1_800_000_000.0
CFG = SentinelConfig(hedge_timeout_secs=90.0, hedge_max_price_cents=51,
                     hedge_retries=3, stale_cancel_secs=900.0)


def cycle(count: int = 100) -> StraddleCycle:
    return StraddleCycle(ticker="KXNBAGAME-TEST", count=count,
                         entry_cents=49, started_ts=T0, cfg=CFG)


class TestHappyPath(unittest.TestCase):
    def test_resting_then_both_fill_locks(self) -> None:
        c = cycle()
        d = c.on_tick(T0 + 5, 0, 0)
        self.assertEqual(d.action, "WAIT")
        self.assertIs(c.state, CycleState.RESTING_BOTH)

        d = c.on_tick(T0 + 60, 100, 100)
        self.assertEqual(d.action, "DONE")
        self.assertIs(c.state, CycleState.LOCKED)
        # +PnL: 100 pairs @ 49/49
        self.assertGreater(c.realized_pnl_cents(), 0)

    def test_no_fills_eventually_cancelled(self) -> None:
        c = cycle()
        d = c.on_tick(T0 + 901, 0, 0)
        self.assertEqual(d.action, "CANCEL_ALL")
        self.assertIs(c.state, CycleState.CANCELLED)
        self.assertEqual(c.realized_pnl_cents(), 0)


class TestSentinel(unittest.TestCase):
    def test_single_side_arms_sentinel(self) -> None:
        c = cycle()
        d = c.on_tick(T0 + 10, 100, 0)
        self.assertEqual(d.action, "WAIT")
        self.assertIs(c.state, CycleState.ONE_FILLED)
        self.assertEqual(c.lagging_side, "NO")

    def test_timeout_triggers_hedge(self) -> None:
        c = cycle()
        c.on_tick(T0 + 10, 100, 0)               # arm
        d = c.on_tick(T0 + 50, 100, 0)           # hindi pa timeout
        self.assertEqual(d.action, "WAIT")
        d = c.on_tick(T0 + 10 + 91, 100, 0)      # lampas 90s
        self.assertEqual(d.action, "HEDGE")
        self.assertIs(c.state, CycleState.HEDGING)
        self.assertIn("SENTINEL", d.reason)

    def test_price_drift_triggers_hedge_early(self) -> None:
        c = cycle()
        c.on_tick(T0 + 10, 100, 0)  # arm
        # 20s lang pero ang NO ask ay 55¢ na (> 51 max) — hedge agad
        d = c.on_tick(T0 + 30, 100, 0, lagging_ask_cents=55)
        self.assertEqual(d.action, "HEDGE")

    def test_hedge_fill_scratches(self) -> None:
        c = cycle()
        c.on_tick(T0 + 10, 100, 0)
        c.on_tick(T0 + 110, 100, 0)          # -> HEDGING
        d = c.on_tick(T0 + 113, 100, 100)    # hedge filled
        self.assertEqual(d.action, "DONE")
        self.assertIs(c.state, CycleState.HEDGED)
        c.mark_hedged(51)
        pnl = c.realized_pnl_cents()
        self.assertIsNotNone(pnl)
        self.assertLessEqual(pnl, 0)         # fees lang ang talo
        self.assertGreater(pnl, -500)

    def test_hedge_exhausted_goes_unhedged(self) -> None:
        c = cycle()
        c.on_tick(T0 + 10, 100, 0)
        c.on_tick(T0 + 110, 100, 0)          # attempt 0 -> HEDGING
        d1 = c.on_tick(T0 + 113, 100, 0)     # attempt 1
        self.assertEqual(d1.action, "HEDGE")
        d2 = c.on_tick(T0 + 116, 100, 0)     # attempt 2
        self.assertEqual(d2.action, "HEDGE")
        d3 = c.on_tick(T0 + 119, 100, 0)     # attempt 3 -> GIVE_UP
        self.assertEqual(d3.action, "GIVE_UP")
        self.assertIs(c.state, CycleState.UNHEDGED_HOLD)
        self.assertIsNone(c.realized_pnl_cents())  # settlement ang bahala

    def test_fills_equalize_disarms_sentinel(self) -> None:
        c = cycle()
        c.on_tick(T0 + 10, 60, 0)            # partial YES — armed
        d = c.on_tick(T0 + 20, 60, 60)       # nag-catch up ang NO (partial)
        self.assertEqual(d.action, "WAIT")
        self.assertIs(c.state, CycleState.RESTING_BOTH)
        self.assertIsNone(c.one_filled_ts)

    def test_settlement_pnl(self) -> None:
        c = cycle()
        c.on_tick(T0 + 10, 100, 0)
        c.state = CycleState.UNHEDGED_HOLD
        # Panalo: 100 contracts @ 49¢ -> payout $100, cost ~$49.44
        self.assertGreater(c.settlement_pnl_cents(won=True), 0)
        # Talo: -cost lang (~-$49.44), hindi hihigit sa entry cost + fee
        lose = c.settlement_pnl_cents(won=False)
        self.assertLess(lose, 0)
        self.assertGreaterEqual(lose, -(100 * 49 + 100))


class TestPersistence(unittest.TestCase):
    def test_roundtrip(self) -> None:
        c = cycle()
        c.on_tick(T0 + 10, 100, 0)  # ONE_FILLED state
        restored = StraddleCycle.from_dict(c.to_dict(), cfg=CFG)
        self.assertEqual(restored.ticker, c.ticker)
        self.assertIs(restored.state, CycleState.ONE_FILLED)
        self.assertEqual(restored.yes_filled, 100)
        self.assertEqual(restored.one_filled_ts, c.one_filled_ts)
        # Tuloy ang sentinel timer pagkatapos ng "restart"
        d = restored.on_tick(T0 + 10 + 95, 100, 0)
        self.assertEqual(d.action, "HEDGE")


if __name__ == "__main__":
    unittest.main()
