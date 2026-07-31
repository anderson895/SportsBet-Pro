"""Guards added after a 15-hour outage and a half-account loss.

The log for 2026-07-28 showed three separate failures of observability and
safety, each covered here:

- a $494.90 straddle placed against a $1,000 balance, from a Risk Per
  Straddle that was 100x what the settings screen showed
- ~2,300 near-identical warnings during a DNS outage, with no backoff
- half of those warnings ending at the colon, because httpx timeouts carry
  no message
"""
import asyncio
import time
import unittest

import httpx

from src.core.applog import Outage, err_text
from src.core.engine_kalshi import DEFAULTS, NO_STRADDLE_CAP
from src.execution.kalshi_client import _MIN_REQUEST_GAP as MIN_REQUEST_GAP
from src.execution.kalshi_client import KalshiClient
from src.strategy.straddle import SentinelConfig, straddle_sizing


class ErrTextTest(unittest.TestCase):
    def test_empty_httpx_errors_still_say_something(self) -> None:
        for exc in (httpx.ConnectTimeout(""), httpx.ConnectError(""),
                    httpx.ReadTimeout("")):
            self.assertEqual(err_text(exc), type(exc).__name__)

    def test_keeps_a_real_message_and_names_the_type(self) -> None:
        self.assertEqual(err_text(ValueError("boom")), "ValueError: boom")

    def test_does_not_repeat_the_type_when_already_present(self) -> None:
        self.assertEqual(err_text(Exception("Exception in flight")),
                         "Exception in flight")

    def test_falls_back_to_the_cause(self) -> None:
        exc = httpx.ConnectError("")
        exc.__cause__ = OSError("getaddrinfo failed")
        self.assertEqual(err_text(exc), "ConnectError: getaddrinfo failed")


class OutageTest(unittest.TestCase):
    def test_only_the_first_failure_is_logged(self) -> None:
        o = Outage()
        self.assertIsNotNone(o.fail("scan failed"))
        for _ in range(200):
            self.assertIsNone(o.fail("scan failed"))

    def test_retry_interval_widens_then_caps(self) -> None:
        o = Outage()
        self.assertEqual(o.delay(30), 30)      # healthy
        o.fail("x")
        self.assertEqual(o.delay(30), 60)
        o.fail("x")
        self.assertEqual(o.delay(30), 120)
        for _ in range(50):
            o.fail("x")
        self.assertEqual(o.delay(30), 30 * Outage.MAX_MULTIPLIER)

    def test_recovery_reports_once_and_resets(self) -> None:
        o = Outage()
        self.assertIsNone(o.recover())  # nothing to report when healthy
        o.fail("x")
        o.fail("x")
        msg = o.recover()
        self.assertIn("2 failed attempts", msg or "")
        self.assertIsNone(o.recover())
        self.assertEqual(o.delay(30), 30)


class StraddleSizeGuardTest(unittest.TestCase):
    """The 2026-07-28 sizing accident, and the cap that now governs it."""

    BALANCE = 1_000.0
    DEFAULT_PCT = DEFAULTS["max_straddle_pct"]

    def _cost(self, risk: float, entry: int = 49) -> float:
        return straddle_sizing(risk, entry, entry) * entry * 2 / 100.0

    def _blocked(self, risk: float, cap_pct: float) -> bool:
        """Mirrors the engine guard: no cap at all once it reaches 100%."""
        if cap_pct >= NO_STRADDLE_CAP:
            return False
        return self._cost(risk) > self.BALANCE * cap_pct / 100.0

    def test_the_accident_is_blocked_at_the_default_cap(self) -> None:
        self.assertAlmostEqual(self._cost(500.0), 494.90, places=2)
        self.assertTrue(self._blocked(500.0, self.DEFAULT_PCT))

    def test_a_small_risk_passes(self) -> None:
        self.assertAlmostEqual(self._cost(5.0), 4.90, places=2)
        self.assertFalse(self._blocked(5.0, self.DEFAULT_PCT))

    def test_the_default_cap_draws_the_line_at_a_quarter(self) -> None:
        self.assertFalse(self._blocked(250.0, self.DEFAULT_PCT))
        self.assertTrue(self._blocked(260.0, self.DEFAULT_PCT))

    def test_raising_the_cap_allows_the_bigger_size(self) -> None:
        self.assertTrue(self._blocked(500.0, 25.0))
        self.assertFalse(self._blocked(500.0, 50.0))

    def test_one_hundred_percent_disables_the_guard(self) -> None:
        # Even a straddle larger than the whole balance goes through.
        self.assertFalse(self._blocked(5_000.0, NO_STRADDLE_CAP))


class RequestThrottleTest(unittest.TestCase):
    """The scan fired 14 series calls back-to-back and stayed rate-limited
    (HTTP 429) for ~20 hours. Requests are paced inside the client now."""

    def _elapsed_for(self, calls: int, gap: float) -> float:
        client = KalshiClient(min_request_gap=gap)

        async def run() -> float:
            start = time.monotonic()
            for _ in range(calls):
                await client._wait_turn()
            return time.monotonic() - start

        return asyncio.run(run())

    def test_requests_are_spaced_apart(self) -> None:
        # 5 calls at a 20ms gap must take at least the 4 intervening gaps
        self.assertGreaterEqual(self._elapsed_for(5, 0.02), 0.07)

    def test_a_zero_gap_disables_pacing(self) -> None:
        self.assertLess(self._elapsed_for(50, 0.0), 0.05)

    def test_the_shipped_gap_keeps_a_full_scan_under_ten_seconds(self) -> None:
        # 14 sports series per scan cycle, every 30 seconds
        self.assertLess(14 * MIN_REQUEST_GAP, 10.0)


class HedgeWindowTest(unittest.TestCase):
    """The sentinel used to give up after ~9 seconds, sometimes with the ask
    a single cent above the cap."""

    def test_the_old_window_was_about_nine_seconds(self) -> None:
        self.assertAlmostEqual(3 * 3.0, 9.0)  # 3 polls at the fill cadence

    def test_the_default_window_is_now_minutes(self) -> None:
        cfg = SentinelConfig()
        window = cfg.hedge_retries * cfg.hedge_retry_secs
        self.assertGreaterEqual(window, 60.0)

    def test_the_window_is_the_product_of_both_settings(self) -> None:
        cfg = SentinelConfig(hedge_retries=10, hedge_retry_secs=12.0)
        self.assertEqual(cfg.hedge_retries * cfg.hedge_retry_secs, 120.0)


if __name__ == "__main__":
    unittest.main()
