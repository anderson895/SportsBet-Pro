"""Dynamic DNS via DoH — bypass ISP DNS poisoning para sa Polymarket/Kalshi.

Ang ISP ng user ay nagpo-poison sa A record ng *.polymarket.com — nagbabalik
ito ng blackhole IP (hal. 161.49.61.85) na nagti-timeout sa port 443, samantalang
ang totoong Cloudflare-fronted IP (172.64.x / 104.18.x) ay bukas naman. Sa halip
na umasa sa system/ISP DNS, kino-consult natin ang DNS-over-HTTPS (Cloudflare
1.1.1.1, fallback Google 8.8.8.8) para sa mga trading host lamang.

Ginagawa ito sa pamamagitan ng pag-patch sa global ``socket.getaddrinfo``. Dahil
DITO dumadaan ang lahat — httpx, websockets, AT ang py-clob-client (na requests-
based, hindi natin direktang macontrol) — isang patch lang, sakop ang buong app.

Non-override na host (Binance, Coinbase) ay dumadaan pa rin sa system DNS nang
buo; kung mabigo ang DoH, awtomatikong nag-fa-fallback din sa system resolver.

Tawagin ang ``install_doh_resolver()`` nang isang beses sa startup (main.py),
matapos ang ``truststore.inject_into_ssl()``.
"""
from __future__ import annotations

import logging
import socket
import threading
import time
from typing import Optional

import httpx

filelog = logging.getLogger("sportsbet.netdns")

# Mga host na iro-route sa DoH (suffix match). Lahat ng iba ay system DNS pa rin.
OVERRIDE_SUFFIXES: tuple[str, ...] = ("polymarket.com", "kalshi.com", "kalshi.co")

# DoH endpoints — kinokonek by-IP (walang bootstrap-DNS dependency). Ang cert ng
# 1.1.1.1 / 8.8.8.8 ay may IP SAN kaya pumapasa ang default TLS verification.
DOH_ENDPOINTS: tuple[str, ...] = (
    "https://1.1.1.1/dns-query",  # Cloudflare
    "https://8.8.8.8/resolve",    # Google (parehong name/type JSON interface)
)

_DOH_TIMEOUT = 6.0
_TTL_MIN, _TTL_MAX, _TTL_DEFAULT = 60.0, 3600.0, 300.0

# Cache: host -> (expiry_monotonic, [ip, ...])
_cache: dict[str, tuple[float, list[str]]] = {}
_lock = threading.Lock()

_original_getaddrinfo = None  # itinatago para sa fallback + uninstall


def _should_override(host: str) -> bool:
    host = host.rstrip(".").lower()
    return any(host == s or host.endswith("." + s) for s in OVERRIDE_SUFFIXES)


def _doh_query(host: str, rrtype: int) -> list[str]:
    """Query DoH para sa host (rrtype 1=A, 28=AAAA). Ibinabalik ang mga IP str."""
    # Bagong client kada tawag — thread-safe, at bihira lang naman (may cache).
    # trust_env=False para hindi maapektuhan ng sirang proxy env vars.
    with httpx.Client(timeout=_DOH_TIMEOUT, trust_env=False) as client:
        for url in DOH_ENDPOINTS:
            try:
                resp = client.get(
                    url,
                    params={"name": host, "type": rrtype},
                    headers={"accept": "application/dns-json"},
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:  # subukan ang susunod na endpoint
                filelog.debug("DoH %s nabigo para sa %s: %s", url, host, exc)
                continue

            answers = [a for a in data.get("Answer", []) if a.get("type") == rrtype]
            ips = [a["data"] for a in answers if a.get("data")]
            if ips:
                ttl = max(_TTL_MIN, min(_TTL_MAX, min(
                    (float(a.get("TTL", _TTL_DEFAULT)) for a in answers),
                    default=_TTL_DEFAULT,
                )))
                with _lock:
                    _cache[host] = (time.monotonic() + ttl, ips)
                filelog.info("DoH resolved %s -> %s (ttl %.0fs)", host, ips, ttl)
                return ips
    return []


def _resolve(host: str, want_v6: bool) -> list[str]:
    """DoH resolution na may cache. want_v6 -> AAAA, else A (IPv4)."""
    now = time.monotonic()
    with _lock:
        cached = _cache.get(host)
        if cached and cached[0] > now:
            return cached[1]
    return _doh_query(host, 28 if want_v6 else 1)


def _patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    """Drop-in ``socket.getaddrinfo`` — DoH para sa trading hosts, system DNS sa iba."""
    # Ang async path (anyio/httpx) ay nagpapasa ng host bilang bytes, ang sync
    # naman (requests, sync httpx) ay str — i-normalize muna bago mag-match.
    hostname = host.decode("ascii") if isinstance(host, (bytes, bytearray)) else host

    if not hostname or not _should_override(str(hostname)):
        return _original_getaddrinfo(host, port, family, type, proto, flags)

    # Pumili ng address family. Ginagamit natin ang IPv4 (kumpirmadong bukas);
    # IPv6 lang kung tahasang hiniling (AF_INET6).
    want_v6 = family == socket.AF_INET6
    out_family = socket.AF_INET6 if want_v6 else socket.AF_INET

    try:
        ips = _resolve(str(hostname), want_v6)
    except Exception as exc:
        filelog.warning("DoH resolve error para sa %s, babalik sa system DNS: %s", host, exc)
        ips = []

    if not ips:  # DoH walang sagot — huwag i-break ang app, gamitin ang system DNS
        return _original_getaddrinfo(host, port, family, type, proto, flags)

    # Normalize ang port -> int (maaaring None, str service name, o int)
    if port is None:
        port_num = 0
    elif isinstance(port, str):
        port_num = int(port) if port.isdigit() else socket.getservbyname(port)
    else:
        port_num = port

    sock_type = type or socket.SOCK_STREAM
    results = []
    for ip in ips:
        if want_v6:
            sockaddr = (ip, port_num, 0, 0)
        else:
            sockaddr = (ip, port_num)
        results.append((out_family, sock_type, proto, "", sockaddr))
    return results


def install_doh_resolver() -> None:
    """I-patch ang global socket.getaddrinfo para gumamit ng DoH sa trading hosts.

    Idempotent — ligtas tawagin nang paulit-ulit.
    """
    global _original_getaddrinfo
    if _original_getaddrinfo is not None:
        return
    _original_getaddrinfo = socket.getaddrinfo
    socket.getaddrinfo = _patched_getaddrinfo
    filelog.info("DoH resolver naka-install (override: %s)", ", ".join(OVERRIDE_SUFFIXES))


def uninstall_doh_resolver() -> None:
    """Ibalik ang orihinal na getaddrinfo (para sa tests / cleanup)."""
    global _original_getaddrinfo
    if _original_getaddrinfo is not None:
        socket.getaddrinfo = _original_getaddrinfo
        _original_getaddrinfo = None
    with _lock:
        _cache.clear()
