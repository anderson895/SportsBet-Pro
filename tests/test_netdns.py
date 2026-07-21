"""Mocked tests para sa DoH getaddrinfo override.

Walang totoong network dito — mina-mock ang DoH query. Tine-test: tamang
routing (Polymarket/Kalshi -> DoH, iba -> system DNS), fallback kapag walang
DoH sagot, at idempotent install/uninstall.

Run:  .\\venv\\Scripts\\python.exe -m unittest tests.test_netdns -v
"""
from __future__ import annotations

import socket
import unittest
from unittest.mock import patch

from src.core import netdns


class DohResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        netdns.uninstall_doh_resolver()  # malinis na estado
        netdns._cache.clear()

    def tearDown(self) -> None:
        netdns.uninstall_doh_resolver()

    def test_polymarket_host_uses_doh(self) -> None:
        with patch.object(netdns, "_doh_query", return_value=["104.18.34.205"]) as doh:
            netdns.install_doh_resolver()
            res = socket.getaddrinfo("clob.polymarket.com", 443, type=socket.SOCK_STREAM)
        doh.assert_called_once()
        self.assertEqual([r[4][0] for r in res], ["104.18.34.205"])
        self.assertEqual(res[0][0], socket.AF_INET)
        self.assertEqual(res[0][4], ("104.18.34.205", 443))

    def test_bytes_host_from_async_path(self) -> None:
        # anyio/httpx async ay nagpapasa ng host bilang bytes — dapat pa rin
        # ma-route sa DoH (regression: dating napupunta sa system DNS).
        with patch.object(netdns, "_doh_query", return_value=["172.64.153.51"]) as doh:
            netdns.install_doh_resolver()
            res = socket.getaddrinfo(b"clob.polymarket.com", 443, type=socket.SOCK_STREAM)
        doh.assert_called_once()
        self.assertEqual([r[4][0] for r in res], ["172.64.153.51"])

    def test_non_polymarket_host_bypasses_doh(self) -> None:
        with patch.object(netdns, "_doh_query", return_value=["1.2.3.4"]) as doh:
            netdns.install_doh_resolver()
            with patch.object(
                netdns, "_original_getaddrinfo",
                return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("9.9.9.9", 443))],
            ) as orig:
                res = socket.getaddrinfo("api.binance.com", 443, type=socket.SOCK_STREAM)
        doh.assert_not_called()
        orig.assert_called_once()
        self.assertEqual(res[0][4][0], "9.9.9.9")

    def test_falls_back_to_system_dns_when_doh_empty(self) -> None:
        sentinel = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("5.5.5.5", 443))]
        with patch.object(netdns, "_doh_query", return_value=[]):
            netdns.install_doh_resolver()
            with patch.object(netdns, "_original_getaddrinfo", return_value=sentinel) as orig:
                res = socket.getaddrinfo("clob.polymarket.com", 443)
        orig.assert_called_once()
        self.assertEqual(res, sentinel)

    def test_should_override_matching(self) -> None:
        self.assertTrue(netdns._should_override("clob.polymarket.com"))
        self.assertTrue(netdns._should_override("gamma-api.polymarket.com."))
        self.assertTrue(netdns._should_override("polymarket.com"))
        # Kalshi hosts ay saklaw na rin ngayon
        self.assertTrue(netdns._should_override("api.elections.kalshi.com"))
        self.assertTrue(netdns._should_override("demo-api.kalshi.co"))
        self.assertFalse(netdns._should_override("api.binance.com"))
        self.assertFalse(netdns._should_override("notpolymarket.com.evil.com"))

    def test_install_idempotent(self) -> None:
        netdns.install_doh_resolver()
        patched = socket.getaddrinfo
        netdns.install_doh_resolver()  # pangalawang tawag — walang double-wrap
        self.assertIs(socket.getaddrinfo, patched)


if __name__ == "__main__":
    unittest.main()
