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


# The REAL edge blocks api.elections.kalshi.com cycled through in one hour of
# app.log. A CDN hands back a different set almost every 60s TTL refresh — an
# earlier "log INFO when the answer changed" attempt therefore still logged 32
# lines in 58 minutes. These fixtures keep the test honest.
_REAL_KALSHI_BLOCKS = [
    ["3.169.71.61", "3.169.71.55", "3.169.71.42", "3.169.71.108"],
    ["52.85.118.15", "52.85.118.66", "52.85.118.82", "52.85.118.10"],
    ["18.154.132.64", "18.154.132.60", "18.154.132.29", "18.154.132.61"],
    ["3.163.125.74", "3.163.125.115", "3.163.125.96", "3.163.125.54"],
    ["18.66.218.14", "18.66.218.17", "18.66.218.126", "18.66.218.108"],
    ["13.249.126.122", "13.249.126.54", "13.249.126.50", "13.249.126.109"],
    ["3.169.231.79", "3.169.231.127", "3.169.231.69", "3.169.231.58"],
    ["99.86.253.79", "99.86.253.85", "99.86.253.37", "99.86.253.42"],
    ["3.163.175.77", "3.163.175.113", "3.163.175.44", "3.163.175.43"],
]


class DohLogNoiseTest(unittest.TestCase):
    """A CDN re-resolve is routine, not news — INFO once per host, then DEBUG.

    Exercises the real `_doh_query` with the network faked out.
    """

    def setUp(self) -> None:
        netdns._cache.clear()
        netdns._seen_hosts.clear()
        self._real_client = netdns.httpx.Client
        netdns.httpx.Client = _FakeHttpClient  # type: ignore[misc]
        self.addCleanup(
            lambda: setattr(netdns.httpx, "Client", self._real_client))
        self.addCleanup(netdns._cache.clear)
        self.addCleanup(netdns._seen_hosts.clear)

    def _resolve_logs(self, ips: list[str],
                      host: str = "api.kalshi.com") -> list[logging.LogRecord]:
        _FakeHttpClient.ips = ips
        with self.assertLogs("sportsbet.netdns", level="DEBUG") as cap:
            got = netdns._doh_query(host, 1)
        self.assertEqual(set(got), set(ips))
        return cap.records

    def test_first_resolve_is_info(self) -> None:
        """One INFO line per host is the proof the DoH bypass works."""
        recs = self._resolve_logs(_REAL_KALSHI_BLOCKS[0])
        self.assertEqual(recs[0].levelno, logging.INFO)

    def test_rotating_cdn_ips_do_not_spam_info(self) -> None:
        """The bug this replaces: real CDN answers differ nearly every time,
        so a changed-answer check still logged ~32 lines an hour."""
        infos = 0
        for i in range(58):                      # 58 min at a 60s TTL
            recs = self._resolve_logs(_REAL_KALSHI_BLOCKS[i % 9])
            infos += sum(r.levelno == logging.INFO for r in recs)
        self.assertEqual(infos, 1,
                         f"58 CDN refreshes should log INFO once, got {infos}")

    def test_each_host_gets_its_own_info_line(self) -> None:
        for host in ("api.kalshi.com", "clob.polymarket.com"):
            recs = self._resolve_logs(_REAL_KALSHI_BLOCKS[0], host=host)
            self.assertEqual(recs[0].levelno, logging.INFO, host)


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
