"""Cliente HTTP autenticado para la API de Binance (M2).

Responsabilidades (SRP):
    - Firma de requests vía BinanceSigner (HMAC-SHA256).
    - Aplicación de rate limits vía RateLimiter (token bucket compartido).
    - Retry con exponential backoff + jitter en 429 y 5xx.
    - Parseo de errores Binance en BinanceAPIError (campos tipificados).
    - Logging estructurado de cada request, response y reintento.

NO conoce:
    - Lógica de órdenes del grid → M4/M5.
    - Filtros de exchange → M1.
    - Estado persistente → M3.

Flujo de un request autenticado:
    1. consume_weight / consume_order  (bloquea si rate limit lo requiere)
    2. sign_params                     (añade timestamp, recvWindow, signature)
    3. session.request                 (con header X-MBX-APIKEY)
    4. Si ok → return JSON
    5. Si 429 → sleep + reintento (hasta max_retries)
    6. Si 5xx → sleep + reintento (hasta max_retries)
    7. Si 4xx (≠429) → BinanceAPIError sin reintento
    8. Si timeout/red → ExchangeUnreachableError sin reintento
"""

from __future__ import annotations

import random
import time
from typing import Any, NoReturn

import requests
import requests.exceptions
from pydantic import ValidationError

from chimuelo_prime.api_client.exceptions import BinanceAPIError, RateLimitExceededError
from chimuelo_prime.api_client.models import BinanceErrorResponse, RetryConfig
from chimuelo_prime.api_client.rate_limiter import RateLimiter
from chimuelo_prime.api_client.signing import BinanceSigner
from chimuelo_prime.exchange_config.exceptions import ExchangeUnreachableError
from chimuelo_prime.exchange_config.logger import get_logger

_SERVER_ERROR_CODES = frozenset({500, 502, 503, 504})


