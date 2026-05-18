"""Excepciones tipificadas del módulo api_client (M2).

Jerarquía:
    ChimueloException (M1 — raíz del proyecto)
    └── APIClientError              # Raíz de errores de M2
        ├── AuthenticationError     # API Key/Secret inválidos o no definidos
        ├── RateLimitExceededError  # 429 + reintentos agotados
        └── BinanceAPIError         # Respuesta de error tipificada de Binance (4xx/5xx)

Regla: módulos downstream (M3, M4, M5) capturan estas excepciones por tipo
para tomar decisiones de negocio. Nunca `except Exception` genérico.
"""

from chimuelo_prime.exchange_config.exceptions import ChimueloException


class APIClientError(ChimueloException):
    """Raíz de errores del módulo api_client (M2)."""


class AuthenticationError(APIClientError):
    """API Key o Secret inválidos, vacíos o no definidos en variables de entorno."""


class RateLimitExceededError(APIClientError):
    """Rate limit de Binance (429) agotado tras todos los reintentos configurados."""


class BinanceAPIError(APIClientError):
    """Respuesta de error tipificada de Binance.

    Binance retorna errores en el formato:
        {"code": -1121, "msg": "Invalid symbol."}

    Este modelo los convierte en excepciones estructuradas con campos
    accesibles para que M3/M4/M5 puedan tomar decisiones de negocio:
        - status_code=-1010: orden rechazada por saldo insuficiente → alertar
        - binance_code=-1021: drift de reloj → sincronizar timestamp
        - binance_code=-2010: cancel-replace fallido → reintentar con nueva orden

    Args:
        status_code:   Código HTTP de la respuesta (400, 401, 403, etc.).
        binance_code:  Código de error interno de Binance (ej. -1121).
        msg:           Mensaje de error de Binance en texto plano.
    """

    def __init__(self, status_code: int, binance_code: int, msg: str) -> None:
        super().__init__(f"HTTP {status_code} | Binance code {binance_code}: {msg}")
        self.status_code = status_code
        self.binance_code = binance_code
        self.msg = msg
