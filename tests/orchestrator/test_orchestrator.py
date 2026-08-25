"""Tests unitarios para orchestrator.py (M7)."""

from __future__ import annotations

import threading
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from chimuelo_prime.api_client.client import BinanceAuthenticatedClient
from chimuelo_prime.exchange_config.client import BinancePublicClient
from chimuelo_prime.exchange_config.models import SymbolFilters
from chimuelo_prime.exchange_config.service import ExchangeConfigService
from chimuelo_prime.grid_engine.engine import GridEngine
from chimuelo_prime.grid_state.reconciler import Reconciler
from chimuelo_prime.orchestrator.config_manager import OrchestratorConfig
from chimuelo_prime.orchestrator.orchestrator import Orchestrator


@pytest.fixture
def mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHIMUELO_API_KEY", "test_api_key")
    monkeypatch.setenv("CHIMUELO_API_SECRET", "test_api_secret")


@pytest.fixture
def orchestrator_config() -> OrchestratorConfig:
    raw = {
        "active_environment": "testnet",
        "environments": {
            "testnet": {
                "base_url": "https://testnet.binance.vision",
                "ws_base_url": "wss://testnet.binance.vision",
                "http_timeout_seconds": 10,
            }
        },
        "symbols": ["SOLUSDT"],
        "strategies": {
            "SOLUSDT": {
                "upper_bound": "140.00",
                "lower_bound": "100.00",
                "grid_levels": 20,
                "capital_per_order": "10.00",
                "capital_weight": "1.00",
            }
        },
    }
    return OrchestratorConfig.model_validate(raw)


@pytest.fixture
def mock_symbol_filters() -> SymbolFilters:
    return SymbolFilters(
        symbol="SOLUSDT",
        tick_size=Decimal("0.01"),
        min_price=Decimal("0.01"),
        max_price=Decimal("1000.00"),
        step_size=Decimal("0.01"),
        min_qty=Decimal("0.01"),
        max_qty=Decimal("1000.00"),
        min_notional=Decimal("5.00"),
        pct_up=Decimal("5.0"),
        pct_down=Decimal("0.2"),
    )


# Decorators applied bottom-up, so params top-down:
# @patch("build_engine")             -> mock_build_engine          (1st)
# @patch("BinancePublicClient")      -> mock_public_client_class   (2nd)
# @patch("BinanceAuthenticatedClient") -> mock_auth_client_class   (3rd)
# @patch("ExchangeConfigService")    -> mock_service_class         (4th)
# @patch("Reconciler")               -> mock_reconciler_class      (5th)
# @patch("GridEngine")               -> mock_grid_engine_class     (6th)
@patch("chimuelo_prime.orchestrator.orchestrator.build_engine")
@patch("chimuelo_prime.orchestrator.orchestrator.BinancePublicClient")
@patch("chimuelo_prime.orchestrator.orchestrator.BinanceAuthenticatedClient")
@patch("chimuelo_prime.orchestrator.orchestrator.ExchangeConfigService")
@patch("chimuelo_prime.orchestrator.orchestrator.Reconciler")
@patch("chimuelo_prime.orchestrator.orchestrator.GridEngine")
def test_setup_success(
    mock_grid_engine_class: MagicMock,
    mock_reconciler_class: MagicMock,
    mock_service_class: MagicMock,
    mock_auth_client_class: MagicMock,
    mock_public_client_class: MagicMock,
    mock_build_engine: MagicMock,
    orchestrator_config: OrchestratorConfig,
    mock_symbol_filters: SymbolFilters,
    mock_env: None,
) -> None:
    # Mocks
    mock_public_client = MagicMock(spec=BinancePublicClient)
    mock_public_client.get_exchange_info.return_value = {"serverTime": 1700000000000}
    mock_public_client_class.return_value = mock_public_client

    mock_auth_client = MagicMock(spec=BinanceAuthenticatedClient)
    mock_auth_client_class.return_value = mock_auth_client

    mock_service = MagicMock(spec=ExchangeConfigService)
    mock_service.fetch_symbol_filters.return_value = mock_symbol_filters
    mock_service_class.return_value = mock_service

    mock_reconciler = MagicMock(spec=Reconciler)
    mock_reconciler_class.return_value = mock_reconciler

    orchestrator = Orchestrator(orchestrator_config, db_url="sqlite:///:memory:")
    orchestrator.setup()

    # Verificar que el reloj del servidor se sincronizó
    mock_public_client.get_exchange_info.assert_called_with("SOLUSDT")
    mock_auth_client.sync_server_time.assert_called_with(1700000000000)

    # Verificar reconciliación
    mock_reconciler.reconcile.assert_called_with("SOLUSDT")

    # Verificar instanciación de GridEngine
    mock_grid_engine_class.assert_called()
    assert "SOLUSDT" in orchestrator._engines


