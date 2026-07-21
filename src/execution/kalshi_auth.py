"""Kalshi API v2 request signing — RSA-PSS SHA256.

Ang bawat authenticated request ay may tatlong header:
- KALSHI-ACCESS-KEY       : ang API Key ID (UUID mula sa account settings)
- KALSHI-ACCESS-TIMESTAMP : ms since epoch (string)
- KALSHI-ACCESS-SIGNATURE : base64(RSA-PSS-SHA256 sign ng
                            "{timestamp}{METHOD}{path}"))

Ang `path` ay KASAMA ang "/trade-api/v2" prefix pero WALANG query string
(per Kalshi docs). Ang private key ay ang RSA .pem na dina-download sa
Kalshi account settings — pwedeng i-paste ang buong PEM text sa Settings
(itinatago sa Windows Credential Manager) o ituro ang file path.
"""
from __future__ import annotations

import base64
import datetime as dt
from pathlib import Path
from typing import Union

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey


class KalshiAuthError(Exception):
    """May problema sa Kalshi credentials / signing."""


def load_private_key(pem_text_or_path: str) -> RSAPrivateKey:
    """I-load ang RSA private key mula sa PEM text O file path.

    Tinatanggap:
    - buong PEM text ("-----BEGIN ... KEY-----\n...")
    - path papunta sa .pem file
    """
    value = (pem_text_or_path or "").strip()
    if not value:
        raise KalshiAuthError("Kalshi RSA private key is not set")

    if "-----BEGIN" in value:
        data = value.encode("utf-8")
    else:
        path = Path(value)
        if not path.exists():
            raise KalshiAuthError(f"PEM file not found: {value}")
        data = path.read_bytes()

    try:
        key = serialization.load_pem_private_key(data, password=None)
    except Exception as e:
        raise KalshiAuthError(f"Could not parse RSA private key: {e}") from e
    if not isinstance(key, RSAPrivateKey):
        raise KalshiAuthError("The PEM file is not an RSA private key")
    return key


def sign_request(
    key: RSAPrivateKey, method: str, path: str, timestamp_ms: Union[int, str]
) -> str:
    """Base64 RSA-PSS SHA256 signature ng "{timestamp}{METHOD}{path}".

    `path` = full API path kasama ang /trade-api/v2 prefix, WALANG query
    string (hal. "/trade-api/v2/portfolio/orders").
    """
    path_without_query = path.split("?", 1)[0]
    message = f"{timestamp_ms}{method.upper()}{path_without_query}".encode("utf-8")
    signature = key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")


def auth_headers(
    key_id: str, key: RSAPrivateKey, method: str, path: str,
    timestamp_ms: Union[int, str, None] = None,
) -> dict[str, str]:
    """Buuin ang tatlong Kalshi auth header para sa isang request."""
    if timestamp_ms is None:
        timestamp_ms = int(
            dt.datetime.now(dt.timezone.utc).timestamp() * 1000
        )
    ts = str(timestamp_ms)
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-SIGNATURE": sign_request(key, method, path, ts),
        "KALSHI-ACCESS-TIMESTAMP": ts,
    }
