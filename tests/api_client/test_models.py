"""Tests para los modelos de dominio de api_client (M2).

Cubre:
    - BinanceCredentials: from_env(), AuthenticationError, __repr__, inmutabilidad.
    - RateLimitConfig: defaults, validaciones, inmutabilidad.
    - RetryConfig: defaults, validaciones, inmutabilidad.
    - APIClientConfig: defaults, validaciones, nested configs, inmutabilidad.
    - BinanceErrorResponse: parseo correcto, campos faltantes.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from chimuelo_prime.api_client.exceptions import AuthenticationError
from chimuelo_prime.api_client.models import (
    APIClientConfig,
    BinanceCredentials,
    BinanceErrorResponse,
    RateLimitConfig,
    RetryConfig,
)


# --------------------------------------------------------------------------- #
# BinanceCredentials.from_env()
# --------------------------------------------------------------------------- #
class TestBinanceCredentialsFromEnv:
    def test_from_env_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CHIMUELO_API_KEY", "test_key_1234")
        monkeypatch.setenv("CHIMUELO_API_SECRET", "test_secret_abcd")
        creds = BinanceCredentials.from_env()
        assert creds.api_key == "test_key_1234"
        assert creds.api_secret == "test_secret_abcd"

    def test_from_env_missing_api_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CHIMUELO_API_KEY", raising=False)
        monkeypatch.setenv("CHIMUELO_API_SECRET", "secret")
        with pytest.raises(AuthenticationError, match="CHIMUELO_API_KEY"):
            BinanceCredentials.from_env()

    def test_from_env_empty_api_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CHIMUELO_API_KEY", "")
        monkeypatch.setenv("CHIMUELO_API_SECRET", "secret")
        with pytest.raises(AuthenticationError, match="CHIMUELO_API_KEY"):
            BinanceCredentials.from_env()

    def test_from_env_missing_api_secret_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CHIMUELO_API_KEY", "key")
        monkeypatch.delenv("CHIMUELO_API_SECRET", raising=False)
        with pytest.raises(AuthenticationError, match="CHIMUELO_API_SECRET"):
            BinanceCredentials.from_env()

    def test_from_env_empty_api_secret_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CHIMUELO_API_KEY", "key")
        monkeypatch.setenv("CHIMUELO_API_SECRET", "")
        with pytest.raises(AuthenticationError, match="CHIMUELO_API_SECRET"):
            BinanceCredentials.from_env()


# --------------------------------------------------------------------------- #
# BinanceCredentials.__repr__ / __str__ — enmascaramiento de secrets
# --------------------------------------------------------------------------- #
class TestBinanceCredentialsRepr:
    def test_repr_masks_secret(self) -> None:
        creds = BinanceCredentials(api_key="ABCD1234", api_secret="supersecret")
        assert "supersecret" not in repr(creds)
        assert "***" in repr(creds)

    def test_repr_shows_last_four_of_key(self) -> None:
        creds = BinanceCredentials(api_key="ABCD1234", api_secret="supersecret")
        assert "...1234" in repr(creds)

    def test_str_also_masks(self) -> None:
        creds = BinanceCredentials(api_key="ABCD1234", api_secret="supersecret")
        assert "supersecret" not in str(creds)
        assert "***" in str(creds)

    def test_short_key_shows_placeholder(self) -> None:
        creds = BinanceCredentials(api_key="AB", api_secret="s")
        assert "***" in repr(creds)
        assert "AB" not in repr(creds)

    def test_repr_format(self) -> None:
        creds = BinanceCredentials(api_key="LONGKEY9876", api_secret="anysecret")
        r = repr(creds)
        assert r.startswith("BinanceCredentials(")
        assert "api_secret='***'" in r
        assert "...9876" in r


# --------------------------------------------------------------------------- #
# BinanceCredentials inmutabilidad
# --------------------------------------------------------------------------- #
class TestBinanceCredentialsImmutability:
    def test_cannot_mutate_api_key(self) -> None:
        creds = BinanceCredentials(api_key="key", api_secret="secret")
        with pytest.raises(ValidationError):
            creds.api_key = "new_key"  # type: ignore[misc]

    def test_cannot_mutate_api_secret(self) -> None:
        creds = BinanceCredentials(api_key="key", api_secret="secret")
        with pytest.raises(ValidationError):
            creds.api_secret = "new_secret"  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# RateLimitConfig
# --------------------------------------------------------------------------- #
class TestRateLimitConfig:
    def test_defaults(self) -> None:
        cfg = RateLimitConfig()
        assert cfg.weight_limit == 1200
        assert cfg.weight_window_seconds == 60.0
        assert cfg.order_limit == 50
        assert cfg.order_window_seconds == 10.0

    def test_custom_values_accepted(self) -> None:
        cfg = RateLimitConfig(
            weight_limit=600,
            weight_window_seconds=30.0,
            order_limit=25,
            order_window_seconds=5.0,
        )
        assert cfg.weight_limit == 600
        assert cfg.order_limit == 25

    def test_zero_weight_limit_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RateLimitConfig(weight_limit=0)

    def test_negative_order_limit_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RateLimitConfig(order_limit=-1)

    def test_zero_weight_window_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RateLimitConfig(weight_window_seconds=0.0)

    def test_immutability(self) -> None:
        cfg = RateLimitConfig()
        with pytest.raises(ValidationError):
            cfg.weight_limit = 999  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# RetryConfig
# --------------------------------------------------------------------------- #
class TestRetryConfig:
    def test_defaults(self) -> None:
        cfg = RetryConfig()
        assert cfg.max_retries == 3
        assert cfg.base_delay_seconds == 1.0
        assert cfg.max_delay_seconds == 60.0
        assert cfg.jitter_seconds == 0.5

    def test_max_retries_zero_allowed(self) -> None:
        cfg = RetryConfig(max_retries=0)
        assert cfg.max_retries == 0

    def test_max_retries_ten_allowed(self) -> None:
        cfg = RetryConfig(max_retries=10)
        assert cfg.max_retries == 10

    def test_max_retries_above_ten_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RetryConfig(max_retries=11)

    def test_base_delay_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RetryConfig(base_delay_seconds=0.0)

    def test_jitter_zero_allowed(self) -> None:
        cfg = RetryConfig(jitter_seconds=0.0)
        assert cfg.jitter_seconds == 0.0

    def test_negative_jitter_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RetryConfig(jitter_seconds=-0.1)

    def test_immutability(self) -> None:
        cfg = RetryConfig()
        with pytest.raises(ValidationError):
            cfg.max_retries = 5  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# APIClientConfig
# --------------------------------------------------------------------------- #
class TestAPIClientConfig:
    def test_defaults(self) -> None:
        cfg = APIClientConfig()
        assert cfg.recv_window_ms == 5000
        assert isinstance(cfg.rate_limit, RateLimitConfig)
        assert isinstance(cfg.retry, RetryConfig)

    def test_nested_defaults_propagate(self) -> None:
        cfg = APIClientConfig()
        assert cfg.rate_limit.weight_limit == 1200
        assert cfg.retry.max_retries == 3

    def test_recv_window_at_limit_accepted(self) -> None:
        cfg = APIClientConfig(recv_window_ms=60000)
        assert cfg.recv_window_ms == 60000

    def test_recv_window_above_limit_rejected(self) -> None:
        with pytest.raises(ValidationError):
            APIClientConfig(recv_window_ms=60001)

    def test_recv_window_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            APIClientConfig(recv_window_ms=0)

    def test_custom_nested_rate_limit(self) -> None:
        rl = RateLimitConfig(weight_limit=600)
        cfg = APIClientConfig(rate_limit=rl)
        assert cfg.rate_limit.weight_limit == 600

    def test_custom_nested_retry(self) -> None:
        rc = RetryConfig(max_retries=5)
        cfg = APIClientConfig(retry=rc)
        assert cfg.retry.max_retries == 5

    def test_immutability(self) -> None:
        cfg = APIClientConfig()
        with pytest.raises(ValidationError):
            cfg.recv_window_ms = 1000  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# BinanceErrorResponse
# --------------------------------------------------------------------------- #
class TestBinanceErrorResponse:
    def test_parse_valid_dict(self) -> None:
        err = BinanceErrorResponse.model_validate({"code": -1121, "msg": "Invalid symbol."})
        assert err.code == -1121
        assert err.msg == "Invalid symbol."

    def test_missing_code_raises(self) -> None:
        with pytest.raises(ValidationError):
            BinanceErrorResponse.model_validate({"msg": "Invalid symbol."})

    def test_missing_msg_raises(self) -> None:
        with pytest.raises(ValidationError):
            BinanceErrorResponse.model_validate({"code": -1121})

    def test_code_is_int(self) -> None:
        err = BinanceErrorResponse(code=-2014, msg="Invalid API-key format.")
        assert isinstance(err.code, int)

    def test_negative_code_accepted(self) -> None:
        err = BinanceErrorResponse(code=-1100, msg="Illegal characters.")
        assert err.code == -1100