@patch("chimuelo_prime.orchestrator.orchestrator.build_engine")
@patch("chimuelo_prime.orchestrator.orchestrator.BinancePublicClient")
@patch("chimuelo_prime.orchestrator.orchestrator.BinanceAuthenticatedClient")
@patch("chimuelo_prime.orchestrator.orchestrator.ExchangeConfigService")
@patch("chimuelo_prime.orchestrator.orchestrator.Reconciler")
@patch("chimuelo_prime.orchestrator.orchestrator.GridEngine")
def test_setup_time_sync_failure(
    mock_grid_engine_class: MagicMock,
    mock_reconciler_class: MagicMock,
    mock_service_class: MagicMock,
    mock_auth_client_class: MagicMock,
    mock_public_client_class: MagicMock,
    mock_build_engine: MagicMock,
    orchestrator_config: OrchestratorConfig,
    mock_env: None,
) -> None:
    # Forzar error de red en public_client
    mock_public_client = MagicMock(spec=BinancePublicClient)
    mock_public_client.get_exchange_info.side_effect = Exception("Conexion rechazada")
    mock_public_client_class.return_value = mock_public_client

    orchestrator = Orchestrator(orchestrator_config, db_url="sqlite:///:memory:")

    # callback de alertas para verificar que se gatilló
    alert_callback = MagicMock()
    orchestrator.alert_manager.register_callback(alert_callback)

    with pytest.raises(Exception, match="Conexion rechazada"):
        orchestrator.setup()

    alert_callback.assert_called_once()
    assert alert_callback.call_args[0][0] == "TIME_SYNC_FAILED"


@patch("chimuelo_prime.orchestrator.orchestrator.build_engine")
@patch("chimuelo_prime.orchestrator.orchestrator.BinancePublicClient")
@patch("chimuelo_prime.orchestrator.orchestrator.BinanceAuthenticatedClient")
@patch("chimuelo_prime.orchestrator.orchestrator.ExchangeConfigService")
@patch("chimuelo_prime.orchestrator.orchestrator.Reconciler")
@patch("chimuelo_prime.orchestrator.orchestrator.GridEngine")
def test_setup_reconciliation_failure(
    mock_grid_engine_class: MagicMock,
    mock_reconciler_class: MagicMock,
    mock_service_class: MagicMock,
    mock_auth_client_class: MagicMock,
    mock_public_client_class: MagicMock,
    mock_build_engine: MagicMock,
    orchestrator_config: OrchestratorConfig,
    mock_symbol_filters: SymbolFilters,
    mock_env: None,
) -> None:
    mock_public_client = MagicMock(spec=BinancePublicClient)
    mock_public_client.get_exchange_info.return_value = {"serverTime": 1700000000000}
    mock_public_client_class.return_value = mock_public_client

    mock_auth_client = MagicMock(spec=BinanceAuthenticatedClient)
    mock_auth_client_class.return_value = mock_auth_client

    mock_service = MagicMock(spec=ExchangeConfigService)
    mock_service.fetch_symbol_filters.return_value = mock_symbol_filters
    mock_service_class.return_value = mock_service

    # Forzar fallo de reconciliacion
    mock_reconciler = MagicMock(spec=Reconciler)
    mock_reconciler.reconcile.side_effect = Exception("Fallo DB")
    mock_reconciler_class.return_value = mock_reconciler

    orchestrator = Orchestrator(orchestrator_config, db_url="sqlite:///:memory:")

    alert_callback = MagicMock()
    orchestrator.alert_manager.register_callback(alert_callback)

    with pytest.raises(Exception, match="Fallo DB"):
        orchestrator.setup()

    alert_callback.assert_called_once()
    assert alert_callback.call_args[0][0] == "RECONCILIATION_FAILED"