class BinanceAuthenticatedClient:
    """Cliente HTTP autenticado para endpoints privados de Binance.

    Recibe todas sus dependencias por inyección — nunca las crea internamente.
    Esto garantiza:
        - Testabilidad (mocks de signer y rate_limiter).
        - Que el RateLimiter es compartido si hay múltiples clientes (M7).
        - Open/Closed: comportamiento de retry configurable sin subclasificar.

    Args:
        base_url:      URL base del API (ej. "https://testnet.binance.vision").
        signer:        BinanceSigner configurado con las credenciales del bot.
        rate_limiter:  Instancia compartida del RateLimiter (UNA por proceso).
        retry_config:  Parámetros de backoff. Si None, usa defaults razonables.
        timeout:       Timeout HTTP en segundos.
    """

    def __init__(
        self,
        base_url: str,
        signer: BinanceSigner,
        rate_limiter: RateLimiter,
        retry_config: RetryConfig | None = None,
        timeout: int = 10,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._signer = signer
        self._rate_limiter = rate_limiter
        self._retry_config = retry_config or RetryConfig()
        self._timeout = timeout
        self._session = requests.Session()
        self._log = get_logger(__name__)

    # --------------------------------------------------------------------- #
    # API pública
    # --------------------------------------------------------------------- #
    def get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        weight: int = 1,
    ) -> dict[str, Any]:
        """GET autenticado. Params van como query string (firmados)."""
        return self._request("GET", endpoint, params or {}, weight, is_order=False)

    def post(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        weight: int = 1,
        is_order: bool = False,
    ) -> dict[str, Any]:
        """POST autenticado. Params van como query string (firmados).

        Args:
            is_order: True para órdenes nuevas — consume también el order bucket.
        """
        return self._request("POST", endpoint, params or {}, weight, is_order=is_order)

    def delete(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        weight: int = 1,
    ) -> dict[str, Any]:
        """DELETE autenticado. Params van como query string (firmados)."""
        return self._request("DELETE", endpoint, params or {}, weight, is_order=False)

    def sync_server_time(self, server_time_ms: int) -> None:
        """Sincroniza el reloj local con el servidor de Binance.

        Calcula el offset y lo inyecta en el signer. Previene -1021.

        El orquestador (M7) obtiene server_time_ms via:
            data = public_client.get_exchange_info("SOLUSDT")  # cualquier call
            # o mejor: GET /api/v3/time → {"serverTime": <ms>}

        Args:
            server_time_ms: timestamp del servidor de Binance en milisegundos.
        """
        local_ms = int(time.time() * 1000)
        offset = server_time_ms - local_ms
        self._signer.set_server_time_offset(offset)
        self._log.info("client.time_sync", offset_ms=offset)

    def close(self) -> None:
        """Cierra la sesión HTTP y libera recursos de conexión."""
        self._session.close()

    # --------------------------------------------------------------------- #
    # Internos
    # --------------------------------------------------------------------- #
    def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any],
        weight: int,
        is_order: bool,
    ) -> dict[str, Any]:
        if is_order:
            self._rate_limiter.consume_order(weight)
        else:
            self._rate_limiter.consume_weight(weight)

        signed = self._signer.sign_params(params)
        url = f"{self._base_url}/{endpoint.lstrip('/')}"
        headers = {"X-MBX-APIKEY": self._signer.api_key}

        self._log.info("client.request", method=method, url=url, weight=weight)

        for attempt in range(self._retry_config.max_retries + 1):
            try:
                response = self._session.request(
                    method=method,
                    url=url,
                    params=signed,
                    timeout=self._timeout,
                    headers=headers,
                )
            except requests.exceptions.Timeout as exc:
                raise ExchangeUnreachableError(f"Timeout ({self._timeout}s) en {url}") from exc
            except requests.exceptions.ConnectionError as exc:
                raise ExchangeUnreachableError(f"Error de conexión a {url}: {exc}") from exc

            if response.ok:
                self._log.info(
                    "client.response",
                    method=method,
                    url=url,
                    status_code=response.status_code,
                )
                return response.json()  # type: ignore[no-any-return]

            if response.status_code == 429:
                if attempt >= self._retry_config.max_retries:
                    raise RateLimitExceededError(
                        f"Rate limit excedido en {url} tras {attempt + 1} intento(s). "
                        "Revisa el RateLimiter compartido o reduce la frecuencia de requests."
                    )
                retry_after = int(response.headers.get("Retry-After", "0"))
                backoff = self._calc_backoff(attempt)
                sleep_time = max(float(retry_after), backoff)
                self._log.warning(
                    "client.rate_limit_retry",
                    attempt=attempt + 1,
                    sleep_seconds=round(sleep_time, 3),
                    retry_after_header=retry_after,
                )
                time.sleep(sleep_time)
                continue

            if response.status_code in _SERVER_ERROR_CODES:
                if attempt >= self._retry_config.max_retries:
                    raise ExchangeUnreachableError(
                        f"HTTP {response.status_code} en {url} tras {attempt + 1} intento(s)."
                    )
                backoff = self._calc_backoff(attempt)
                self._log.warning(
                    "client.server_error_retry",
                    status_code=response.status_code,
                    attempt=attempt + 1,
                    sleep_seconds=round(backoff, 3),
                )
                time.sleep(backoff)
                continue

            # 4xx que no es 429 — no se reintenta
            self._raise_binance_error(response)

        # Inalcanzable: el loop siempre retorna o lanza antes de llegar aquí.
        raise ExchangeUnreachableError(  # pragma: no cover
            f"Estado inesperado tras reintentos en {url}"
        )

    def _calc_backoff(self, attempt: int) -> float:
        """Calcula delay con exponential backoff y jitter uniforme."""
        delay: float = self._retry_config.base_delay_seconds * float(2**attempt)
        delay += random.uniform(0, self._retry_config.jitter_seconds)
        return min(delay, self._retry_config.max_delay_seconds)

    def _raise_binance_error(self, response: requests.Response) -> NoReturn:
        """Parsea el body de error de Binance y lanza BinanceAPIError."""
        try:
            error_data = BinanceErrorResponse.model_validate(response.json())
            raise BinanceAPIError(
                status_code=response.status_code,
                binance_code=error_data.code,
                msg=error_data.msg,
            )
        except (ValueError, ValidationError):
            raise BinanceAPIError(
                status_code=response.status_code,
                binance_code=-1,
                msg=response.text[:300],
            ) from None
