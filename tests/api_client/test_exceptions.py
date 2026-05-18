"""Tests para la jerarquía de excepciones de api_client (M2).

Cubre:
    - Instanciación de cada excepción.
    - Herencia completa (APIClientError → ChimueloException → Exception).
    - BinanceAPIError: campos status_code, binance_code, msg accesibles.
    - Captura polimórfica por clase base.
    - Aislamiento entre ramas (M1 vs M2).
"""

from __future__ import annotations

import pytest

from chimuelo_prime.api_client.exceptions import (
    APIClientError,
    AuthenticationError,
    BinanceAPIError,
    RateLimitExceededError,
)
from chimuelo_prime.exchange_config.exceptions import ChimueloException


class TestExceptionInstantiation:
    def test_api_client_error(self) -> None:
        exc = APIClientError("error genérico")
        assert str(exc) == "error genérico"

    def test_authentication_error(self) -> None:
        exc = AuthenticationError("CHIMUELO_API_KEY no definida")
        assert str(exc) == "CHIMUELO_API_KEY no definida"

    def test_rate_limit_exceeded_error(self) -> None:
        exc = RateLimitExceededError("429 tras 3 reintentos")
        assert str(exc) == "429 tras 3 reintentos"

    def test_binance_api_error_fields(self) -> None:
        exc = BinanceAPIError(status_code=400, binance_code=-1121, msg="Invalid symbol.")
        assert exc.status_code == 400
        assert exc.binance_code == -1121
        assert exc.msg == "Invalid symbol."

    def test_binance_api_error_message_format(self) -> None:
        exc = BinanceAPIError(status_code=400, binance_code=-1121, msg="Invalid symbol.")
        assert "400" in str(exc)
        assert "-1121" in str(exc)
        assert "Invalid symbol." in str(exc)


class TestExceptionHierarchy:
    def test_authentication_is_api_client_error(self) -> None:
        assert isinstance(AuthenticationError("x"), APIClientError)

    def test_authentication_is_chimuelo_exception(self) -> None:
        assert isinstance(AuthenticationError("x"), ChimueloException)

    def test_authentication_is_base_exception(self) -> None:
        assert isinstance(AuthenticationError("x"), Exception)

    def test_rate_limit_is_api_client_error(self) -> None:
        assert isinstance(RateLimitExceededError("x"), APIClientError)

    def test_rate_limit_is_chimuelo_exception(self) -> None:
        assert isinstance(RateLimitExceededError("x"), ChimueloException)

    def test_binance_api_error_is_api_client_error(self) -> None:
        assert isinstance(BinanceAPIError(400, -1121, "x"), APIClientError)

    def test_binance_api_error_is_chimuelo_exception(self) -> None:
        assert isinstance(BinanceAPIError(400, -1121, "x"), ChimueloException)

    def test_api_client_error_is_chimuelo_exception(self) -> None:
        assert isinstance(APIClientError("x"), ChimueloException)


class TestExceptionCapture:
    def test_capture_authentication_as_api_client_error(self) -> None:
        with pytest.raises(APIClientError):
            raise AuthenticationError("sin key")

    def test_capture_rate_limit_as_chimuelo_exception(self) -> None:
        with pytest.raises(ChimueloException):
            raise RateLimitExceededError("agotado")

    def test_capture_binance_api_error_as_api_client_error(self) -> None:
        with pytest.raises(APIClientError):
            raise BinanceAPIError(403, -2014, "Invalid API-key format.")

    def test_capture_all_m2_errors_as_api_client_error(self) -> None:
        errors = [
            AuthenticationError("auth"),
            RateLimitExceededError("rl"),
            BinanceAPIError(400, -1121, "sym"),
        ]
        for exc in errors:
            assert isinstance(exc, APIClientError)


class TestExceptionIsolation:
    def test_authentication_is_not_rate_limit(self) -> None:
        assert not isinstance(AuthenticationError("x"), RateLimitExceededError)

    def test_binance_api_error_is_not_authentication(self) -> None:
        assert not isinstance(BinanceAPIError(400, -1, "x"), AuthenticationError)

    def test_m2_errors_are_not_m1_exchange_config_errors(self) -> None:
        from chimuelo_prime.exchange_config.exceptions import ExchangeConfigError

        assert not isinstance(APIClientError("x"), ExchangeConfigError)
