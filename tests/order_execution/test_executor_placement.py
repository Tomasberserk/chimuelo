"""Tests para OrderExecutor — colocación de órdenes (place_limit_buy / sell).

Cubre:
    - Flujo feliz: BUY y SELL, M3 persistido correctamente.
    - FilterViolationError si precio no pasa filtros de M1.
    - FilterViolationError si notional no pasa filtros de M1.
    - InsufficientBalanceError en Binance -2021.
    - DuplicateOrderError recuperable (-2010, GET confirma que orden existe).
    - DuplicateOrderError no recuperable (-2010, GET falla).
    - DatabaseError relanzado con log CRITICAL si M3 falla post-Binance.
    - Precisión Decimal preservada desde respuesta de Binance.
    - Ningún float en el payload enviado a client.post.
    - M3 nunca escrito si Binance retorna error.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, call

import pytest

from chimuelo_prime.api_client.exceptions import BinanceAPIError
from chimuelo_prime.grid_state.exceptions import DatabaseError
from chimuelo_prime.grid_state.schema import OrderStatus
from chimuelo_prime.order_execution.exceptions import (
    DuplicateOrderError,
    FilterViolationError,
    InsufficientBalanceError,
    OrderPlacementError,
    OrderRejectedError,
)
from chimuelo_prime.order_execution.models import PlacedOrder
from tests.order_execution.conftest import make_binance_order_response


class TestPlaceLimitBuySuccess:
    def test_returns_placed_order(
        self, executor, mock_client, mock_grid_state
    ) -> None:
        mock_client.post.return_value = make_binance_order_response()
        result = executor.place_limit_buy(Decimal("150.00"), Decimal("0.10"), level_id=1)
        assert isinstance(result, PlacedOrder)
        assert result.order_id == 12345
        assert result.side == "BUY"
        assert result.status == OrderStatus.NEW

    def test_m3_save_order_called(self, executor, mock_client, mock_grid_state) -> None:
        mock_client.post.return_value = make_binance_order_response()
        executor.place_limit_buy(Decimal("150.00"), Decimal("0.10"), level_id=1)
        mock_grid_state.save_order.assert_called_once()

    def test_m3_update_level_buy_order_called(
        self, executor, mock_client, mock_grid_state
    ) -> None:
        mock_client.post.return_value = make_binance_order_response(order_id=12345)
        executor.place_limit_buy(Decimal("150.00"), Decimal("0.10"), level_id=7)
        mock_grid_state.update_level_buy_order.assert_called_once_with(7, 12345)

    def test_place_sell_calls_update_level_sell_order(
        self, executor, mock_client, mock_grid_state
    ) -> None:
        mock_client.post.return_value = make_binance_order_response(
            order_id=99, side="SELL"
        )
        executor.place_limit_sell(Decimal("160.00"), Decimal("0.10"), level_id=3)
        mock_grid_state.update_level_sell_order.assert_called_once_with(3, 99)
        mock_grid_state.update_level_buy_order.assert_not_called()

    def test_decimal_precision_preserved(
        self, executor, mock_client, mock_grid_state
    ) -> None:
        # El input es válido; lo que verificamos es que el precio de la respuesta
        # de Binance se parsea con precisión exacta via Decimal(str(...)), sin floats.
        mock_client.post.return_value = make_binance_order_response(price="150.00000001")
        result = executor.place_limit_buy(Decimal("150.00"), Decimal("0.10"), level_id=1)
        assert result.price == Decimal("150.00000001")

    def test_no_float_in_payload(self, executor, mock_client, mock_grid_state) -> None:
        mock_client.post.return_value = make_binance_order_response()
        executor.place_limit_buy(Decimal("150.00"), Decimal("0.10"), level_id=1)
        _, kwargs = mock_client.post.call_args
        payload = kwargs.get("params", {})
        for key, value in payload.items():
            assert not isinstance(value, float), f"Float encontrado en payload[{key!r}]"

    def test_is_order_true_in_post_call(
        self, executor, mock_client, mock_grid_state
    ) -> None:
        mock_client.post.return_value = make_binance_order_response()
        executor.place_limit_buy(Decimal("150.00"), Decimal("0.10"), level_id=1)
        _, kwargs = mock_client.post.call_args
        assert kwargs.get("is_order") is True


class TestPlaceLimitBuyFilterViolations:
    def test_filter_violation_price_below_min(self, executor, mock_grid_state) -> None:
        with pytest.raises(FilterViolationError):
            executor.place_limit_buy(Decimal("0.001"), Decimal("0.10"), level_id=1)
        mock_grid_state.save_order.assert_not_called()

    def test_filter_violation_notional_below_min(
        self, executor, mock_grid_state
    ) -> None:
        # min_notional=5.00; price=6.00, qty=0.01 → notional=0.06
        with pytest.raises(FilterViolationError):
            executor.place_limit_buy(Decimal("6.00"), Decimal("0.01"), level_id=1)
        mock_grid_state.save_order.assert_not_called()


class TestPlaceLimitBuyBinanceErrors:
    def test_insufficient_balance(
        self, executor, mock_client, mock_grid_state
    ) -> None:
        mock_client.post.side_effect = BinanceAPIError(400, -2021, "Insufficient balance")
        with pytest.raises(InsufficientBalanceError):
            executor.place_limit_buy(Decimal("150.00"), Decimal("0.10"), level_id=1)
        mock_grid_state.save_order.assert_not_called()

    def test_order_rejected_server_side_filter(
        self, executor, mock_client, mock_grid_state
    ) -> None:
        mock_client.post.side_effect = BinanceAPIError(400, -1013, "Filter failure")
        with pytest.raises(OrderRejectedError):
            executor.place_limit_buy(Decimal("150.00"), Decimal("0.10"), level_id=1)
        mock_grid_state.save_order.assert_not_called()

    def test_duplicate_order_recoverable(
        self, executor, mock_client, mock_grid_state
    ) -> None:
        mock_client.post.side_effect = BinanceAPIError(400, -2010, "Duplicate order")
        mock_client.get.return_value = make_binance_order_response(
            order_id=777, client_order_id="my_cid"
        )
        result = executor.place_limit_buy(
            Decimal("150.00"), Decimal("0.10"), level_id=2, client_order_id="my_cid"
        )
        assert result.order_id == 777
        mock_grid_state.save_order.assert_called_once()

    def test_duplicate_recoverable_m3_failure_relaunches(
        self, executor, mock_client, mock_grid_state
    ) -> None:
        mock_client.post.side_effect = BinanceAPIError(400, -2010, "Duplicate order")
        mock_client.get.return_value = make_binance_order_response(
            order_id=777, client_order_id="my_cid"
        )
        mock_grid_state.save_order.side_effect = DatabaseError("SQLite error")

        with pytest.raises(DatabaseError):
            executor.place_limit_buy(
                Decimal("150.00"), Decimal("0.10"), level_id=2, client_order_id="my_cid"
            )
        mock_client.post.assert_called_once()
        mock_client.get.assert_called_once()
        mock_grid_state.save_order.assert_called_once()

    def test_duplicate_order_not_recoverable_raises(
        self, executor, mock_client, mock_grid_state
    ) -> None:
        mock_client.post.side_effect = BinanceAPIError(400, -2010, "Duplicate order")
        mock_client.get.side_effect = BinanceAPIError(400, -2013, "Order not found")
        with pytest.raises(DuplicateOrderError):
            executor.place_limit_buy(
                Decimal("150.00"), Decimal("0.10"), level_id=2, client_order_id="my_cid"
            )
        mock_grid_state.save_order.assert_not_called()

    def test_duplicate_no_client_order_id_raises(
        self, executor, mock_client, mock_grid_state
    ) -> None:
        mock_client.post.side_effect = BinanceAPIError(400, -2010, "Duplicate order")
        with pytest.raises(DuplicateOrderError):
            executor.place_limit_buy(Decimal("150.00"), Decimal("0.10"), level_id=1)
        mock_grid_state.save_order.assert_not_called()

    def test_duplicate_recovery_non_2013_propagates(
        self, executor, mock_client, mock_grid_state
    ) -> None:
        # Si GET falla con código distinto a -2013 (ej. rate-limit), NO se silencia.
        mock_client.post.side_effect = BinanceAPIError(400, -2010, "Duplicate order")
        mock_client.get.side_effect = BinanceAPIError(429, -1003, "Too many requests")
        with pytest.raises(BinanceAPIError) as exc_info:
            executor.place_limit_buy(
                Decimal("150.00"), Decimal("0.10"), level_id=2, client_order_id="my_cid"
            )
        assert exc_info.value.binance_code == -1003
        mock_grid_state.save_order.assert_not_called()

    def test_generic_binance_error_raises_order_placement_error(
        self, executor, mock_client, mock_grid_state
    ) -> None:
        mock_client.post.side_effect = BinanceAPIError(500, -1000, "Unknown internal error")
        with pytest.raises(OrderPlacementError):
            executor.place_limit_buy(Decimal("150.00"), Decimal("0.10"), level_id=1)
        mock_grid_state.save_order.assert_not_called()


class TestPlaceLimitBuyM3Failure:
    def test_m3_write_failure_relaunches_and_does_not_silence(
        self, executor, mock_client, mock_grid_state
    ) -> None:
        mock_client.post.return_value = make_binance_order_response()
        mock_grid_state.save_order.side_effect = DatabaseError("SQLite error")

        with pytest.raises(DatabaseError):
            executor.place_limit_buy(Decimal("150.00"), Decimal("0.10"), level_id=1)

        # Binance sí fue llamado; M3 falló
        mock_client.post.assert_called_once()
        mock_grid_state.save_order.assert_called_once()
