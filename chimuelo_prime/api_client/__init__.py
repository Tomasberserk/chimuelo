"""Exports públicos del módulo api_client (M2).

API pública:
    BinanceAuthenticatedClient — cliente HTTP autenticado (firma + rate limit + retry).
    BinanceSigner              — firma HMAC-SHA256 de requests.
    RateLimiter                — token bucket compartido (instancia única por proceso).
    TokenBucket                — bucket individual (expuesto para tests y composición).

Modelos:
    BinanceCredentials   — credenciales leídas desde variables de entorno.
    APIClientConfig      — configuración completa del cliente.
    RateLimitConfig      — parámetros del token bucket.
    RetryConfig          — parámetros de backoff.
    BinanceErrorResponse — parseo de errores de Binance.

Excepciones:
    APIClientError         — raíz de errores de M2.
    AuthenticationError    — credenciales inválidas o faltantes.
    RateLimitExceededError — 429 con reintentos agotados.
    BinanceAPIError        — error tipificado de Binance (status_code + binance_code + msg).
"""

from chimuelo_prime.api_client.client import BinanceAuthenticatedClient
from chimuelo_prime.api_client.exceptions import (
    APIClientError,
    AuthenticationError,
    BinanceAPIError,
    RateLimitExceededError,
)
from chimuelo_prime.api_client.models import (
    APIClientConfig,
    BinanceCredentials,
    BinanceErrorResponse,
    RateLimitConfig,
    RetryConfig,
)
from chimuelo_prime.api_client.rate_limiter import RateLimiter, TokenBucket
from chimuelo_prime.api_client.signing import BinanceSigner

__all__ = [
    # Cliente
    "BinanceAuthenticatedClient",
    # Signing
    "BinanceSigner",
    # Rate limiting
    "RateLimiter",
    "TokenBucket",
    # Modelos de configuración
    "APIClientConfig",
    "RateLimitConfig",
    "RetryConfig",
    # Modelos de runtime
    "BinanceCredentials",
    "BinanceErrorResponse",
    # Excepciones
    "APIClientError",
    "AuthenticationError",
    "BinanceAPIError",
    "RateLimitExceededError",
]
