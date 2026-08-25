"""Configuración global de fixtures para pytest.

Aísla las pruebas unitarias para evitar envíos reales de peticiones HTTP
externas (como alertas de Telegram) durante la ejecución de la suite de tests.
"""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def mock_telegram_network_calls() -> Generator[MagicMock, None, None]:
    """Mockea requests.post por defecto en todos los tests para evitar tráfico real a Telegram."""
    with patch("requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"ok": True, "result": {}}
        mock_post.return_value = mock_response
        yield mock_post
