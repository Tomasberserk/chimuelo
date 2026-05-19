"""Tests para OrderLifecycleManager — sincronización de estado de órdenes.

Cubre:
    - sync_order_status sin cambio: status_changed=False, M3 no escrito.
    - sync_order_status con cambio: M3 actualizado, status_changed=True.
    - sync_order_status Binance falla: StatusSyncError.
    - sync_order_status orden no en M3: OrderNotFoundError.
    - sync_all_open_orders: dos órdenes, una cambia estado, la otra no.
    - handle_fill_event: M3 marcado FILLED, OrderStatusUpdate correcto.
    - handle_fill_event orden no en M3: OrderNotFoundError.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from chimuelo_prime.api_client.exceptions import BinanceAPIError
from chimuelo_prime.grid_state.exceptions import OrderNotFoundError
from chimuelo_prime.grid_state.schema import OrderStatus
from chimuelo_prime.order_execution.exceptions import StatusSyncError
from chimuelo_prime.order_execution.models import OrderStatusUpdate
from tests.order_execution.conftest import make_binance_order_response, make_order_orm


def _binance_get_response(status: str = "NEW", executed: str = "0.00") -> dict:
    return {
        "symbol": "SOLUSDT",
        "orderId": 12345,
        "clientOrderId": "cid",
        "price": "150.00",
        "origQty": "0.10",
        "executedQty": executed,
        "status": status,
        "timeInForce": "GTC",
        "type": "LIMIT",
        "side": "BUY",
        "time": 1700000000000,
        "updateTime": 1700000000000,
    }


class TestSyncOrderStatus:
    def test_no_change_returns_status_changed_false(
        self, lifecycle_manager, mock_client, mock_grid_state
    ) -> None:
        mock_grid_state.get_order.return_value = make_order_orm(status="NEW")
        mock_client.get.return_value = _binance_get_response(status="NEW")
        result = lifecycle_manager.sync_order_status(12345, "SOLUSDT")
        assert result.status_changed is False
        assert result.previous_status == OrderStatus.NEW
        assert result.current_status == OrderStatus.NEW

    def test_no_change_m3_not_written(
        self, lifecycle_manager, mock_client, mock_grid_state
    ) -> None:
        mock_grid_state.get_order.return_value = make_order_orm(status="NEW")
        mock_client.get.return_value = _binance_get_response(status="NEW")
        lifecycle_manager.sync_order_status(12345, "SOLUSDT")
        mock_grid_state.update_order_status.assert_not_called()

    def test_status_changed_updates_m3(
        self, lifecycle_manager, mock_client, mock_grid_state
    ) -> None:
        mock_grid_state.get_order.return_value = make_order_orm(status="NEW")
        mock_client.get.return_value = _binance_get_response(status="FILLED", executed="0.10")
        result = lifecycle_manager.sync_order_status(12345, "SOLUSDT")
        assert result.status_changed is True
        assert result.current_status == OrderStatus.FILLED
        mock_grid_state.update_order_status.assert_called_once_with(
            12345, OrderStatus.FILLED.value
        )

    def test_executed_qty_from_binance(
        self, lifecycle_manager, mock_client, mock_grid_state
    ) -> None:
        mock_grid_state.get_order.return_value = make_order_orm(status="PARTIALLY_FILLED")
        mock_client.get.return_value = _binance_get_response(
            status="PARTIALLY_FILLED", executed="0.05"
        )
        result = lifecycle_manager.sync_order_status(12345, "SOLUSDT")
        assert result.executed_qty == Decimal("0.05")

    def test_binance_error_raises_status_sync_error(
        self, lifecycle_manager, mock_client, mock_grid_state
    ) -> None:
        mock_grid_state.get_order.return_value = make_order_orm(status="NEW")
        mock_client.get.side_effect = BinanceAPIError(500, -1000, "Internal")
        with pytest.raises(StatusSyncError):
            lifecycle_manager.sync_order_status(12345, "SOLUSDT")

    def test_order_not_in_m3_raises(
        self, lifecycle_manager, mock_grid_state
    ) -> None:
        mock_grid_state.get_order.return_value = None
        with pytest.raises(OrderNotFoundError):
            lifecycle_manager.sync_order_status(99999, "SOLUSDT")

    def test_returns_order_status_update(
        self, lifecycle_manager, mock_client, mock_grid_state
    ) -> None:
        mock_grid_state.get_order.return_value = make_order_orm(status="NEW")
        mock_client.get.return_value = _binance_get_response(status="FILLED")
        result = lifecycle_manager.sync_order_status(12345, "SOLUSDT")
        assert isinstance(result, OrderStatusUpdate)
        assert result.order_id == 12345
        assert result.symbol == "SOLUSDT"


class TestSyncAllOpenOrders:
    def test_syncs_all_open_orders(
        self, lifecycle_manager, mock_client, mock_grid_state
    ) -> None:
        mock_grid_state.get_open_orders.return_value = [
            make_order_orm(order_id=1, status="NEW"),
            make_order_orm(order_id=2, status="NEW"),
        ]
        mock_grid_state.get_order.side_effect = [
            make_order_orm(order_id=1, status="NEW"),
            make_order_orm(order_id=2, status="NEW"),
        ]
        mock_client.get.side_effect = [
            _binance_get_response(status="FILLED"),   # orden 1 cambió
            _binance_get_response(status="NEW"),       # orden 2 no cambió
        ]
        results = lifecycle_manager.sync_all_open_orders("SOLUSDT")
        assert len(results) == 2
        assert results[0].status_changed is True
        assert results[1].status_changed is False

    def test_empty_open_orders_returns_empty_list(
        self, lifecycle_manager, mock_grid_state
    ) -> None:
        mock_grid_state.get_open_orders.return_value = []
        results = lifecycle_manager.sync_all_open_orders("SOLUSDT")
        assert results == []


class TestHandleFillEvent:
    def test_marks_order_filled_in_m3(
        self, lifecycle_manager, mock_grid_state
    ) -> None:
        mock_grid_state.get_order.return_value = make_order_orm(status="NEW")
        lifecycle_manager.handle_fill_event(
            order_id=12345,
            symbol="SOLUSDT",
            filled_qty=Decimal("0.10"),
            fill_price=Decimal("150.00"),
        )
        mock_grid_state.update_order_status.assert_called_once_with(
            12345, OrderStatus.FILLED.value
        )

    def test_returns_correct_order_status_update(
        self, lifecycle_manager, mock_grid_state
    ) -> None:
        mock_grid_state.get_order.return_value = make_order_orm(status="NEW")
        result = lifecycle_manager.handle_fill_event(
            order_id=12345,
            symbol="SOLUSDT",
            filled_qty=Decimal("0.10"),
            fill_price=Decimal("150.00"),
        )
        assert result.previous_status == OrderStatus.NEW
        assert result.current_status == OrderStatus.FILLED
        assert result.status_changed is True
        assert result.executed_qty == Decimal("0.10")

    def test_order_not_in_m3_raises(
        self, lifecycle_manager, mock_grid_state
    ) -> None:
        mock_grid_state.get_order.return_value = None
        with pytest.raises(OrderNotFoundError):
            lifecycle_manager.handle_fill_event(
                order_id=99999,
                symbol="SOLUSDT",
                filled_qty=Decimal("0.10"),
                fill_price=Decimal("150.00"),
            )

    def test_duplicate_fill_event_returns_status_changed_false(
        self, lifecycle_manager, mock_grid_state
    ) -> None:
        mock_grid_state.get_order.return_value = make_order_orm(status="FILLED")
        result = lifecycle_manager.handle_fill_event(
            order_id=12345,
            symbol="SOLUSDT",
            filled_qty=Decimal("0.10"),
            fill_price=Decimal("150.00"),
        )
        assert result.status_changed is False
        assert result.previous_status.value == "FILLED"
        assert result.current_status.value == "FILLED"
        mock_grid_state.update_order_status.assert_not_called()
