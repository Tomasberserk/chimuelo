"""Firma HMAC-SHA256 para endpoints autenticados de Binance.

Responsabilidades (SRP):
    - Añadir timestamp y recvWindow al dict de params.
    - Calcular HMAC-SHA256 sobre el query string resultante.
    - Retornar una COPIA del dict con timestamp, recvWindow y signature.

Aislado del cliente HTTP para facilitar tests unitarios puros (sin red).

REGLA: el api_secret NUNCA se loguea. El __repr__ del signer no lo expone.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any
from urllib.parse import urlencode

from chimuelo_prime.api_client.models import BinanceCredentials


class BinanceSigner:
    """Firma requests para la API autenticada de Binance.

    Algoritmo (por llamada a sign_params):
        1. Copiar params (nunca mutar el original).
        2. Añadir timestamp = int(time.time() * 1000) + server_time_offset_ms.
        3. Añadir recvWindow.
        4. Construir query string con urllib.parse.urlencode (orden de inserción).
        5. Firma = HMAC-SHA256(api_secret, query_string.encode()).hexdigest().
        6. Añadir 'signature' al dict copiado.
        7. Retornar el dict copiado con firma.

    El api_key se expone vía propiedad (es semipúblico, necesario en headers).
    El api_secret nunca se expone.

    Args:
        credentials:   BinanceCredentials con api_key y api_secret.
        recv_window:   Margen temporal en ms (default 5000, máximo 60000).
    """

    def __init__(self, credentials: BinanceCredentials, recv_window: int = 5000) -> None:
        self._api_key = credentials.api_key
        self._secret = credentials.api_secret
        self._recv_window = recv_window
        self._server_time_offset_ms: int = 0

    def sign_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Firma un dict de parámetros retornando una copia firmada.

        No muta el dict original — el llamador puede reutilizarlo.

        Args:
            params: parámetros del endpoint (sin timestamp ni signature).

        Returns:
            Nuevo dict con los params originales + timestamp + recvWindow + signature.
        """
        signed: dict[str, Any] = dict(params)
        signed["timestamp"] = int(time.time() * 1000) + self._server_time_offset_ms
        signed["recvWindow"] = self._recv_window
        query_string = urlencode(signed)
        signature = hmac.new(
            self._secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        signed["signature"] = signature
        return signed

    def set_server_time_offset(self, offset_ms: int) -> None:
        """Actualiza el offset entre reloj local y servidor de Binance.

        El orquestador (M7) llama a GET /api/v3/time via BinancePublicClient,
        calcula `offset = server_time_ms - local_time_ms` y lo inyecta aquí.
        Previene el error -1021 (Timestamp out of recvWindow) en entornos con
        drift de NTP.

        Args:
            offset_ms: diferencia en ms (positivo = servidor adelantado).
        """
        self._server_time_offset_ms = offset_ms

    @property
    def api_key(self) -> str:
        """API Key semipública — se incluye en el header X-MBX-APIKEY."""
        return self._api_key

    def __repr__(self) -> str:
        suffix = self._api_key[-4:] if len(self._api_key) >= 4 else "***"
        return f"BinanceSigner(api_key='...{suffix}', recv_window={self._recv_window})"
