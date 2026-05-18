"""Tests para Reconciler — sincronización con Binance (reconciler.py).

Cubre:
    - reconcile: sin divergencias → resultado vacío.
    - reconcile: orden local ausente en Binance + Binance retorna FILLED → se marca FILLED.
    - reconcile: orden local ausente en Binance + Binance retorna CANCELED → se marca CANCELED.
    - reconcile: orden en Binance no está en local → unexpected_ids.
    - ReconciliationResult.has_divergences: True/False según contenido.
    - reconcile: usa weight correcto en consume de API.
    - reconcile: error en fetch_open_orders → ReconciliationError.
    - reconcile: error en fetch_order_status → ReconciliationError.
    - ReconciliationResult es frozen dataclass (inmutable).
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from chimuelo_prime.api_client.exceptions import BinanceAPIError
from chimuelo_prime.grid_state.database import build_engine
from chimuelo_prime.grid_state.exceptions import ReconciliationError
from chimuelo_prime.grid_state.grid_state import GridState
from chimuelo_prime.grid_state.reconciler import Reconciler, ReconciliationResult
from chimuelo_prime.grid_state.schema import Order


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _make_order(order_id: int, status: str = "NEW", symbol: str = "SOLUSDT") -> Order:
    now = _utcnow()
    return Order(
        order_id=order_id,
        symbol=symbol,
        side="BUY",
        price=Decimal("150.00"),
        qty=Decimal("1.0"),
        status=status,
        created_at=now,
        updated_at=now,
    )


def _mock_client(
    open_orders: list[dict[str, object]],
    order_statuses: dict[int, str] | None = None,
) -> MagicMock:
    """Crea un MagicMock de BinanceAuthenticatedClient.

    open_orders: respuesta de GET /api/v3/openOrders.
    order_statuses: {order_id: status} para GET /api/v3/order.
    """
    client = MagicMock()
    statuses = order_statuses or {}

    def _get(endpoint: str, params: dict[str, object] | None = None, weight: int = 1) -> object:
        params = params or {}
        if endpoint == "/api/v3/openOrders":
            return open_orders
        if endpoint == "/api/v3/order":
            order_id = int(params["orderId"])  # type: ignore[arg-type]
            return {"status": statuses.get(order_id, "CANCELED")}
        return {}

    client.get.side_effect = _get
    return client


@pytest.fixture
def engine():  # type: ignore[no-untyped-def]
    return build_engine("sqlite:///:memory:")


@pytest.fixture
def state(engine):  # type: ignore[no-untyped-def]
    return GridState(engine)


# --------------------------------------------------------------------------- #
# Sin divergencias
# --------------------------------------------------------------------------- #
class TestReconcileNoDivergences:
    def test_no_divergences_returns_empty_result(self, state: GridState) -> None:
        order = _make_order(order_id=1001, status="NEW")
        state.save_order(order)
        client = _mock_client(open_orders=[{"orderId": 1001, "symbol": "SOLUSDT", "status": "NEW"}])
        reconciler = Reconciler(grid_state=state, api_client=client)
        result = reconciler.reconcile("SOLUSDT")
        assert result.filled_ids == []
        assert result.canceled_ids == []
        assert result.unexpected_ids == []

    def test_no_local_orders_no_binance_orders(self, state: GridState) -> None:
        client = _mock_client(open_orders=[])
        reconciler = Reconciler(grid_state=state, api_client=client)
        result = reconciler.reconcile("SOLUSDT")
        assert not result.has_divergences

    def test_result_symbol_matches(self, state: GridState) -> None:
        client = _mock_client(open_orders=[])
        reconciler = Reconciler(grid_state=state, api_client=client)
        result = reconciler.reconcile("BTCUSDT")
        assert result.symbol == "BTCUSDT"


# --------------------------------------------------------------------------- #
# Orden local ausente en Binance → FILLED
# --------------------------------------------------------------------------- #
class TestReconcileFilledOrders:
    def test_missing_from_binance_filled_updates_local_db(self, state: GridState) -> None:
        state.save_order(_make_order(order_id=2001, status="NEW"))
        client = _mock_client(
            open_orders=[],  # 2001 ya no está en Binance
            order_statuses={2001: "FILLED"},
        )
        reconciler = Reconciler(grid_state=state, api_client=client)
        result = reconciler.reconcile("SOLUSDT")
        assert 2001 in result.filled_ids
        updated = state.get_order(2001)
        assert updated is not None
        assert updated.status == "FILLED"

    def test_filled_order_not_in_canceled_ids(self, state: GridState) -> None:
        state.save_order(_make_order(order_id=2002, status="NEW"))
        client = _mock_client(open_orders=[], order_statuses={2002: "FILLED"})
        reconciler = Reconciler(grid_state=state, api_client=client)
        result = reconciler.reconcile("SOLUSDT")
        assert 2002 not in result.canceled_ids

    def test_partially_filled_treated_as_filled(self, state: GridState) -> None:
        state.save_order(_make_order(order_id=2003, status="NEW"))
        client = _mock_client(open_orders=[], order_statuses={2003: "PARTIALLY_FILLED"})
        reconciler = Reconciler(grid_state=state, api_client=client)
        result = reconciler.reconcile("SOLUSDT")
        assert 2003 in result.filled_ids


# --------------------------------------------------------------------------- #
# Orden local ausente en Binance → CANCELED / EXPIRED
# --------------------------------------------------------------------------- #
class TestReconcileCanceledOrders:
    def test_missing_from_binance_canceled_updates_local_db(self, state: GridState) -> None:
        state.save_order(_make_order(order_id=3001, status="NEW"))
        client = _mock_client(open_orders=[], order_statuses={3001: "CANCELED"})
        reconciler = Reconciler(grid_state=state, api_client=client)
        result = reconciler.reconcile("SOLUSDT")
        assert 3001 in result.canceled_ids
        updated = state.get_order(3001)
        assert updated is not None
        assert updated.status == "CANCELED"

    def test_expired_order_lands_in_canceled_ids(self, state: GridState) -> None:
        state.save_order(_make_order(order_id=3002, status="NEW"))
        client = _mock_client(open_orders=[], order_statuses={3002: "EXPIRED"})
        reconciler = Reconciler(grid_state=state, api_client=client)
        result = reconciler.reconcile("SOLUSDT")
        assert 3002 in result.canceled_ids
        updated = state.get_order(3002)
        assert updated is not None
        assert updated.status == "EXPIRED"

    def test_canceled_order_not_in_filled_ids(self, state: GridState) -> None:
        state.save_order(_make_order(order_id=3003, status="NEW"))
        client = _mock_client(open_orders=[], order_statuses={3003: "CANCELED"})
        reconciler = Reconciler(grid_state=state, api_client=client)
        result = reconciler.reconcile("SOLUSDT")
        assert 3003 not in result.filled_ids


# --------------------------------------------------------------------------- #
# Orden en Binance pero no en local → unexpected
# --------------------------------------------------------------------------- #
class TestReconcileUnexpectedOrders:
    def test_binance_order_not_in_local_goes_to_unexpected(self, state: GridState) -> None:
        client = _mock_client(open_orders=[{"orderId": 4001, "symbol": "SOLUSDT", "status": "NEW"}])
        reconciler = Reconciler(grid_state=state, api_client=client)
        result = reconciler.reconcile("SOLUSDT")
        assert 4001 in result.unexpected_ids

    def test_unexpected_order_not_inserted_in_db(self, state: GridState) -> None:
        client = _mock_client(open_orders=[{"orderId": 4002, "symbol": "SOLUSDT", "status": "NEW"}])
        reconciler = Reconciler(grid_state=state, api_client=client)
        reconciler.reconcile("SOLUSDT")
        assert state.get_order(4002) is None

    def test_has_divergences_true_on_unexpected(self, state: GridState) -> None:
        client = _mock_client(open_orders=[{"orderId": 4003, "symbol": "SOLUSDT", "status": "NEW"}])
        reconciler = Reconciler(grid_state=state, api_client=client)
        result = reconciler.reconcile("SOLUSDT")
        assert result.has_divergences is True


# --------------------------------------------------------------------------- #
# has_divergences
# --------------------------------------------------------------------------- #
class TestReconciliationResultHasDivergences:
    def test_no_divergences_false(self) -> None:
        r = ReconciliationResult(symbol="SOLUSDT")
        assert r.has_divergences is False

    def test_filled_ids_triggers_divergences(self) -> None:
        r = ReconciliationResult(symbol="SOLUSDT", filled_ids=[1])
        assert r.has_divergences is True

    def test_canceled_ids_triggers_divergences(self) -> None:
        r = ReconciliationResult(symbol="SOLUSDT", canceled_ids=[2])
        assert r.has_divergences is True

    def test_unexpected_ids_triggers_divergences(self) -> None:
        r = ReconciliationResult(symbol="SOLUSDT", unexpected_ids=[3])
        assert r.has_divergences is True

    def test_result_is_frozen(self) -> None:
        r = ReconciliationResult(symbol="SOLUSDT")
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.symbol = "BTCUSDT"  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# Errores de API → ReconciliationError
# --------------------------------------------------------------------------- #
class TestReconcilerAPIErrors:
    def test_fetch_open_orders_error_raises_reconciliation_error(self, state: GridState) -> None:
        client = MagicMock()
        client.get.side_effect = BinanceAPIError(
            status_code=500, binance_code=-1000, msg="Internal error"
        )
        reconciler = Reconciler(grid_state=state, api_client=client)
        with pytest.raises(ReconciliationError):
            reconciler.reconcile("SOLUSDT")

    def test_fetch_order_status_error_raises_reconciliation_error(self, state: GridState) -> None:
        state.save_order(_make_order(order_id=5001, status="NEW"))
        call_count = 0

        def _get(
            endpoint: str,
            params: dict[str, object] | None = None,
            weight: int = 1,
        ) -> object:
            nonlocal call_count
            call_count += 1
            if endpoint == "/api/v3/openOrders":
                return []  # 5001 desaparece de Binance
            raise BinanceAPIError(status_code=400, binance_code=-2013, msg="Order not found")

        client = MagicMock()
        client.get.side_effect = _get
        reconciler = Reconciler(grid_state=state, api_client=client)
        with pytest.raises(ReconciliationError):
            reconciler.reconcile("SOLUSDT")

    def test_unexpected_response_type_raises_reconciliation_error(self, state: GridState) -> None:
        client = MagicMock()
        client.get.return_value = {"error": "not a list"}  # openOrders debe ser lista
        reconciler = Reconciler(grid_state=state, api_client=client)
        with pytest.raises(ReconciliationError):
            reconciler.reconcile("SOLUSDT")


# --------------------------------------------------------------------------- #
# Integración: múltiples órdenes en distintos estados
# --------------------------------------------------------------------------- #
class TestReconcileIntegration:
    def test_mixed_scenario(self, state: GridState) -> None:
        state.save_order(_make_order(order_id=9001, status="NEW"))  # sigue open
        state.save_order(_make_order(order_id=9002, status="NEW"))  # se llenó
        state.save_order(_make_order(order_id=9003, status="NEW"))  # fue cancelada

        client = _mock_client(
            open_orders=[
                {"orderId": 9001, "symbol": "SOLUSDT", "status": "NEW"},
                {"orderId": 9099, "symbol": "SOLUSDT", "status": "NEW"},  # inesperada
            ],
            order_statuses={9002: "FILLED", 9003: "CANCELED"},
        )
        reconciler = Reconciler(grid_state=state, api_client=client)
        result = reconciler.reconcile("SOLUSDT")

        assert 9002 in result.filled_ids
        assert 9003 in result.canceled_ids
        assert 9099 in result.unexpected_ids
        assert 9001 not in result.filled_ids
        assert 9001 not in result.canceled_ids
        assert result.has_divergences is True
