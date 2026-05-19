"""Token bucket rate limiter para los límites de la API de Binance.

Arquitectura:
    TokenBucket  — implementa el algoritmo de token bucket thread-safe.
    RateLimiter  — compone dos TokenBucket: uno de peso y uno de órdenes.

Límites de Binance Spot (actuales):
    - Weight bucket:  1200 tokens / 60 segundos  (requests de lectura/escritura)
    - Order bucket:   50 tokens  / 10 segundos   (solo órdenes nuevas)

REGLA CRÍTICA: el RateLimiter debe ser una instancia compartida entre todos
los clientes que usan la misma cuenta de Binance. Si cada cliente tiene su
propio RateLimiter, la suma puede exceder el límite y provocar baneos de IP.
El orquestador (M7) es responsable de crear UNA instancia y pasarla a todos.

El rate limiter ESPERA, no falla. Solo RateLimitExceededError viene del
cliente cuando los reintentos del HTTP 429 se agotan — no del limiter.
"""

from __future__ import annotations

import threading
import time

from chimuelo_prime.api_client.models import RateLimitConfig
from chimuelo_prime.exchange_config.logger import get_logger


class TokenBucket:
    """Token bucket thread-safe con recarga periódica completa.

    Algoritmo:
        1. Al consumir, calcular si ha pasado `refill_interval` desde la
           última recarga. Si sí, restaurar tokens al máximo.
        2. Si hay tokens suficientes: consumir y retornar 0.0 (sin espera).
        3. Si no: retornar los segundos hasta la próxima recarga.

    El llamador (RateLimiter) hace `time.sleep(wait)` si wait > 0.

    Thread-safety: `threading.Lock` protege el estado interno. Correcto
    para M7 donde múltiples GridEngines comparten el mismo RateLimiter.

    Args:
        max_tokens:       Capacidad máxima del bucket.
        refill_interval:  Segundos entre recargas completas.
    """

    def __init__(self, max_tokens: int, refill_interval: float) -> None:
        self._max_tokens = max_tokens
        self._tokens = max_tokens
        self._refill_interval = refill_interval
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def consume(self, amount: int) -> float:
        """Intenta consumir `amount` tokens.

        Returns:
            0.0 si había tokens suficientes (sin espera).
            Segundos hasta la próxima recarga si no había suficientes.
        """
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            if elapsed >= self._refill_interval:
                self._tokens = self._max_tokens
                self._last_refill = now
            if self._tokens >= amount:
                self._tokens -= amount
                return 0.0
            return max(0.0, self._refill_interval - elapsed)

    @property
    def available_tokens(self) -> int:
        """Tokens disponibles en este momento (snapshot, puede cambiar)."""
        with self._lock:
            return self._tokens


class RateLimiter:
    """Compone dos TokenBucket para respetar los límites de Binance.

    Uso:
        rate_limiter = RateLimiter(config.api_client.rate_limit)
        # En el cliente HTTP:
        rate_limiter.consume_weight(weight=1)    # para requests de lectura
        rate_limiter.consume_order(weight=1)     # para órdenes nuevas

    Args:
        config: RateLimitConfig con los parámetros de ventana y límite.
    """

    def __init__(self, config: RateLimitConfig) -> None:
        self._weight_bucket = TokenBucket(
            max_tokens=config.weight_limit,
            refill_interval=config.weight_window_seconds,
        )
        self._order_bucket = TokenBucket(
            max_tokens=config.order_limit,
            refill_interval=config.order_window_seconds,
        )
        self._log = get_logger(__name__)

    def consume_weight(self, weight: int) -> None:
        """Consume `weight` tokens del bucket de peso. Bloquea si necesario."""
        wait = self._weight_bucket.consume(weight)
        if wait > 0.0:
            self._log.warning(
                "rate_limiter.weight_throttle",
                weight=weight,
                wait_seconds=round(wait, 3),
            )
            time.sleep(wait)

    def consume_order(self, weight: int) -> None:
        """Consume del bucket de peso Y del bucket de órdenes. Bloquea si necesario.

        Las órdenes nuevas consumen de ambos buckets: afectan tanto el límite
        de peso general como el límite específico de órdenes por ventana corta.
        """
        self.consume_weight(weight)
        wait = self._order_bucket.consume(1)
        if wait > 0.0:
            self._log.warning(
                "rate_limiter.order_throttle",
                wait_seconds=round(wait, 3),
            )
            time.sleep(wait)
