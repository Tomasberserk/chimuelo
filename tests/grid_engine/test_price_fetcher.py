"""Tests para PriceFetcher (M5).

Cubre los 3 casos obligatorios de MARTA:
    26. Respuesta {"price": "123.45"} → Decimal("123.45").
    27. Respuesta {"price": 123.45} (float) → PriceFetchError.
    28. Respuesta sin clave 'price' → PriceFetchError.

Adicionalmente:
    - Resultado es siempre Decimal, nunca float ni str.
    - BinanceAPIError del cliente HTTP se propaga sin envolver.
    - Peso correcto (WEIGHT_TICKER_PRICE=2) se pasa al cliente.
    - Parámetro symbol correcto se pasa al cliente.
    - Valor no convertible a Decimal → PriceFetchError.
    - Precio con muchos decimales preserva precisión exacta.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from chimuelo_prime.api_client.client import BinanceAuthenticatedClient
from chimuelo_prime.api_client.exceptions import BinanceAPIError
from chimuelo_prime.grid_engine.exceptions import PriceFetchError
from chimuelo_prime.grid_engine.price_fetcher import PriceFetcher
from chimuelo_prime.shared.constants import WEIGHT_TICKER_PRICE


@pytest.fixture
def mock_client() -> MagicMock:
    return MagicMock(spec=BinanceAuthenticatedClient)


@pytest.fixture
def price_fetcher(mock_client: MagicMock) -> PriceFetcher:
    return PriceFetcher(client=mock_client)


# ---------------------------------------------------------------------------
# Caso 26: respuesta válida → Decimal correcto
# ---------------------------------------------------------------------------
class TestGetCurrentPriceSuccess:
    def test_returns_decimal_from_string_price(
        self, price_fetcher: PriceFetcher, mock_client: MagicMock
    ) -> None:
        mock_client.get.return_value = {"symbol": "SOLUSDT", "price": "123.45"}
        result = price_fetcher.get_current_price("SOLUSDT")
        assert result == Decimal("123.45")

    def test_result_type_is_decimal(
        self, price_fetcher: PriceFetcher, mock_client: MagicMock
    ) -> None:
        mock_client.get.return_value = {"symbol": "SOLUSDT", "price": "123.45"}
        result = price_fetcher.get_current_price("SOLUSDT")
        assert isinstance(result, Decimal)

    def test_preserves_decimal_precision(
        self, price_fetcher: PriceFetcher, mock_client: MagicMock
    ) -> None:
        mock_client.get.return_value = {"symbol": "SOLUSDT", "price": "123.45678901"}
        result = price_fetcher.get_current_price("SOLUSDT")
        assert result == Decimal("123.45678901")

    def test_calls_correct_endpoint(
        self, price_fetcher: PriceFetcher, mock_client: MagicMock
    ) -> None:
        mock_client.get.return_value = {"symbol": "SOLUSDT", "price": "100.00"}
        price_fetcher.get_current_price("SOLUSDT")
        mock_client.get.assert_called_once_with(
            "/api/v3/ticker/price",
            params={"symbol": "SOLUSDT"},
            weight=WEIGHT_TICKER_PRICE,
        )

    def test_passes_symbol_correctly(
        self, price_fetcher: PriceFetcher, mock_client: MagicMock
    ) -> None:
        mock_client.get.return_value = {"symbol": "BTCUSDT", "price": "50000.00"}
        price_fetcher.get_current_price("BTCUSDT")
        _, kwargs = mock_client.get.call_args
        assert kwargs["params"]["symbol"] == "BTCUSDT"

    def test_uses_correct_weight(self, price_fetcher: PriceFetcher, mock_client: MagicMock) -> None:
        mock_client.get.return_value = {"symbol": "SOLUSDT", "price": "100.00"}
        price_fetcher.get_current_price("SOLUSDT")
        _, kwargs = mock_client.get.call_args
        assert kwargs["weight"] == WEIGHT_TICKER_PRICE
        assert kwargs["weight"] == 2


# ---------------------------------------------------------------------------
# Caso 27: float en respuesta → PriceFetchError
# ---------------------------------------------------------------------------
class TestGetCurrentPriceFloatRejection:
    def test_float_price_raises_price_fetch_error(
        self, price_fetcher: PriceFetcher, mock_client: MagicMock
    ) -> None:
        mock_client.get.return_value = {"symbol": "SOLUSDT", "price": 123.45}
        with pytest.raises(PriceFetchError):
            price_fetcher.get_current_price("SOLUSDT")

    def test_float_zero_raises_price_fetch_error(
        self, price_fetcher: PriceFetcher, mock_client: MagicMock
    ) -> None:
        mock_client.get.return_value = {"symbol": "SOLUSDT", "price": 0.0}
        with pytest.raises(PriceFetchError):
            price_fetcher.get_current_price("SOLUSDT")

    def test_float_error_message_explains_reason(
        self, price_fetcher: PriceFetcher, mock_client: MagicMock
    ) -> None:
        mock_client.get.return_value = {"symbol": "SOLUSDT", "price": 123.45}
        with pytest.raises(PriceFetchError) as exc_info:
            price_fetcher.get_current_price("SOLUSDT")
        assert "float" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# Caso 28: clave 'price' ausente → PriceFetchError
# ---------------------------------------------------------------------------
class TestGetCurrentPriceMissingKey:
    def test_missing_price_key_raises_price_fetch_error(
        self, price_fetcher: PriceFetcher, mock_client: MagicMock
    ) -> None:
        mock_client.get.return_value = {"symbol": "SOLUSDT"}
        with pytest.raises(PriceFetchError):
            price_fetcher.get_current_price("SOLUSDT")

    def test_empty_response_raises_price_fetch_error(
        self, price_fetcher: PriceFetcher, mock_client: MagicMock
    ) -> None:
        mock_client.get.return_value = {}
        with pytest.raises(PriceFetchError):
            price_fetcher.get_current_price("SOLUSDT")

    def test_missing_key_error_message_mentions_price(
        self, price_fetcher: PriceFetcher, mock_client: MagicMock
    ) -> None:
        mock_client.get.return_value = {"symbol": "SOLUSDT"}
        with pytest.raises(PriceFetchError) as exc_info:
            price_fetcher.get_current_price("SOLUSDT")
        assert "price" in str(exc_info.value)


# ---------------------------------------------------------------------------
# BinanceAPIError se propaga sin envolver
# ---------------------------------------------------------------------------
class TestGetCurrentPriceBinanceError:
    def test_binance_api_error_propagates_unwrapped(
        self, price_fetcher: PriceFetcher, mock_client: MagicMock
    ) -> None:
        mock_client.get.side_effect = BinanceAPIError(400, -1100, "Bad request")
        with pytest.raises(BinanceAPIError) as exc_info:
            price_fetcher.get_current_price("SOLUSDT")
        assert exc_info.value.binance_code == -1100

    def test_binance_error_is_not_wrapped_in_price_fetch_error(
        self, price_fetcher: PriceFetcher, mock_client: MagicMock
    ) -> None:
        mock_client.get.side_effect = BinanceAPIError(503, -1000, "Service unavailable")
        with pytest.raises(BinanceAPIError):
            price_fetcher.get_current_price("SOLUSDT")


# ---------------------------------------------------------------------------
# Valor no convertible a Decimal
# ---------------------------------------------------------------------------
class TestGetCurrentPriceInvalidValue:
    def test_non_numeric_string_raises_price_fetch_error(
        self, price_fetcher: PriceFetcher, mock_client: MagicMock
    ) -> None:
        mock_client.get.return_value = {"symbol": "SOLUSDT", "price": "not_a_number"}
        with pytest.raises(PriceFetchError):
            price_fetcher.get_current_price("SOLUSDT")

    def test_none_price_raises_price_fetch_error(
        self, price_fetcher: PriceFetcher, mock_client: MagicMock
    ) -> None:
        mock_client.get.return_value = {"symbol": "SOLUSDT", "price": None}
        with pytest.raises(PriceFetchError):
            price_fetcher.get_current_price("SOLUSDT")
