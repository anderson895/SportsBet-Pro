"""Unit tests para sa Kalshi RSA-PSS request signing.

Gumagawa ng in-test RSA keypair — walang totoong credentials dito.

Run:  .\\venv\\Scripts\\python.exe -m pytest tests\\test_kalshi_auth.py -v
"""
from __future__ import annotations

import base64
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from src.execution.kalshi_auth import (
    KalshiAuthError,
    auth_headers,
    load_private_key,
    sign_request,
)


def make_keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    return key, pem


class TestLoadPrivateKey(unittest.TestCase):
    def test_load_from_pem_text(self) -> None:
        _, pem = make_keypair()
        key = load_private_key(pem)
        self.assertEqual(key.key_size, 2048)

    def test_load_from_file_path(self) -> None:
        _, pem = make_keypair()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "key.pem"
            path.write_text(pem, encoding="utf-8")
            key = load_private_key(str(path))
            self.assertEqual(key.key_size, 2048)

    def test_missing_file_raises(self) -> None:
        with self.assertRaises(KalshiAuthError):
            load_private_key(r"C:\does\not\exist.pem")

    def test_empty_raises(self) -> None:
        with self.assertRaises(KalshiAuthError):
            load_private_key("")

    def test_garbage_pem_raises(self) -> None:
        with self.assertRaises(KalshiAuthError):
            load_private_key("-----BEGIN PRIVATE KEY-----\ngarbage\n-----END PRIVATE KEY-----")


class TestSigning(unittest.TestCase):
    def test_signature_verifies_with_public_key(self) -> None:
        key, _ = make_keypair()
        ts = "1750000000000"
        path = "/trade-api/v2/portfolio/orders"
        sig_b64 = sign_request(key, "POST", path, ts)

        # I-verify gamit ang public key — eksaktong parehong message spec
        message = f"{ts}POST{path}".encode("utf-8")
        key.public_key().verify(
            base64.b64decode(sig_b64),
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )  # walang exception = valid

    def test_query_string_excluded_from_signature(self) -> None:
        key, _ = make_keypair()
        ts = "1750000000000"
        with_q = sign_request(key, "GET", "/trade-api/v2/markets?limit=5", ts)
        # PSS ay randomized — i-verify na ang message na WALANG query ang
        # pumapasa sa verification
        message = f"{ts}GET/trade-api/v2/markets".encode("utf-8")
        key.public_key().verify(
            base64.b64decode(with_q),
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )

    def test_auth_headers_shape(self) -> None:
        key, _ = make_keypair()
        headers = auth_headers("my-key-id", key, "GET",
                               "/trade-api/v2/portfolio/balance",
                               timestamp_ms=1750000000000)
        self.assertEqual(headers["KALSHI-ACCESS-KEY"], "my-key-id")
        self.assertEqual(headers["KALSHI-ACCESS-TIMESTAMP"], "1750000000000")
        self.assertIn("KALSHI-ACCESS-SIGNATURE", headers)
        base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"])  # valid base64


if __name__ == "__main__":
    unittest.main()
