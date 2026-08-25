"""Tests para OrderExecutor — cancelación de órdenes.

Cubre:
    - cancel_order flujo feliz: M3 actualizado con CANCELED.
    - cancel_order -2011 con orden FILLED en tránsito: M3 actualizado con FILLED,
      OrderNotCancelableError con actual_status=FILLED.
    - cancel_order -2011 con estado desconocido (GET falla): actual_status=None.
    - cancel_all_open_orders: todas las órdenes abiertas canceladas, resultados correctos.
    - cancel_all_open_orders vacío: lista vacía, sin llamadas a client.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from chimuelo_prime.api_client.exceptions import BinanceAPIError
from chimuelo_prime.grid_state.schema import OrderStatus
from chimuelo_prime.order_execution.exceptions import (
    AggregateCancellationError,
    OrderCancellationError,
    OrderNotCancelableError,
)
from chimuelo_prime.order_execution.models import CancelResult
from tests.order_execution.conftest import make_binance_order_response, make_order_orm


def _make_cancel_response(order_id: int = 12345, executed_qty: str = "0.00") -> dict:
    return {
        "symbol": "SOLUSDT",
        "orderId": order_id,
        "clientOrderId": "cancel_cid",
        "origQty": "0.10",
        "executedQty": executed_qty,
        "status": "CANCELED",
        "price": "150.00",
        "side": "BUY",
    }


class TestCancelOrderSuccess:
    def test_returns_cancel_result(self, executor, mock_client) -> None:
        mock_client.delete.return_value = _make_cancel_response()
        result = executor.cancel_order(order_id=12345, symbol="SOLUSDT")
        assert isinstance(result, CancelResult)
        assert result.status == OrderStatus.CANCELED
        assert result.order_id == 12345

    def test_m3_status_updated_to_canceled(self, executor, mock_client, mock_grid_state) -> None:
        mock_client.delete.return_value = _make_cancel_response()
        executor.cancel_order(order_id=12345, symbol="SOLUSDT")
        mock_grid_state.update_order_status.assert_called_once_with(
            12345, OrderStatus.CANCELED.value
        )

    def test_executed_qty_preserved(self, executor, mock_client) -> None:
        mock_client.delete.return_value = _make_cancel_response(executed_qty="0.05")
        result = executor.cancel_order(order_id=12345, symbol="SOLUSDT")
        assert result.executed_qty == Decimal("0.05")


class TestCancelOrderFilledInTransit:
    def test_raises_not_cancelable_with_filled_status(
        self, executor, mock_client, mock_grid_state
    ) -> None:
        mock_client.delete.side_effect = BinanceAPIError(400, -2011, "Order not found")
        mock_client.get.return_value = make_binance_order_response(status="FILLED")
        with pytest.raises(OrderNotCancelableError) as exc_info:
            executor.cancel_order(order_id=12345, symbol="SOLUSDT")
        assert exc_info.value.actual_status == OrderStatus.FILLED

    def test_m3_updated_with_filled_when_discovered(
        self, executor, mock_client, mock_grid_state
    ) -> None:
        mock_client.delete.side_effect = BinanceAPIError(400, -2011, "Order not found")
        mock_client.get.return_value = make_binance_order_response(status="FILLED")
        with pytest.raises(OrderNotCancelableError):
            executor.cancel_order(order_id=12345, symbol="SOLUSDT")
        mock_grid_state.update_order_status.assert_called_once_with(12345, OrderStatus.FILLED.value)

    def test_actual_status_none_when_get_also_fails(
        self, executor, mock_client, mock_grid_state
    ) -> None:
        mock_client.delete.side_effect = BinanceAPIError(400, -2011, "Order not found")
        mock_client.get.side_effect = BinanceAPIError(400, -2013, "No order")
        with pytest.raises(OrderNotCancelableError) as exc_info:
            executor.cancel_order(order_id=12345, symbol="SOLUSDT")
        assert exc_info.value.actual_status is None
        mock_grid_state.update_order_status.assert_not_called()

    def test_other_binance_error_raises_cancellation_error(self, executor, mock_client) -> None:
        mock_client.delete.side_effect = BinanceAPIError(500, -1000, "Internal error")
        with pytest.raises(OrderCancellationError):
            executor.cancel_order(order_id=12345, symbol="SOLUSDT")


class TestCancelAllOpenOrders:
    def test_cancels_all_open_orders(self, executor, mock_client, mock_grid_state) -> None:
        open_orders = [make_order_orm(order_id=1), make_order_orm(order_id=2)]
        mock_grid_state.get_open_orders.return_value = open_orders
        mock_client.delete.side_effect = [
            _make_cancel_response(order_id=1),
            _make_cancel_response(order_id=2),
        ]
        results = executor.cancel_all_open_orders("SOLUSDT")
        assert len(results) == 2
        assert all(isinstance(r, CancelResult) for r in results)
        assert mock_grid_state.update_order_status.call_count == 2

    def test_empty_open_orders_returns_empty_list(
        self, executor, mock_client, mock_grid_state
    ) -> None:
        mock_grid_state.get_open_orders.return_value = []
        results = executor.cancel_all_open_orders("SOLUSDT")
        assert results == []
        mock_client.delete.assert_not_called()

    def test_partial_failure_raises_aggregate_error(
        self, executor, mock_client, mock_grid_state
    ) -> None:
        open_orders = [make_order_orm(order_id=1), make_order_orm(order_id=2)]
        mock_grid_state.get_open_orders.return_value = open_orders
        mock_client.delete.side_effect = [
            _make_cancel_response(order_id=1),
            BinanceAPIError(500, -1000, "Internal error"),
        ]
        with pytest.raises(AggregateCancellationError) as exc_info:
            executor.cancel_all_open_orders("SOLUSDT")
        err = exc_info.value
        assert len(err.partial_results) == 1
        assert err.partial_results[0].order_id == 1
        assert len(err.errors) == 1
        assert err.errors[0][0] == 2

    def test_all_fail_raises_aggregate_with_no_partial_results(
        self, executor, mock_client, mock_grid_state
    ) -> None:
        open_orders = [make_order_orm(order_id=3), make_order_orm(order_id=4)]
        mock_grid_state.get_open_orders.return_value = open_orders
        mock_client.delete.side_effect = BinanceAPIError(500, -1000, "Error")
        with pytest.raises(AggregateCancellationError) as exc_info:
            executor.cancel_all_open_orders("SOLUSDT")
        assert exc_info.value.partial_results == []
        assert len(exc_info.value.errors) == 2
