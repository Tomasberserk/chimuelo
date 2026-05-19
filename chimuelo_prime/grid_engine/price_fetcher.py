"""Obtención del precio spot actual de un símbolo via Binance (M5).

PriceFetcher encapsula la única llamada HTTP que GridEngine hace directamente:
GET /api/v3/ticker/price. Existe para que GridEngine no importe
BinanceAuthenticatedClient — solo PriceFetcher depende de M2.

Contrato:
    - Retorna siempre Decimal. Nunca float.
    - BinanceAPIError (error HTTP de Binance) se propaga sin envolver.
    - Respuesta malformada (sin clave 'price' o valor no convertible) → PriceFetchError.
    - Float en la respuesta → PriceFetchError (Binance siempre devuelve strings;
      un float indica comportamiento inesperado de la API o del mock).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from chimuelo_prime.api_client.client import BinanceAuthenticatedClient
from chimuelo_prime.exchange_config.logger import get_logger
from chimuelo_prime.grid_engine.exceptions import PriceFetchError
from chimuelo_prime.shared.constants import WEIGHT_TICKER_PRICE


class PriceFetcher:
    """Obtiene el precio spot actual de un símbolo via GET /api/v3/ticker/price.

    Args:
        client: Cliente HTTP autenticado de M2.
    """

    def __init__(self, client: BinanceAuthenticatedClient) -> None:
        self._client = client
        self._log = get_logger(__name__)

    def get_current_price(self, symbol: str) -> Decimal:
        """Consulta el precio spot actual del símbolo.

        GET /api/v3/ticker/price?symbol=SOLUSDT
        → {"symbol": "SOLUSDT", "price": "123.45"}

        Args:
            symbol: Par de trading (ej. "SOLUSDT").

        Returns:
            Precio actual como Decimal exacto.

        Raises:
            PriceFetchError:  respuesta malformada (clave ausente, float, o valor
                              no convertible a Decimal).
            BinanceAPIError:  el endpoint retornó error HTTP — se propaga sin envolver.
        """
        response: dict[str, Any] = self._client.get(
            "/api/v3/ticker/price",
            params={"symbol": symbol},
            weight=WEIGHT_TICKER_PRICE,
        )

        if "price" not in response:
            raise PriceFetchError(
                f"Respuesta de /api/v3/ticker/price no contiene clave 'price': {response!r}"
            )

        raw = response["price"]

        if isinstance(raw, float):
            raise PriceFetchError(
                f"Precio recibido como float ({raw!r}). "
                "Binance siempre devuelve strings — comportamiento inesperado."
            )

        try:
            price = Decimal(str(raw))
        except InvalidOperation as exc:
            raise PriceFetchError(
                f"No se pudo convertir precio a Decimal: {raw!r}"
            ) from exc

        self._log.debug("price_fetcher.price_fetched", symbol=symbol, price=str(price))
        return price
