"""Fixtures compartidos para los tests de order_execution (M4)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from chimuelo_prime.api_client.client import BinanceAuthenticatedClient
from chimuelo_prime.exchange_config.models import SymbolConfig, SymbolFilters
from chimuelo_prime.grid_state.grid_state import GridState
from chimuelo_prime.grid_state.schema import Order, OrderStatus
from chimuelo_prime.order_execution.executor import OrderExecutor
from chimuelo_prime.order_execution.lifecycle import OrderLifecycleManager


# --------------------------------------------------------------------------- #
# SymbolConfig realista (basado en filtros reales de SOLUSDT en Binance)
# --------------------------------------------------------------------------- #
@pytest.fixture
def symbol_filters() -> SymbolFilters:
    return SymbolFilters(
        symbol="SOLUSDT",
        tick_size=Decimal("0.01"),
        min_price=Decimal("0.01"),
        max_price=Decimal("10000.00"),
        step_size=Decimal("0.01"),
        min_qty=Decimal("0.01"),
        max_qty=Decimal("10000.00"),
        min_notional=Decimal("5.00"),
        pct_up=Decimal("5.0"),
        pct_down=Decimal("0.2"),
    )


@pytest.fixture
def symbol_config(symbol_filters: SymbolFilters) -> SymbolConfig:
    return SymbolConfig(
        filters=symbol_filters,
        upper_bound=Decimal("200.00"),
        lower_bound=Decimal("100.00"),
        grid_levels=20,
        capital_per_order=Decimal("10.00"),
    )


# --------------------------------------------------------------------------- #
# Mocks de dependencias
# --------------------------------------------------------------------------- #
@pytest.fixture
def mock_client() -> MagicMock:
    return MagicMock(spec=BinanceAuthenticatedClient)


@pytest.fixture
def mock_grid_state() -> MagicMock:
    return MagicMock(spec=GridState)


# --------------------------------------------------------------------------- #
# Instancias de M4
# --------------------------------------------------------------------------- #
@pytest.fixture
def executor(
    mock_client: MagicMock,
    mock_grid_state: MagicMock,
    symbol_config: SymbolConfig,
) -> OrderExecutor:
    return OrderExecutor(
        client=mock_client,
        grid_state=mock_grid_state,
        config=symbol_config,
    )


@pytest.fixture
def lifecycle_manager(
    mock_client: MagicMock,
    mock_grid_state: MagicMock,
) -> OrderLifecycleManager:
    return OrderLifecycleManager(client=mock_client, grid_state=mock_grid_state)


# --------------------------------------------------------------------------- #
# Helpers de datos
# --------------------------------------------------------------------------- #
def make_binance_order_response(
    order_id: int = 12345,
    client_order_id: str = "test_cid",
    symbol: str = "SOLUSDT",
    side: str = "BUY",
    price: str = "150.00",
    orig_qty: str = "0.10",
    executed_qty: str = "0.00",
    status: str = "NEW",
) -> dict:
    return {
        "symbol": symbol,
        "orderId": order_id,
        "clientOrderId": client_order_id,
        "transactTime": 1700000000000,
        "price": price,
        "origQty": orig_qty,
        "executedQty": executed_qty,
        "status": status,
        "timeInForce": "GTC",
        "type": "LIMIT",
        "side": side,
    }


def make_order_orm(
    order_id: int = 12345,
    symbol: str = "SOLUSDT",
    side: str = "BUY",
    status: str = "NEW",
    price: str = "150.00",
    qty: str = "0.10",
) -> Order:
    now = datetime.now(UTC).replace(tzinfo=None)
    return Order(
        order_id=order_id,
        symbol=symbol,
        side=side,
        price=Decimal(price),
        qty=Decimal(qty),
        status=status,
        created_at=now,
        updated_at=now,
    )
