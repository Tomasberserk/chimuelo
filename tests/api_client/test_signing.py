"""Tests para BinanceSigner (M2).

Cubre:
    - Vector HMAC conocido: dado key/secret/params fijos + timestamp fijo, la firma
      debe coincidir con el valor calculado independientemente.
    - sign_params no muta el dict original.
    - timestamp se inyecta correctamente (freezegun para time.time).
    - recvWindow se inyecta con el valor del constructor.
    - server_time_offset_ms se suma al timestamp.
    - api_key property expone la clave.
    - __repr__ no expone el secret.
"""

from __future__ import annotations

import hashlib
import hmac
from urllib.parse import urlencode

from freezegun import freeze_time

from chimuelo_prime.api_client.models import BinanceCredentials
from chimuelo_prime.api_client.signing import BinanceSigner

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
FIXED_KEY = "testApiKey1234567890ABCDEFGHIJ"
FIXED_SECRET = "testSecretXYZABCDEFGHIJKLMNOPQ"
FIXED_TIMESTAMP_MS = 1_700_000_000_000  # 2023-11-14 22:13:20 UTC


def _make_signer(recv_window: int = 5000, offset_ms: int = 0) -> BinanceSigner:
    creds = BinanceCredentials(api_key=FIXED_KEY, api_secret=FIXED_SECRET)
    signer = BinanceSigner(creds, recv_window=recv_window)
    if offset_ms:
        signer.set_server_time_offset(offset_ms)
    return signer


def _expected_signature(params: dict, timestamp_ms: int, recv_window: int, secret: str) -> str:
    signed = dict(params)
    signed["timestamp"] = timestamp_ms
    signed["recvWindow"] = recv_window
    qs = urlencode(signed)
    return hmac.new(secret.encode("utf-8"), qs.encode("utf-8"), hashlib.sha256).hexdigest()


# --------------------------------------------------------------------------- #
# Vector HMAC — firma determinista
# --------------------------------------------------------------------------- #
class TestSignParamsHMACVector:
    @freeze_time("2023-11-14 22:13:20")  # FIXED_TIMESTAMP_MS / 1000
    def test_signature_matches_expected_vector(self) -> None:
        signer = _make_signer(recv_window=5000)
        params = {"symbol": "SOLUSDT", "side": "BUY", "quantity": "1.5"}
        result = signer.sign_params(params)
        expected_sig = _expected_signature(params, FIXED_TIMESTAMP_MS, 5000, FIXED_SECRET)
        assert result["signature"] == expected_sig

    @freeze_time("2023-11-14 22:13:20")
    def test_signature_is_hex_string(self) -> None:
        signer = _make_signer()
        result = signer.sign_params({"symbol": "SOLUSDT"})
        assert isinstance(result["signature"], str)
        assert len(result["signature"]) == 64  # SHA256 = 32 bytes = 64 hex chars

    @freeze_time("2023-11-14 22:13:20")
    def test_signature_changes_with_different_params(self) -> None:
        signer = _make_signer()
        r1 = signer.sign_params({"symbol": "SOLUSDT"})
        r2 = signer.sign_params({"symbol": "BTCUSDT"})
        assert r1["signature"] != r2["signature"]

    @freeze_time("2023-11-14 22:13:20")
    def test_empty_params_produces_valid_signature(self) -> None:
        signer = _make_signer()
        result = signer.sign_params({})
        assert "signature" in result
        assert len(result["signature"]) == 64


# --------------------------------------------------------------------------- #
# Timestamp y recvWindow
# --------------------------------------------------------------------------- #
class TestSignParamsTimestamp:
    @freeze_time("2023-11-14 22:13:20")
    def test_timestamp_matches_frozen_time(self) -> None:
        signer = _make_signer()
        result = signer.sign_params({})
        assert result["timestamp"] == FIXED_TIMESTAMP_MS

    @freeze_time("2023-11-14 22:13:20")
    def test_recv_window_in_result(self) -> None:
        signer = _make_signer(recv_window=10000)
        result = signer.sign_params({})
        assert result["recvWindow"] == 10000

    @freeze_time("2023-11-14 22:13:20")
    def test_server_time_offset_applied(self) -> None:
        offset = 500
        signer = _make_signer(offset_ms=offset)
        result = signer.sign_params({})
        assert result["timestamp"] == FIXED_TIMESTAMP_MS + offset

    @freeze_time("2023-11-14 22:13:20")
    def test_negative_offset_applied(self) -> None:
        offset = -300
        signer = _make_signer(offset_ms=offset)
        result = signer.sign_params({})
        assert result["timestamp"] == FIXED_TIMESTAMP_MS + offset

    def test_set_server_time_offset_updates_offset(self) -> None:
        signer = _make_signer()
        signer.set_server_time_offset(1000)
        assert signer._server_time_offset_ms == 1000

    def test_set_server_time_offset_zero_resets(self) -> None:
        signer = _make_signer(offset_ms=500)
        signer.set_server_time_offset(0)
        assert signer._server_time_offset_ms == 0


# --------------------------------------------------------------------------- #
# Inmutabilidad del dict original
# --------------------------------------------------------------------------- #
class TestSignParamsNotMutateOriginal:
    @freeze_time("2023-11-14 22:13:20")
    def test_original_params_unchanged(self) -> None:
        signer = _make_signer()
        original = {"symbol": "SOLUSDT", "side": "SELL"}
        original_copy = dict(original)
        signer.sign_params(original)
        assert original == original_copy

    @freeze_time("2023-11-14 22:13:20")
    def test_original_has_no_timestamp(self) -> None:
        signer = _make_signer()
        original = {"symbol": "SOLUSDT"}
        signer.sign_params(original)
        assert "timestamp" not in original

    @freeze_time("2023-11-14 22:13:20")
    def test_original_has_no_signature(self) -> None:
        signer = _make_signer()
        original = {"symbol": "SOLUSDT"}
        signer.sign_params(original)
        assert "signature" not in original

    @freeze_time("2023-11-14 22:13:20")
    def test_result_is_new_dict(self) -> None:
        signer = _make_signer()
        original = {"symbol": "SOLUSDT"}
        result = signer.sign_params(original)
        assert result is not original


# --------------------------------------------------------------------------- #
# api_key property y __repr__
# --------------------------------------------------------------------------- #
class TestSignerApiKeyAndRepr:
    def test_api_key_property_returns_key(self) -> None:
        signer = _make_signer()
        assert signer.api_key == FIXED_KEY

    def test_repr_does_not_expose_secret(self) -> None:
        signer = _make_signer()
        assert FIXED_SECRET not in repr(signer)

    def test_repr_shows_last_four_of_key(self) -> None:
        signer = _make_signer()
        assert f"...{FIXED_KEY[-4:]}" in repr(signer)

    def test_repr_shows_recv_window(self) -> None:
        signer = _make_signer(recv_window=7500)
        assert "7500" in repr(signer)
