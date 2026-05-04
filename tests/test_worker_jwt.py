"""Unit tests for artagents.core.reigh.worker_jwt."""

from __future__ import annotations

import base64
import json
import time
import unittest
from typing import Any
from unittest.mock import patch

import jwt as pyjwt
from cryptography.hazmat.primitives.asymmetric import rsa

from artagents.core.reigh import worker_jwt
from artagents.core.reigh.worker_jwt import (
    DEFAULT_AUDIENCE,
    JwtVerificationError,
    verify_user_jwt,
)


def _b64url(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, byteorder="big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _build_jwks(private_key) -> dict[str, Any]:
    public_numbers = private_key.public_key().public_numbers()
    return {
        "keys": [
            {
                "kid": "test-key",
                "kty": "RSA",
                "alg": "RS256",
                "use": "sig",
                "n": _b64url(public_numbers.n),
                "e": _b64url(public_numbers.e),
            }
        ]
    }


def _sign(private_key, claims: dict[str, Any]) -> str:
    return pyjwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )


class WorkerJwtTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # 2048-bit RSA is overkill for tests but matches Supabase's JWKS shape.
        cls.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.jwks = _build_jwks(cls.private_key)

    def setUp(self) -> None:
        # Reset the per-URL JWKS TTL cache so each test sees the patched fetch.
        worker_jwt._jwks_cache.clear()
        self._fetch_patch = patch.object(worker_jwt, "_fetch_jwks", return_value=self.jwks)
        self._fetch_patch.start()
        self.addCleanup(self._fetch_patch.stop)

    def test_valid_jwt_returns_verified_subject(self) -> None:
        token = _sign(
            self.private_key,
            {
                "sub": "user-1",
                "aud": DEFAULT_AUDIENCE,
                "exp": int(time.time()) + 60,
                "iat": int(time.time()),
            },
        )
        verified = verify_user_jwt(token, jwks_url="https://example/jwks")
        self.assertEqual(verified.user_id, "user-1")
        self.assertEqual(verified.audience, DEFAULT_AUDIENCE)
        self.assertEqual(verified.raw_claims["sub"], "user-1")

    def test_expired_jwt_rejected(self) -> None:
        token = _sign(
            self.private_key,
            {
                "sub": "user-1",
                "aud": DEFAULT_AUDIENCE,
                "exp": int(time.time()) - 60,
            },
        )
        with self.assertRaises(JwtVerificationError):
            verify_user_jwt(token, jwks_url="https://example/jwks")

    def test_wrong_audience_rejected(self) -> None:
        token = _sign(
            self.private_key,
            {
                "sub": "user-1",
                "aud": "service",
                "exp": int(time.time()) + 60,
            },
        )
        with self.assertRaises(JwtVerificationError):
            verify_user_jwt(token, jwks_url="https://example/jwks")

    def test_missing_sub_claim_rejected(self) -> None:
        token = _sign(
            self.private_key,
            {
                "aud": DEFAULT_AUDIENCE,
                "exp": int(time.time()) + 60,
            },
        )
        with self.assertRaises(JwtVerificationError):
            verify_user_jwt(token, jwks_url="https://example/jwks")

    def test_empty_token_rejected(self) -> None:
        with self.assertRaises(JwtVerificationError):
            verify_user_jwt("", jwks_url="https://example/jwks")


if __name__ == "__main__":
    unittest.main()
