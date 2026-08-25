"""Tests unitarios para la lógica de Stop-Loss activo en GridEngine (Fase A)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from chimuelo_prime.exchange_config.models import SymbolConfig
from chimuelo_prime.grid_engine.engine import GridEngine
from chimuelo_prime.grid_state.grid_state import GridState
from chimuelo_prime.grid_state.reconciler import Reconciler
from chimuelo_prime.orchestrator.monitoring import AlertManager
from chimuelo_prime.order_execution.executor import OrderExecutor
from chimuelo_prime.order_execution.lifecycle import OrderLifecycleManager


@pytest.fixture
def mock_grid_state() -> MagicMock:
    gs = MagicMock(spec=GridState)
    gs.get_open_orders.return_value = []
    return gs


@pytest.fixture
def mock_executor() -> MagicMock:
    return MagicMock(spec=OrderExecutor)


@pytest.fixture
def mock_lifecycle() -> MagicMock:
    return MagicMock(spec=OrderLifecycleManager)


@pytest.fixture
def mock_reconciler() -> MagicMock:
    return MagicMock(spec=Reconciler)


@pytest.fixture
def mock_price_fetcher() -> MagicMock:
    from chimuelo_prime.grid_engine.price_fetcher import PriceFetcher

    pf = MagicMock(spec=PriceFetcher)
    pf.get_current_price.return_value = Decimal("120.00")
    return pf


@pytest.fixture
def mock_alert_manager() -> MagicMock:
    return MagicMock(spec=AlertManager)


@pytest.fixture
def engine(
    symbol_config: SymbolConfig,
    mock_grid_state: MagicMock,
    mock_executor: MagicMock,
    mock_lifecycle: MagicMock,
    mock_reconciler: MagicMock,
    mock_price_fetcher: MagicMock,
    mock_alert_manager: MagicMock,
) -> GridEngine:
    return GridEngine(
        config=symbol_config,
        grid_state=mock_grid_state,
        executor=mock_executor,
        lifecycle=mock_lifecycle,
        reconciler=mock_reconciler,
        price_fetcher=mock_price_fetcher,
        alert_manager=mock_alert_manager,
        poll_interval=0.0,
    )


def test_stop_loss_not_triggered(
    engine: GridEngine,
    mock_price_fetcher: MagicMock,
    mock_alert_manager: MagicMock,
    mock_grid_state: MagicMock,
    mock_lifecycle: MagicMock,
) -> None:
    # Límite inferior configurado en conftest.py es 100.00
    # Precio actual es 120.00 (mayor que 100.00)
    mock_price_fetcher.get_current_price.return_value = Decimal("120.00")

    mock_order = MagicMock()
    mock_order.order_id = 456
    mock_order.side = "BUY"
    mock_grid_state.get_open_orders.return_value = [mock_order]

    engine._run_poll_cycle()

    # AlertManager no debe disparar alerta de stop-loss
    mock_alert_manager.trigger_alert.assert_not_called()

    # El motor debe continuar e intentar sincronizar las órdenes abiertas
    mock_lifecycle.sync_order_status.assert_called_once_with(456, "SOLUSDT")
    assert not engine._stop_event.is_set()


def test_stop_loss_triggered_success(
    engine: GridEngine,
    mock_price_fetcher: MagicMock,
    mock_alert_manager: MagicMock,
    mock_executor: MagicMock,
    mock_grid_state: MagicMock,
    mock_lifecycle: MagicMock,
) -> None:
    # Precio actual 95.00 (menor que lower_bound 100.00)
    mock_price_fetcher.get_current_price.return_value = Decimal("95.00")

    mock_order = MagicMock()
    mock_order.order_id = 789
    mock_order.side = "BUY"
    mock_grid_state.get_open_orders.return_value = [mock_order]

    engine._run_poll_cycle()

    # 1. AlertManager debe disparar alerta GRID_STOP_LOSS
    mock_alert_manager.trigger_alert.assert_called_once()
    args, kwargs = mock_alert_manager.trigger_alert.call_args
    assert args[0] == "GRID_STOP_LOSS"
    assert "Stop-Loss triggered" in args[1]
    assert kwargs["symbol"] == "SOLUSDT"
    assert kwargs["current_price"] == "95.00"
    assert kwargs["lower_bound"] == "100.00"

    # 2. Debe cancelar todas las órdenes abiertas de inmediato
    mock_executor.cancel_all_open_orders.assert_called_once_with("SOLUSDT")

    # 3. Debe detener el ciclo de polling (engine.stop)
    assert engine._stop_event.is_set()

    # 4. Retorno temprano: no sincroniza órdenes restantes
    mock_lifecycle.sync_order_status.assert_not_called()


def test_stop_loss_triggered_cancel_fails(
    engine: GridEngine,
    mock_price_fetcher: MagicMock,
    mock_alert_manager: MagicMock,
    mock_executor: MagicMock,
    mock_lifecycle: MagicMock,
) -> None:
    # Precio actual cae a 90.00
    mock_price_fetcher.get_current_price.return_value = Decimal("90.00")

    # Simular fallo en la cancelación
    mock_executor.cancel_all_open_orders.side_effect = RuntimeError("Binance API error")

    # La ejecución no debe propagar la excepción al orquestador, sino procesar de forma segura
    engine._run_poll_cycle()

    # El trigger de alerta y la detención se realizan de todos modos
    mock_alert_manager.trigger_alert.assert_called_once()
    mock_executor.cancel_all_open_orders.assert_called_once()
    assert engine._stop_event.is_set()
    mock_lifecycle.sync_order_status.assert_not_called()


def test_stop_loss_check_resilience_to_price_fetch_error(
    engine: GridEngine,
    mock_price_fetcher: MagicMock,
    mock_alert_manager: MagicMock,
    mock_executor: MagicMock,
    mock_grid_state: MagicMock,
    mock_lifecycle: MagicMock,
) -> None:
    # Error al obtener precio no debe detener el bot
    mock_price_fetcher.get_current_price.side_effect = RuntimeError("Network timeout")

    mock_order = MagicMock()
    mock_order.order_id = 999
    mock_order.side = "BUY"
    mock_grid_state.get_open_orders.return_value = [mock_order]

    engine._run_poll_cycle()

    # No se detiene el bot ni se cancela nada
    assert not engine._stop_event.is_set()
    mock_alert_manager.trigger_alert.assert_not_called()
    mock_executor.cancel_all_open_orders.assert_not_called()

    # El flujo continúa normalmente
    mock_lifecycle.sync_order_status.assert_called_once_with(999, "SOLUSDT")
