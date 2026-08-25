"""Sistema de Monitoreo y Alertas para Chimuelo Prime (M7).

Responsabilidades:
    1. Proveer una fachada `AlertManager` para reportar incidentes críticos.
    2. Emitir logs estructurados de nivel `critical` con contexto completo.
    3. Soporte para callbacks extensibles (ej. webhooks para Slack, Email)
       sin añadir dependencias externas al núcleo del bot.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from chimuelo_prime.exchange_config.logger import get_logger


class AlertManager:
    """Fachada centralizada para la gestión y despacho de alertas.

    Permite registrar dinámicamente receptores de alertas (callbacks)
    y asegura que todo incidente crítico se guarde bajo logs estructurados JSON.
    """

    def __init__(self) -> None:
        self._log = get_logger(__name__)
        self._callbacks: list[Callable[[str, dict[str, Any]], None]] = []

        import os

        self._telegram_token = os.environ.get("CHIMUELO_TELEGRAM_TOKEN")
        self._telegram_chat_id = os.environ.get("CHIMUELO_TELEGRAM_CHAT_ID")

        if self._telegram_token and self._telegram_chat_id:
            self.register_callback(self._send_telegram_alert)
            self._log.info("alert.telegram_initialized", chat_id=self._telegram_chat_id)
        else:
            self._log.info(
                "alert.telegram_skipped",
                reason="Missing CHIMUELO_TELEGRAM_TOKEN or CHIMUELO_TELEGRAM_CHAT_ID",
            )

    def register_callback(self, callback: Callable[[str, dict[str, Any]], None]) -> None:
        """Registra un callback externo de notificación para ser invocado en cada alerta."""
        self._callbacks.append(callback)

    def trigger_alert(self, event: str, message: str, **context: Any) -> None:
        """Dispara una alerta crítica en el sistema.

        Escribe un log estructurado `critical` e invoca a cada callback registrado
        de manera segura (capturando y reportando fallos de red/despacho individuales).
        """
        self._log.critical(
            "alert.triggered",
            alert_event=event,
            message=message,
            **context,
        )

        for cb in self._callbacks:
            try:
                cb(event, {"message": message, **context})
            except Exception as exc:
                self._log.error(
                    "alert.callback_failed",
                    alert_event=event,
                    error=str(exc),
                )

    def _send_telegram_alert(self, event: str, context: dict[str, Any]) -> None:
        """Envía un mensaje de alerta a Telegram de forma sincrónica con un timeout seguro."""
        token = self._telegram_token
        chat_id = self._telegram_chat_id
        if not token or not chat_id:
            return

        import requests

        message = context.get("message", "")
        text = f"🚨 *[Chimuelo Prime Alert: {event}]*\n\n{message}"

        # Agregar variables de contexto adicionales si existen
        extra = {k: v for k, v in context.items() if k != "message"}
        if extra:
            text += "\n\n*Context:*\n"
            for k, v in extra.items():
                text += f"- `{k}`: {v}\n"

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }

        try:
            response = requests.post(url, json=payload, timeout=5.0)
            response.raise_for_status()
        except Exception as exc:
            self._log.error(
                "alert.telegram_send_failed",
                alert_event=event,
                error=str(exc),
            )
