"""Tests unitarios para la integración de alertas de Telegram en monitoring.py (Fase A)."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import requests

from chimuelo_prime.orchestrator.monitoring import AlertManager


def test_telegram_alerts_enabled_success() -> None:
    env_mock = {
        "CHIMUELO_TELEGRAM_TOKEN": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        "CHIMUELO_TELEGRAM_CHAT_ID": "987654321",
    }
    with patch.dict(os.environ, env_mock), patch("requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        manager = AlertManager()
        # Verificar que se registró la función _send_telegram_alert
        assert len(manager._callbacks) == 1

        manager.trigger_alert("TEST_EVENT", "This is a test alert", extra_param="value123")

        # Verificar que requests.post se llamó con los argumentos esperados
        expected_url = (
            "https://api.telegram.org/bot123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11/sendMessage"
        )
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == expected_url
        assert kwargs["timeout"] == 5.0

        payload = kwargs["json"]
        assert payload["chat_id"] == "987654321"
        assert "TEST_EVENT" in payload["text"]
        assert "This is a test alert" in payload["text"]
        assert "extra_param" in payload["text"]
        assert "value123" in payload["text"]


def test_telegram_alerts_disabled_by_missing_env() -> None:
    # Asegurar que las variables de entorno estén vacías
    with patch.dict(os.environ, {}, clear=True), patch("requests.post") as mock_post:
        manager = AlertManager()
        # No debería registrar ningún callback de Telegram
        assert len(manager._callbacks) == 0

        manager.trigger_alert("TEST_EVENT", "No Telegram here")
        mock_post.assert_not_called()


def test_telegram_alerts_handle_exceptions_gracefully() -> None:
    env_mock = {
        "CHIMUELO_TELEGRAM_TOKEN": "some_token",
        "CHIMUELO_TELEGRAM_CHAT_ID": "some_chat_id",
    }
    with (
        patch.dict(os.environ, env_mock),
        patch(
            "requests.post", side_effect=requests.exceptions.RequestException("Timeout!")
        ) as mock_post,
    ):
        manager = AlertManager()

        # Debe capturar el error y no levantar excepción en el trigger_alert
        manager.trigger_alert("FAIL_EVENT", "Connection drop")
        mock_post.assert_called_once()
