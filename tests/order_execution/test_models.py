"""Tests para los modelos de M4 — float rejection validators y cobertura de ramas."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from chimuelo_prime.grid_state.schema import OrderStatus
from chimuelo_prime.order_execution.models import (
    CancelResult,
    OrderStatusUpdate,
    PlacedOrder,
)
from tests.order_execution.conftest import make_binance_order_response


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class TestPlacedOrderFloatRejection:
    def test_float_price_raises(self) -> None:
        with pytest.raises(Exception):
            PlacedOrder(
                order_id=1,
                client_order_id="cid",
                symbol="SOLUSDT",
                side="BUY",
                price=150.0,  # type: ignore[arg-type]
                orig_qty=Decimal("0.10"),
                executed_qty=Decimal("0.00"),
                status=OrderStatus.NEW,
                level_id=1,
                transact_time=_now(),
            )

    def test_float_orig_qty_raises(self) -> None:
        with pytest.raises(Exception):
            PlacedOrder(
                order_id=1,
                client_order_id="cid",
                symbol="SOLUSDT",
                side="BUY",
                price=Decimal("150.00"),
                orig_qty=0.10,  # type: ignore[arg-type]
                executed_qty=Decimal("0.00"),
                status=OrderStatus.NEW,
                level_id=1,
                transact_time=_now(),
            )


class TestCancelResultFloatRejection:
    def test_float_orig_qty_raises(self) -> None:
        with pytest.raises(Exception):
            CancelResult(
                order_id=1,
                symbol="SOLUSDT",
                status=OrderStatus.CANCELED,
                orig_qty=0.10,  # type: ignore[arg-type]
                executed_qty=Decimal("0.00"),
            )


class TestOrderStatusUpdateFloatRejection:
    def test_float_executed_qty_raises(self) -> None:
        with pytest.raises(Exception):
            OrderStatusUpdate(
                order_id=1,
                symbol="SOLUSDT",
                previous_status=OrderStatus.NEW,
                current_status=OrderStatus.FILLED,
                executed_qty=0.10,  # type: ignore[arg-type]
                synced_at=_now(),
                status_changed=True,
            )


class TestParseUtcnowFallback:
    """Cubre la rama _utcnow() en executor._parse_placed_order cuando transactTime=0."""

    def test_response_without_transact_time_uses_utcnow(
        self, executor, mock_client, mock_grid_state
    ) -> None:
        response = make_binance_order_response()
        response["transactTime"] = 0  # fuerza la rama _utcnow()
        mock_client.post.return_value = response
        result = executor.place_limit_buy(Decimal("150.00"), Decimal("0.10"), level_id=1)
        assert result.order_id == 12345
