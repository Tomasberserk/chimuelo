"""Fachada pública del módulo exchange_config.

`ExchangeConfigService` es el único punto de entrada para obtener
`SymbolFilters` desde Binance. Implementa el principio SRP:
    - `BinancePublicClient` hace el HTTP.
    - `ExchangeConfigService` parsea y construye el modelo de dominio.
    - Los llamadores (M2, M5) solo ven `fetch_symbol_filters()`.

Excepciones que produce:
    - `ExchangeUnreachableError`: propagada desde el cliente HTTP.
    - `InvalidSymbolError`: símbolo no existe en la respuesta de Binance.
    - `FilterParsingError`: estructura inesperada o campos faltantes.

REGLA: cero floats. Todos los valores de filtros se construyen con `Decimal(str_value)`.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from chimuelo_prime.exchange_config.client import BinancePublicClient
from chimuelo_prime.exchange_config.exceptions import (
    FilterParsingError,
    InvalidSymbolError,
)
from chimuelo_prime.exchange_config.logger import get_logger
from chimuelo_prime.exchange_config.models import SymbolFilters

# Filtros que el servicio necesita extraer obligatoriamente.
# Si alguno falta en la respuesta de Binance, es un FilterParsingError.
_REQUIRED_FILTER_TYPES: frozenset[str] = frozenset(
    {"PRICE_FILTER", "LOT_SIZE", "NOTIONAL", "PERCENT_PRICE_BY_SIDE"}
)


class ExchangeConfigService:
    """Fachada que obtiene y parsea los filtros operativos de un símbolo.

    Recibe `BinancePublicClient` por inyección de dependencias (no lo crea
    internamente). Esto cumple el Dependency Inversion Principle: el servicio
    depende de una abstracción, no de una implementación concreta.

    Args:
        client: instancia de `BinancePublicClient` configurada con la URL correcta.
    """

    def __init__(self, client: BinancePublicClient) -> None:
        self._client = client
        self._log = get_logger(__name__)

    def fetch_symbol_filters(self, symbol: str) -> SymbolFilters:
        """Obtiene y construye `SymbolFilters` para el símbolo indicado.

        Flujo:
            1. GET /api/v3/exchangeInfo?symbol=<symbol>
            2. Localiza el símbolo en la respuesta.
            3. Indexa los filtros por `filterType`.
            4. Valida que todos los filtros requeridos estén presentes.
            5. Construye `SymbolFilters` con valores `Decimal`.

        Args:
            symbol: par de trading, ej. "SOLUSDT".

        Returns:
            `SymbolFilters` inmutable con todos los filtros validados.

        Raises:
            ExchangeUnreachableError: el cliente HTTP no pudo contactar Binance.
            InvalidSymbolError:       el símbolo no existe en la respuesta.
            FilterParsingError:       la respuesta tiene estructura inesperada.
        """
        self._log.info("service.fetch_filters.start", symbol=symbol)

        raw = self._client.get_exchange_info(symbol)
        symbol_data = self._find_symbol(raw, symbol)
        filters = self._index_filters(symbol_data, symbol)
        result = self._build_symbol_filters(symbol, filters)

        self._log.info(
            "service.fetch_filters.done",
            symbol=symbol,
            tick_size=str(result.tick_size),
            min_notional=str(result.min_notional),
        )
        return result

    # --------------------------------------------------------------------- #
    # Métodos privados de parsing
    # --------------------------------------------------------------------- #
    def _find_symbol(self, data: dict[str, Any], symbol: str) -> dict[str, Any]:
        """Localiza el dict de un símbolo dentro de la lista `symbols`."""
        symbols_list: list[dict[str, Any]] = data.get("symbols", [])
        for entry in symbols_list:
            if entry.get("symbol") == symbol:
                return entry
        raise InvalidSymbolError(
            f"Símbolo '{symbol}' no encontrado en la respuesta de exchangeInfo. "
            "Verifica que el símbolo esté habilitado en Binance."
        )

    def _index_filters(self, symbol_data: dict[str, Any], symbol: str) -> dict[str, dict[str, Any]]:
        """Convierte la lista de filtros en un dict indexado por `filterType`.

        Valida que todos los tipos requeridos estén presentes.
        """
        raw_filters: list[dict[str, Any]] = symbol_data.get("filters", [])
        indexed: dict[str, dict[str, Any]] = {
            f["filterType"]: f for f in raw_filters if "filterType" in f
        }
        missing = _REQUIRED_FILTER_TYPES - indexed.keys()
        if missing:
            raise FilterParsingError(
                f"Filtros requeridos faltantes para '{symbol}': {sorted(missing)}. "
                "La respuesta de Binance puede haber cambiado su estructura."
            )
        return indexed

    def _build_symbol_filters(
        self,
        symbol: str,
        filters: dict[str, dict[str, Any]],
    ) -> SymbolFilters:
        """Construye `SymbolFilters` desde el dict de filtros indexados.

        Todos los valores numéricos vienen como strings en la API de Binance
        (ej. "0.01000000"). Se convierten a `Decimal` desde string, nunca
        desde float — esto garantiza precisión exacta en base 10.
        """
        try:
            pf = filters["PRICE_FILTER"]
            ls = filters["LOT_SIZE"]
            no = filters["NOTIONAL"]
            pp = filters["PERCENT_PRICE_BY_SIDE"]

            return SymbolFilters(
                symbol=symbol,
                tick_size=Decimal(pf["tickSize"]),
                min_price=Decimal(pf["minPrice"]),
                max_price=Decimal(pf["maxPrice"]),
                step_size=Decimal(ls["stepSize"]),
                min_qty=Decimal(ls["minQty"]),
                max_qty=Decimal(ls["maxQty"]),
                min_notional=Decimal(no["minNotional"]),
                pct_up=Decimal(pp["bidMultiplierUp"]),
                pct_down=Decimal(pp["bidMultiplierDown"]),
            )
        except KeyError as exc:
            raise FilterParsingError(
                f"Campo faltante en filtros de '{symbol}': {exc}. "
                "Actualiza el parser si la API de Binance cambió."
            ) from exc
        except InvalidOperation as exc:
            raise FilterParsingError(
                f"Valor no convertible a Decimal en filtros de '{symbol}': {exc}. "
                "Binance envió un valor inesperado."
            ) from exc