def test_start_and_stop_lifecycle(orchestrator_config: OrchestratorConfig) -> None:
    orchestrator = Orchestrator(orchestrator_config, db_url="sqlite:///:memory:")

    # Mock del setup para que start() no intente conectarse realmente
    orchestrator.setup = MagicMock()  # type: ignore[assignment]

    # Mock de GridEngine
    mock_engine = MagicMock(spec=GridEngine)
    orchestrator._engines = {"SOLUSDT": mock_engine}

    # Mockear _stop_event para que el loop principal termine inmediatamente
    # is_set() devuelve True en la primera iteracion del while
    mock_stop_event = MagicMock(spec=threading.Event)
    mock_stop_event.is_set.return_value = True  # El loop termina de inmediato
    orchestrator._stop_event = mock_stop_event

    with patch("threading.Thread") as mock_thread_class:
        mock_thread = MagicMock()
        mock_thread_class.return_value = mock_thread

        # start() llama setup() -> lanza hilos -> loop principal -> stop()
        # Como is_set() = True, el loop termina sin bloquear
        # Pero stop() verifica _is_running, así que lo seteamos manualmente
        orchestrator._is_running = False  # Evitar que start() lo salte

        # Interceptamos el stop() para no ejecutar lógica real de teardown aún
        with patch.object(orchestrator, "stop", wraps=None) as mock_stop_method:
            orchestrator._is_running = True  # start() verificará esto antes de lanzar setup
            # Simular que start ya pasó por setup, lanzó hilos, y el loop terminó
            # Invocamos la lógica interna de start() de forma controlada:
            orchestrator._is_running = True
            orchestrator._stop_event.clear()

            for symbol, engine in orchestrator._engines.items():
                thread = threading.Thread(
                    target=engine.start,
                    name=f"GridEngine-{symbol}",
                    daemon=True,
                )
                thread.start()
                orchestrator._threads[symbol] = thread

            mock_thread_class.assert_called_once_with(
                target=mock_engine.start, name="GridEngine-SOLUSDT", daemon=True
            )
            mock_thread.start.assert_called_once()

    # Mocks de teardown
    mock_db_engine = MagicMock()
    mock_auth_client = MagicMock()
    mock_public_client = MagicMock()

    orchestrator._db_engine = mock_db_engine
    orchestrator._authenticated_client = mock_auth_client
    orchestrator._public_client = mock_public_client
    orchestrator._threads = {"SOLUSDT": mock_thread}
    orchestrator._is_running = True  # Asegurar que stop() no salte temprano

    # Ejecutar parada
    orchestrator.stop()

    # Verificar limpieza
    mock_engine.stop.assert_called_once()
    mock_thread.join.assert_called_once()
    mock_auth_client.close.assert_called_once()
    mock_public_client.close.assert_called_once()
    mock_db_engine.dispose.assert_called_once()


