"""Modelos de dominio del módulo api_client (M2).

Modelos de configuración:
    RateLimitConfig  — parámetros del token bucket (weight/orden por ventana).
    RetryConfig      — parámetros de backoff exponencial con jitter.
    APIClientConfig  — configuración completa del cliente autenticado.
                       Importada en config_loader.py para integrarla en ChimueloConfig.

Modelos de runtime:
    BinanceCredentials   — API Key + Secret leídos desde variables de entorno.
    BinanceErrorResponse — Parseo del body de error de Binance {"code": int, "msg": str}.

REGLA: BinanceCredentials NUNCA aparece en logs. __repr__ enmascara ambos campos.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field

from chimuelo_prime.api_client.exceptions import AuthenticationError


# --------------------------------------------------------------------------- #
# Configuración del rate limiter
# --------------------------------------------------------------------------- #
class RateLimitConfig(BaseModel):
    """Parámetros del token bucket para respetar los rate limits de Binance.

    Límites actuales de Binance Spot (2024):
        - Peso de requests: 1200 por minuto (rolling window).
        - Órdenes nuevas: 50 por 10 segundos (rolling window).

    Estos valores son los defaults. Si Binance los cambia, se actualizan
    en chimuelo.yaml sin modificar código.
    """

    model_config = ConfigDict(frozen=True)

    weight_limit: int = Field(default=1200, gt=0, description="Tokens de peso por ventana")
    weight_window_seconds: float = Field(
        default=60.0, gt=0, description="Duración de la ventana de peso en segundos"
    )
    order_limit: int = Field(default=50, gt=0, description="Órdenes permitidas por ventana")
    order_window_seconds: float = Field(
        default=10.0, gt=0, description="Duración de la ventana de órdenes en segundos"
    )


# --------------------------------------------------------------------------- #
# Configuración de reintentos
# --------------------------------------------------------------------------- #
class RetryConfig(BaseModel):
    """Parámetros de backoff exponencial con jitter para reintentos HTTP.

    Fórmula del delay:
        delay = min(base_delay * 2^attempt + uniform(0, jitter), max_delay)

    El jitter es crítico para evitar thundering herd cuando múltiples
    instancias del bot reintentan simultáneamente tras un 429.
    """

    model_config = ConfigDict(frozen=True)

    max_retries: int = Field(
        default=3, ge=0, le=10, description="Reintentos máximos (0 = sin reintento)"
    )
    base_delay_seconds: float = Field(default=1.0, gt=0, description="Delay base en segundos")
    max_delay_seconds: float = Field(default=60.0, gt=0, description="Delay máximo en segundos")
    jitter_seconds: float = Field(
        default=0.5, ge=0, description="Jitter máximo aleatorio en segundos"
    )


# --------------------------------------------------------------------------- #
# Configuración completa del cliente API
# --------------------------------------------------------------------------- #
class APIClientConfig(BaseModel):
    """Configuración completa del cliente autenticado de Binance.

    Se carga desde la sección `api_client:` de chimuelo.yaml.
    Todos los campos tienen defaults razonables — la sección es opcional en el YAML.
    """

    model_config = ConfigDict(frozen=True)

    recv_window_ms: int = Field(
        default=5000,
        gt=0,
        le=60000,
        description="Margen temporal para validación de firma (máximo 60000ms según Binance)",
    )
    rate_limit: RateLimitConfig = Field(
        default_factory=RateLimitConfig,
        description="Configuración del token bucket",
    )
    retry: RetryConfig = Field(
        default_factory=RetryConfig,
        description="Configuración de reintentos con backoff",
    )


# --------------------------------------------------------------------------- #
# Credenciales de autenticación
# --------------------------------------------------------------------------- #
class BinanceCredentials(BaseModel):
    """Credenciales de la API de Binance.

    REGLA DE SEGURIDAD:
        - Nunca provienen del YAML (secrets nunca en archivos de config).
        - Siempre desde variables de entorno: CHIMUELO_API_KEY, CHIMUELO_API_SECRET.
        - __repr__ enmascara ambos campos: nunca aparecen en logs ni tracebacks.

    Uso:
        credentials = BinanceCredentials.from_env()
    """

    model_config = ConfigDict(frozen=True)

    api_key: str = Field(..., min_length=1, repr=False)
    api_secret: str = Field(..., min_length=1, repr=False)

    def __repr__(self) -> str:
        suffix = self.api_key[-4:] if len(self.api_key) >= 4 else "***"
        return f"BinanceCredentials(api_key='...{suffix}', api_secret='***')"

    def __str__(self) -> str:
        return self.__repr__()

    @classmethod
    def from_env(cls) -> BinanceCredentials:
        """Lee las credenciales desde variables de entorno.

        Variables requeridas:
            CHIMUELO_API_KEY    — clave pública de la API de Binance.
            CHIMUELO_API_SECRET — clave secreta para firma HMAC-SHA256.

        Raises:
            AuthenticationError: si alguna variable no está definida o está vacía.
        """
        api_key = os.environ.get("CHIMUELO_API_KEY", "")
        api_secret = os.environ.get("CHIMUELO_API_SECRET", "")
        if not api_key:
            raise AuthenticationError(
                "Variable de entorno CHIMUELO_API_KEY no definida o vacía. "
                "Exporta la clave antes de iniciar el bot."
            )
        if not api_secret:
            raise AuthenticationError(
                "Variable de entorno CHIMUELO_API_SECRET no definida o vacía. "
                "Exporta el secret antes de iniciar el bot."
            )
        return cls(api_key=api_key, api_secret=api_secret)


# --------------------------------------------------------------------------- #
# Respuesta de error de Binance
# --------------------------------------------------------------------------- #
class BinanceErrorResponse(BaseModel):
    """Parsea el body JSON de error de Binance.

    Todos los errores de Binance tienen el formato:
        {"code": -1121, "msg": "Invalid symbol."}

    Se usa en BinanceAuthenticatedClient._raise_binance_error() para
    construir BinanceAPIError con campos tipificados.
    """

    code: int
    msg: str
