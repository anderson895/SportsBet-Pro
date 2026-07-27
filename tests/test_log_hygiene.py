"""Log must answer "why didn't it trade?" without drowning in DNS noise.

A real 1.5-hour session produced 145 DoH lines and 19 real ones, and not a
single line explaining why neither bot placed a straddle. Both are covered here.
"""
from __future__ import annotations

import logging
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.core import netdns
from src.core.engine_kalshi import KalshiEngine
from src.core.engine_poly_box import PolyBoxEngine
from src.storage.db import Database


class _FakeResp:
    def __init__(self, ips: list[str]) -> None:
        self._ips = ips

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {"Answer": [{"type": 1, "data": ip, "TTL": 60}
                           for ip in self._ips]}


class _FakeHttpClient:
    """Stands in for httpx.Client inside netdns._doh_query."""
    ips: list[str] = []

    def __init__(self, *a, **kw) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a) -> bool:
        return False

    def get(self, url, params=None, headers=None):
        return _FakeResp(type(self).ips)


class DohLogNoiseTest(unittest.TestCase):
    """Kalshi's TTL is 60s, so the same answer is re-resolved every minute.
    Only a NEW or CHANGED answer deserves INFO. Exercises the real
    `_doh_query` with the network faked out."""

    def setUp(self) -> None:
        netdns._cache.clear()
        self._real_client = netdns.httpx.Client
        netdns.httpx.Client = _FakeHttpClient  # type: ignore[misc]
        self.addCleanup(
            lambda: setattr(netdns.httpx, "Client", self._real_client))
        self.addCleanup(netdns._cache.clear)

    def _resolve_logs(self, ips: list[str]) -> list[logging.LogRecord]:
        _FakeHttpClient.ips = ips
        with self.assertLogs("sportsbet.netdns", level="DEBUG") as cap:
            got = netdns._doh_query("api.kalshi.com", 1)
        self.assertEqual(set(got), set(ips))
        return cap.records

    def test_first_resolve_is_info(self) -> None:
        recs = self._resolve_logs(["1.1.1.1", "2.2.2.2"])
        self.assertEqual(recs[0].levelno, logging.INFO)

    def test_same_answer_reshuffled_is_not_info(self) -> None:
        """DNS round-robins the order — the same four IPs come back shuffled.
        A list compare would log INFO forever; a set compare must not."""
        self._resolve_logs(["1.1.1.1", "2.2.2.2"])
        recs = self._resolve_logs(["2.2.2.2", "1.1.1.1"])  # same, reordered
        self.assertEqual(recs[-1].levelno, logging.DEBUG,
                         "a reshuffled repeat answer must not log at INFO")

    def test_changed_answer_is_info(self) -> None:
        self._resolve_logs(["1.1.1.1", "2.2.2.2"])
        recs = self._resolve_logs(["9.9.9.9"])
        self.assertEqual(recs[-1].levelno, logging.INFO)


class WhyNoTradeIsLoggedTest(unittest.TestCase):
    """Box arb sits idle for long stretches; the reason must reach the log."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self._raw = Database(Path(self._tmp.name) / "t.db")

    def tearDown(self) -> None:
        self._raw.close()
        self._tmp.cleanup()

    def _engine(self, which: str):
        if which == "poly":
            return PolyBoxEngine(self._raw.scope("polymarket")), "polymarket"
        return KalshiEngine(self._raw.scope("kalshi")), "kalshi"

    def test_reason_is_written_to_the_log(self) -> None:
        for which in ("poly", "kalshi"):
            with self.subTest(engine=which):
                eng, scope = self._engine(which)
                eng._watch("SCANNING — 47 markets, none in the 48-52¢ band yet")
                msgs = [r["message"] for r in self._raw.scope(scope).recent_logs()]
                self.assertTrue(any("Watching:" in m for m in msgs),
                                f"{which}: reason never reached the log")

    def test_repeated_reason_is_not_spammed(self) -> None:
        """The scan loop runs every 30s — the same reason must log once."""
        for which in ("poly", "kalshi"):
            with self.subTest(engine=which):
                eng, scope = self._engine(which)
                for n in (47, 48, 51):        # same reason, different counts
                    eng._watch(f"SCANNING — {n} markets, none in the band yet")
                msgs = [r["message"] for r in self._raw.scope(scope).recent_logs()
                        if "Watching:" in r["message"]]
                self.assertEqual(len(msgs), 1, f"{which}: log spam: {msgs}")

    def test_a_different_reason_does_log_again(self) -> None:
        eng, scope = self._engine("poly")
        eng._watch("SCANNING — 47 markets, none in the band yet")
        eng._watch("WAITING — risk $1.00 too small for one 49¢+49¢ pair")
        msgs = [r["message"] for r in self._raw.scope(scope).recent_logs()
                if "Watching:" in r["message"]]
        self.assertEqual(len(msgs), 2)


if __name__ == "__main__":
    unittest.main()