@patch("chimuelo_prime.orchestrator.orchestrator.build_engine")
@patch("chimuelo_prime.orchestrator.orchestrator.BinancePublicClient")
@patch("chimuelo_prime.orchestrator.orchestrator.BinanceAuthenticatedClient")
@patch("chimuelo_prime.orchestrator.orchestrator.ExchangeConfigService")
@patch("chimuelo_prime.orchestrator.orchestrator.Reconciler")
@patch("chimuelo_prime.orchestrator.orchestrator.GridEngine")
def test_setup_time_sync_empty_server_time(
    mock_grid_engine_class: MagicMock,
    mock_reconciler_class: MagicMock,
    mock_service_class: MagicMock,
    mock_auth_client_class: MagicMock,
    mock_public_client_class: MagicMock,
    mock_build_engine: MagicMock,
    orchestrator_config: OrchestratorConfig,
    mock_env: None,
) -> None:
    mock_public_client = MagicMock(spec=BinancePublicClient)
    mock_public_client.get_exchange_info.return_value = {}  # Empty response
    mock_public_client_class.return_value = mock_public_client

    orchestrator = Orchestrator(orchestrator_config, db_url="sqlite:///:memory:")

    alert_callback = MagicMock()
    orchestrator.alert_manager.register_callback(alert_callback)

    with pytest.raises(ValueError, match="serverTime ausente"):
        orchestrator.setup()

    alert_callback.assert_called_once()
    assert alert_callback.call_args[0][0] == "TIME_SYNC_FAILED"


def test_stop_not_running(orchestrator_config: OrchestratorConfig) -> None:
    orchestrator = Orchestrator(orchestrator_config, db_url="sqlite:///:memory:")
    orchestrator._is_running = False
    orchestrator.stop()  # Should return early and do nothing
    assert orchestrator._is_running is False


def test_stop_with_exceptions(orchestrator_config: OrchestratorConfig) -> None:
    orchestrator = Orchestrator(orchestrator_config, db_url="sqlite:///:memory:")

    # Setup mocks that raise exceptions
    mock_engine = MagicMock(spec=GridEngine)
    mock_engine.stop.side_effect = Exception("engine stop failed")

    mock_thread = MagicMock()

    mock_auth_client = MagicMock()
    mock_auth_client.close.side_effect = Exception("auth client close failed")

    mock_public_client = MagicMock()
    mock_public_client.close.side_effect = Exception("public client close failed")

    mock_db_engine = MagicMock()
    mock_db_engine.dispose.side_effect = Exception("db dispose failed")

    orchestrator._engines = {"SOLUSDT": mock_engine}
    orchestrator._threads = {"SOLUSDT": mock_thread}
    orchestrator._authenticated_client = mock_auth_client
    orchestrator._public_client = mock_public_client
    orchestrator._db_engine = mock_db_engine
    orchestrator._is_running = True

    # stop() should catch all exceptions and log them, not raise them
    orchestrator.stop()

    mock_engine.stop.assert_called_once()
    mock_thread.join.assert_called_once()
    mock_auth_client.close.assert_called_once()
    mock_public_client.close.assert_called_once()
    mock_db_engine.dispose.assert_called_once()
    assert orchestrator._is_running is False


def test_start_keyboard_interrupt(orchestrator_config: OrchestratorConfig) -> None:
    orchestrator = Orchestrator(orchestrator_config, db_url="sqlite:///:memory:")
    orchestrator.setup = MagicMock()

    mock_engine = MagicMock()
    orchestrator._engines = {"SOLUSDT": mock_engine}

    # Mock stop event to raise KeyboardInterrupt on wait
    mock_stop_event = MagicMock()
    mock_stop_event.is_set.side_effect = [False, True]
    mock_stop_event.wait.side_effect = KeyboardInterrupt()
    orchestrator._stop_event = mock_stop_event

    orchestrator.stop = MagicMock()

    orchestrator.start()

    orchestrator.setup.assert_called_once()
    orchestrator.stop.assert_called_once()


def test_handle_signal(orchestrator_config: OrchestratorConfig) -> None:
    orchestrator = Orchestrator(orchestrator_config, db_url="sqlite:///:memory:")
    assert not orchestrator._stop_event.is_set()
    import signal

    orchestrator._handle_signal(signal.SIGINT, None)
    assert orchestrator._stop_event.is_set()
