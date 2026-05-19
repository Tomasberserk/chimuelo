"""Tests para ExchangeConfigService (service.py).

Usa el fixture JSON real de Binance (exchange_info_solusdt.json) para
mockear la respuesta del cliente HTTP sin tocar la red.

Estrategia de mocking:
    Se pasa un `MagicMock` en lugar de un `BinancePublicClient` real.
    Esto garantiza aislamiento total: el servicio se testa solo, sin
    depender del comportamiento del cliente HTTP.

Cubre:
    - Parseo exitoso → SymbolFilters correcto.
    - InvalidSymbolError si el símbolo no existe en la respuesta.
    - FilterParsingError si faltan filtros requeridos.
    - FilterParsingError si un campo específico dentro del filtro falta.
    - FilterParsingError si un valor no es convertible a Decimal.
    - Verificación de que los valores Decimal son exactos (no floats).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from chimuelo_prime.exchange_config.client import BinancePublicClient
from chimuelo_prime.exchange_config.exceptions import (
    FilterParsingError,
    InvalidSymbolError,
)
from chimuelo_prime.exchange_config.models import SymbolFilters
from chimuelo_prime.exchange_config.service import ExchangeConfigService

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "exchange_info_solusdt.json"


@pytest.fixture()
def exchange_info_payload() -> dict:  # type: ignore[type-arg]
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture()
def mock_client(exchange_info_payload: dict) -> MagicMock:  # type: ignore[type-arg]
    """Mock de BinancePublicClient que retorna el fixture JSON."""
    client = MagicMock(spec=BinancePublicClient)
    client.get_exchange_info.return_value = exchange_info_payload
    return client


@pytest.fixture()
def service(mock_client: MagicMock) -> ExchangeConfigService:
    return ExchangeConfigService(client=mock_client)


# --------------------------------------------------------------------------- #
# Tests: parseo exitoso
# --------------------------------------------------------------------------- #
class TestFetchSymbolFiltersSuccess:
    def test_returns_symbol_filters(self, service: ExchangeConfigService) -> None:
        result = service.fetch_symbol_filters("SOLUSDT")
        assert isinstance(result, SymbolFilters)

    def test_symbol_is_correct(self, service: ExchangeConfigService) -> None:
        result = service.fetch_symbol_filters("SOLUSDT")
        assert result.symbol == "SOLUSDT"

    def test_tick_size_is_decimal(self, service: ExchangeConfigService) -> None:
        result = service.fetch_symbol_filters("SOLUSDT")
        assert isinstance(result.tick_size, Decimal)
        assert result.tick_size == Decimal("0.01")

    def test_min_notional_is_decimal(self, service: ExchangeConfigService) -> None:
        result = service.fetch_symbol_filters("SOLUSDT")
        assert isinstance(result.min_notional, Decimal)
        assert result.min_notional == Decimal("5.00")

    def test_step_size_correct(self, service: ExchangeConfigService) -> None:
        result = service.fetch_symbol_filters("SOLUSDT")
        assert result.step_size == Decimal("0.001")

    def test_pct_up_correct(self, service: ExchangeConfigService) -> None:
        result = service.fetch_symbol_filters("SOLUSDT")
        assert result.pct_up == Decimal("5")

    def test_pct_down_correct(self, service: ExchangeConfigService) -> None:
        result = service.fetch_symbol_filters("SOLUSDT")
        assert result.pct_down == Decimal("0.2")

    def test_no_float_values(self, service: ExchangeConfigService) -> None:
        """Ningún campo financiero debe ser float — regla innegociable."""
        result = service.fetch_symbol_filters("SOLUSDT")
        financial_fields = [
            result.tick_size,
            result.min_price,
            result.max_price,
            result.step_size,
            result.min_qty,
            result.max_qty,
            result.min_notional,
            result.pct_up,
            result.pct_down,
        ]
        for field in financial_fields:
            assert isinstance(field, Decimal), f"Campo es float: {field!r}"
            assert not isinstance(field, float)

    def test_client_called_with_correct_symbol(
        self, service: ExchangeConfigService, mock_client: MagicMock
    ) -> None:
        service.fetch_symbol_filters("SOLUSDT")
        mock_client.get_exchange_info.assert_called_once_with("SOLUSDT")


# --------------------------------------------------------------------------- #
# Tests: símbolo no encontrado
# --------------------------------------------------------------------------- #
class TestInvalidSymbol:
    def test_nonexistent_symbol_raises(self, service: ExchangeConfigService) -> None:
        """Símbolo no presente en la respuesta debe lanzar InvalidSymbolError."""
        with pytest.raises(InvalidSymbolError, match="XYZUSDT"):
            service.fetch_symbol_filters("XYZUSDT")

    def test_empty_symbols_list_raises(self, mock_client: MagicMock) -> None:
        mock_client.get_exchange_info.return_value = {"symbols": []}
        svc = ExchangeConfigService(client=mock_client)
        with pytest.raises(InvalidSymbolError):
            svc.fetch_symbol_filters("SOLUSDT")

    def test_missing_symbols_key_raises(self, mock_client: MagicMock) -> None:
        """Respuesta sin clave 'symbols' debe lanzar InvalidSymbolError."""
        mock_client.get_exchange_info.return_value = {}
        svc = ExchangeConfigService(client=mock_client)
        with pytest.raises(InvalidSymbolError):
            svc.fetch_symbol_filters("SOLUSDT")


# --------------------------------------------------------------------------- #
# Tests: filtros faltantes o malformados
# --------------------------------------------------------------------------- #
class TestFilterParsingErrors:
    def _make_payload_without_filter(
        self,
        exchange_info_payload: dict,  # type: ignore[type-arg]
        filter_type: str,
    ) -> dict:  # type: ignore[type-arg]
        """Retorna el payload con el filterType especificado eliminado."""
        import copy

        payload = copy.deepcopy(exchange_info_payload)
        payload["symbols"][0]["filters"] = [
            f for f in payload["symbols"][0]["filters"] if f.get("filterType") != filter_type
        ]
        return payload

    def test_missing_price_filter_raises(
        self,
        mock_client: MagicMock,
        exchange_info_payload: dict,  # type: ignore[type-arg]
    ) -> None:
        mock_client.get_exchange_info.return_value = self._make_payload_without_filter(
            exchange_info_payload, "PRICE_FILTER"
        )
        svc = ExchangeConfigService(client=mock_client)
        with pytest.raises(FilterParsingError, match="PRICE_FILTER"):
            svc.fetch_symbol_filters("SOLUSDT")

    def test_missing_lot_size_raises(
        self,
        mock_client: MagicMock,
        exchange_info_payload: dict,  # type: ignore[type-arg]
    ) -> None:
        mock_client.get_exchange_info.return_value = self._make_payload_without_filter(
            exchange_info_payload, "LOT_SIZE"
        )
        svc = ExchangeConfigService(client=mock_client)
        with pytest.raises(FilterParsingError, match="LOT_SIZE"):
            svc.fetch_symbol_filters("SOLUSDT")

    def test_missing_notional_raises(
        self,
        mock_client: MagicMock,
        exchange_info_payload: dict,  # type: ignore[type-arg]
    ) -> None:
        mock_client.get_exchange_info.return_value = self._make_payload_without_filter(
            exchange_info_payload, "NOTIONAL"
        )
        svc = ExchangeConfigService(client=mock_client)
        with pytest.raises(FilterParsingError, match="NOTIONAL"):
            svc.fetch_symbol_filters("SOLUSDT")

    def test_missing_percent_price_raises(
        self,
        mock_client: MagicMock,
        exchange_info_payload: dict,  # type: ignore[type-arg]
    ) -> None:
        mock_client.get_exchange_info.return_value = self._make_payload_without_filter(
            exchange_info_payload, "PERCENT_PRICE_BY_SIDE"
        )
        svc = ExchangeConfigService(client=mock_client)
        with pytest.raises(FilterParsingError, match="PERCENT_PRICE_BY_SIDE"):
            svc.fetch_symbol_filters("SOLUSDT")

    def test_invalid_decimal_value_raises(
        self,
        mock_client: MagicMock,
        exchange_info_payload: dict,  # type: ignore[type-arg]
    ) -> None:
        """Un tickSize con valor no numérico debe lanzar FilterParsingError."""
        import copy

        payload = copy.deepcopy(exchange_info_payload)
        for f in payload["symbols"][0]["filters"]:
            if f.get("filterType") == "PRICE_FILTER":
                f["tickSize"] = "NOT_A_NUMBER"
        mock_client.get_exchange_info.return_value = payload
        svc = ExchangeConfigService(client=mock_client)
        with pytest.raises(FilterParsingError):
            svc.fetch_symbol_filters("SOLUSDT")

    def test_missing_field_in_filter_raises(
        self,
        mock_client: MagicMock,
        exchange_info_payload: dict,  # type: ignore[type-arg]
    ) -> None:
        """Un filtro sin el campo `tickSize` debe lanzar FilterParsingError."""
        import copy

        payload = copy.deepcopy(exchange_info_payload)
        for f in payload["symbols"][0]["filters"]:
            if f.get("filterType") == "PRICE_FILTER":
                del f["tickSize"]
        mock_client.get_exchange_info.return_value = payload
        svc = ExchangeConfigService(client=mock_client)
        with pytest.raises(FilterParsingError):
            svc.fetch_symbol_filters("SOLUSDT")
