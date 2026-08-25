"""Cliente HTTP para endpoints públicos de Binance.

Responsabilidades (SRP):
    - Encapsular `requests.Session` con timeout configurado.
    - Convertir errores de red en excepciones tipificadas del proyecto.
    - Logging estructurado de cada request/response.
    - NO firma requests (endpoints públicos). La autenticación es M2.

Excepciones que produce:
    - `ExchangeUnreachableError`: timeout, error de red, HTTP 5xx.

REGLA: la `base_url` se inyecta en el constructor — nunca hardcodeada aquí.
"""

from __future__ import annotations

from typing import Any

import requests
import requests.exceptions

from chimuelo_prime.exchange_config.exceptions import ExchangeUnreachableError
from chimuelo_prime.exchange_config.logger import get_logger


class BinancePublicClient:
    """Wrapper HTTP sobre endpoints públicos (no autenticados) de Binance.

    Diseñado para ser inyectado como dependencia en `ExchangeConfigService`.
    No gestiona autenticación (eso corresponde a M2: API Client).

    Args:
        base_url: URL base del API, ej. "https://testnet.binance.vision".
                  Debe provenir de `ChimueloConfig.active_env.base_url`.
        timeout:  Timeout en segundos para cada request HTTP.
    """

    def __init__(self, base_url: str, timeout: int = 10) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._session = requests.Session()
        self._log = get_logger(__name__)

    def get_exchange_info(self, symbol: str) -> dict[str, Any]:
        """Obtiene la información de exchange para un símbolo específico.

        Llama a `GET /api/v3/exchangeInfo?symbol=<symbol>`.

        Args:
            symbol: par de trading, ej. "SOLUSDT".

        Returns:
            Diccionario con la respuesta JSON de Binance.

        Raises:
            ExchangeUnreachableError: si hay timeout, error de red o HTTP ≥ 400.
        """
        url = f"{self._base_url}/api/v3/exchangeInfo"
        self._log.info(
            "binance.request",
            method="GET",
            url=url,
            symbol=symbol,
        )

        try:
            response = self._session.get(
                url,
                params={"symbol": symbol},
                timeout=self._timeout,
            )
            response.raise_for_status()
        except requests.exceptions.Timeout as exc:
            raise ExchangeUnreachableError(
                f"Timeout ({self._timeout}s) al contactar {url} [symbol={symbol}]"
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise ExchangeUnreachableError(
                f"Error de conexión a {url} [symbol={symbol}]: {exc}"
            ) from exc
        except requests.exceptions.HTTPError as exc:
            status = response.status_code if response is not None else "unknown"
            raise ExchangeUnreachableError(
                f"HTTP {status} en {url} [symbol={symbol}]: {exc}"
            ) from exc

        data: dict[str, Any] = response.json()
        self._log.info(
            "binance.response",
            url=url,
            symbol=symbol,
            status_code=response.status_code,
        )
        return data

    def get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        weight: int = 1,
    ) -> dict[str, Any]:
        """GET público genérico (sin autenticación).

        Usado por PriceFetcher y cualquier otro componente que necesite
        consultar endpoints públicos de Binance sin firma HMAC.
        El parámetro `weight` se acepta por compatibilidad de interfaz pero
        no se aplica rate-limiting aquí (responsabilidad del cliente autenticado).
        """
        url = f"{self._base_url}{endpoint}"
        try:
            response = self._session.get(url, params=params or {}, timeout=self._timeout)
            response.raise_for_status()
        except requests.exceptions.Timeout as exc:
            raise ExchangeUnreachableError(f"Timeout ({self._timeout}s) en {url}") from exc
        except requests.exceptions.ConnectionError as exc:
            raise ExchangeUnreachableError(f"Error de conexión a {url}: {exc}") from exc
        except requests.exceptions.HTTPError as exc:
            raise ExchangeUnreachableError(f"HTTP {response.status_code} en {url}: {exc}") from exc
        return response.json()  # type: ignore[no-any-return]

    def close(self) -> None:
        """Cierra la sesión HTTP y libera recursos de conexión."""
        self._session.close()
