"""Guards added after a 15-hour outage and a half-account loss.

The log for 2026-07-28 showed three separate failures of observability and
safety, each covered here:

- a $494.90 straddle placed against a $1,000 balance, from a Risk Per
  Straddle that was 100x what the settings screen showed
- ~2,300 near-identical warnings during a DNS outage, with no backoff
- half of those warnings ending at the colon, because httpx timeouts carry
  no message
"""
import unittest

import httpx

from src.core.applog import Outage, err_text
from src.core.engine_kalshi import MAX_STRADDLE_FRACTION
from src.strategy.straddle import straddle_sizing


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
    """The 2026-07-28 sizing accident, pinned."""

    BALANCE = 1_000.0

    def _cost(self, risk: float, entry: int = 49) -> float:
        return straddle_sizing(risk, entry, entry) * entry * 2 / 100.0

    def test_the_accident_would_now_be_blocked(self) -> None:
        cost = self._cost(500.0)
        self.assertAlmostEqual(cost, 494.90, places=2)
        self.assertGreater(cost, self.BALANCE * MAX_STRADDLE_FRACTION)

    def test_the_intended_risk_is_allowed(self) -> None:
        cost = self._cost(5.0)
        self.assertAlmostEqual(cost, 4.90, places=2)
        self.assertLessEqual(cost, self.BALANCE * MAX_STRADDLE_FRACTION)

    def test_a_quarter_of_the_account_is_the_line(self) -> None:
        self.assertLessEqual(self._cost(250.0),
                             self.BALANCE * MAX_STRADDLE_FRACTION)
        self.assertGreater(self._cost(260.0),
                           self.BALANCE * MAX_STRADDLE_FRACTION)


if __name__ == "__main__":
    unittest.main()
