"""Tests unitarios para monitoring.py (M7)."""

from __future__ import annotations

from unittest.mock import MagicMock

from chimuelo_prime.orchestrator.monitoring import AlertManager


def test_alert_manager_success() -> None:
    manager = AlertManager()
    callback1 = MagicMock()
    callback2 = MagicMock()

    manager.register_callback(callback1)
    manager.register_callback(callback2)

    manager.trigger_alert("TEST_EVENT", "Something happened", symbol="SOLUSDT")

    callback1.assert_called_once_with(
        "TEST_EVENT", {"message": "Something happened", "symbol": "SOLUSDT"}
    )
    callback2.assert_called_once_with(
        "TEST_EVENT", {"message": "Something happened", "symbol": "SOLUSDT"}
    )


def test_alert_manager_callback_failure() -> None:
    manager = AlertManager()

    # Callback that raises an error
    failing_callback = MagicMock(side_effect=ValueError("Network timeout"))
    working_callback = MagicMock()

    manager.register_callback(failing_callback)
    manager.register_callback(working_callback)

    # Deberia procesar de forma segura y ejecutar el segundo callback
    manager.trigger_alert("CRITICAL_ERR", "Disaster strikes")

    failing_callback.assert_called_once_with("CRITICAL_ERR", {"message": "Disaster strikes"})
    working_callback.assert_called_once_with("CRITICAL_ERR", {"message": "Disaster strikes"})
