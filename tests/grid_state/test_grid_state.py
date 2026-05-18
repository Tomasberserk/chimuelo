"""Tests para GridState — CRUD y transacciones (grid_state.py).

Cubre:
    Órdenes:
        - save_order: INSERT y UPDATE (upsert via merge).
        - get_order: recupera o retorna None.
        - get_open_orders: filtra por status NEW/PARTIALLY_FILLED.
        - update_order_status: persiste cambio, actualiza updated_at.
        - update_order_status de orden inexistente → OrderNotFoundError.

    Niveles de grid:
        - save_grid_level: retorna level_id asignado.
        - get_grid_levels: ordenados por lower_price.
        - get_grid_levels: aislados por símbolo.
        - update_level_buy_order / sell_order: persisten.
        - update level de nivel inexistente → GridLevelNotFoundError.

    Snapshots:
        - save_snapshot: persiste.
        - get_latest_snapshot: retorna el más reciente.
        - get_latest_snapshot sin datos → None.

    Transacciones:
        - Rollback ante excepción antes de commit (ACID).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from chimuelo_prime.grid_state.database import build_engine
from chimuelo_prime.grid_state.exceptions import GridLevelNotFoundError, OrderNotFoundError
from chimuelo_prime.grid_state.grid_state import GridState
from chimuelo_prime.grid_state.schema import GridLevel, Order, Snapshot


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _make_order(
    order_id: int,
    symbol: str = "SOLUSDT",
    side: str = "BUY",
    status: str = "NEW",
    price: str = "150.00",
    qty: str = "1.0",
) -> Order:
    now = _utcnow()
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


def _make_level(
    symbol: str = "SOLUSDT",
    lower: str = "140.00",
    upper: str = "150.00",
) -> GridLevel:
    return GridLevel(
        symbol=symbol,
        lower_price=Decimal(lower),
        upper_price=Decimal(upper),
        created_at=_utcnow(),
    )


def _make_snapshot(
    symbol: str = "SOLUSDT",
    equity: str = "1000.00",
    inventory: str = "5.0",
    cash: str = "250.00",
) -> Snapshot:
    return Snapshot(
        symbol=symbol,
        equity=Decimal(equity),
        inventory=Decimal(inventory),
        cash=Decimal(cash),
        created_at=_utcnow(),
    )


@pytest.fixture
def engine():  # type: ignore[no-untyped-def]
    return build_engine("sqlite:///:memory:")


@pytest.fixture
def state(engine):  # type: ignore[no-untyped-def]
    return GridState(engine)


# --------------------------------------------------------------------------- #
# Órdenes — save / get
# --------------------------------------------------------------------------- #
class TestSaveGetOrder:
    def test_save_and_retrieve_order(self, state: GridState) -> None:
        order = _make_order(order_id=1001)
        state.save_order(order)
        retrieved = state.get_order(1001)
        assert retrieved is not None
        assert retrieved.order_id == 1001
        assert retrieved.symbol == "SOLUSDT"
        assert retrieved.status == "NEW"

    def test_get_order_returns_none_if_not_found(self, state: GridState) -> None:
        assert state.get_order(99999) is None

    def test_save_order_upsert_updates_existing(self, state: GridState) -> None:
        order = _make_order(order_id=2001, status="NEW")
        state.save_order(order)
        order_updated = _make_order(order_id=2001, status="FILLED")
        state.save_order(order_updated)
        retrieved = state.get_order(2001)
        assert retrieved is not None
        assert retrieved.status == "FILLED"

    def test_price_persisted_correctly(self, state: GridState) -> None:
        order = _make_order(order_id=3001, price="152.50")
        state.save_order(order)
        retrieved = state.get_order(3001)
        assert retrieved is not None
        assert float(retrieved.price) == pytest.approx(152.50, rel=1e-5)

    def test_save_multiple_orders(self, state: GridState) -> None:
        for i in range(5):
            state.save_order(_make_order(order_id=4000 + i))
        for i in range(5):
            assert state.get_order(4000 + i) is not None


# --------------------------------------------------------------------------- #
# Órdenes — get_open_orders
# --------------------------------------------------------------------------- #
class TestGetOpenOrders:
    def test_returns_new_orders(self, state: GridState) -> None:
        state.save_order(_make_order(order_id=101, status="NEW"))
        open_orders = state.get_open_orders("SOLUSDT")
        assert any(o.order_id == 101 for o in open_orders)

    def test_returns_partially_filled(self, state: GridState) -> None:
        state.save_order(_make_order(order_id=102, status="PARTIALLY_FILLED"))
        open_orders = state.get_open_orders("SOLUSDT")
        assert any(o.order_id == 102 for o in open_orders)

    def test_excludes_filled_orders(self, state: GridState) -> None:
        state.save_order(_make_order(order_id=103, status="FILLED"))
        open_orders = state.get_open_orders("SOLUSDT")
        assert not any(o.order_id == 103 for o in open_orders)

    def test_excludes_canceled_orders(self, state: GridState) -> None:
        state.save_order(_make_order(order_id=104, status="CANCELED"))
        open_orders = state.get_open_orders("SOLUSDT")
        assert not any(o.order_id == 104 for o in open_orders)

    def test_isolated_by_symbol(self, state: GridState) -> None:
        state.save_order(_make_order(order_id=201, symbol="SOLUSDT", status="NEW"))
        state.save_order(_make_order(order_id=202, symbol="BTCUSDT", status="NEW"))
        sol_orders = state.get_open_orders("SOLUSDT")
        assert all(o.symbol == "SOLUSDT" for o in sol_orders)
        assert not any(o.order_id == 202 for o in sol_orders)

    def test_returns_empty_when_no_open_orders(self, state: GridState) -> None:
        assert state.get_open_orders("XRPUSDT") == []


# --------------------------------------------------------------------------- #
# Órdenes — update_order_status
# --------------------------------------------------------------------------- #
class TestUpdateOrderStatus:
    def test_status_update_persists(self, state: GridState) -> None:
        state.save_order(_make_order(order_id=501, status="NEW"))
        state.update_order_status(501, "FILLED")
        retrieved = state.get_order(501)
        assert retrieved is not None
        assert retrieved.status == "FILLED"

    def test_updated_at_changes(self, state: GridState) -> None:
        import time

        order = _make_order(order_id=502, status="NEW")
        state.save_order(order)
        original_updated_at = state.get_order(502)
        assert original_updated_at is not None
        t0 = original_updated_at.updated_at
        time.sleep(0.01)
        state.update_order_status(502, "CANCELED")
        updated = state.get_order(502)
        assert updated is not None
        assert updated.updated_at >= t0

    def test_raises_if_order_not_found(self, state: GridState) -> None:
        with pytest.raises(OrderNotFoundError):
            state.update_order_status(99999, "FILLED")


# --------------------------------------------------------------------------- #
# Niveles de grid
# --------------------------------------------------------------------------- #
class TestGridLevels:
    def test_save_level_returns_level_id(self, state: GridState) -> None:
        level_id = state.save_grid_level(_make_level())
        assert isinstance(level_id, int)
        assert level_id > 0

    def test_level_ids_are_unique(self, state: GridState) -> None:
        id1 = state.save_grid_level(_make_level(lower="100", upper="110"))
        id2 = state.save_grid_level(_make_level(lower="110", upper="120"))
        assert id1 != id2

    def test_get_grid_levels_ordered_by_lower_price(self, state: GridState) -> None:
        state.save_grid_level(_make_level(lower="130", upper="140"))
        state.save_grid_level(_make_level(lower="110", upper="120"))
        state.save_grid_level(_make_level(lower="120", upper="130"))
        levels = state.get_grid_levels("SOLUSDT")
        prices = [float(lv.lower_price) for lv in levels]
        assert prices == sorted(prices)

    def test_get_grid_levels_isolated_by_symbol(self, state: GridState) -> None:
        state.save_grid_level(_make_level(symbol="SOLUSDT"))
        state.save_grid_level(_make_level(symbol="BTCUSDT"))
        sol_levels = state.get_grid_levels("SOLUSDT")
        assert all(lv.symbol == "SOLUSDT" for lv in sol_levels)

    def test_get_grid_level_returns_none_if_not_found(self, state: GridState) -> None:
        assert state.get_grid_level(99999) is None

    def test_get_grid_level_by_id(self, state: GridState) -> None:
        level_id = state.save_grid_level(_make_level(lower="200", upper="210"))
        level = state.get_grid_level(level_id)
        assert level is not None
        assert float(level.lower_price) == pytest.approx(200.0, rel=1e-5)

    def test_update_level_buy_order(self, state: GridState) -> None:
        order = _make_order(order_id=6001)
        state.save_order(order)
        level_id = state.save_grid_level(_make_level())
        state.update_level_buy_order(level_id, 6001)
        level = state.get_grid_level(level_id)
        assert level is not None
        assert level.buy_order_id == 6001
        assert level.sell_order_id is None

    def test_update_level_sell_order(self, state: GridState) -> None:
        buy = _make_order(order_id=7001)
        sell = _make_order(order_id=7002, side="SELL")
        state.save_order(buy)
        state.save_order(sell)
        level_id = state.save_grid_level(_make_level())
        state.update_level_buy_order(level_id, 7001)
        state.update_level_sell_order(level_id, 7002)
        level = state.get_grid_level(level_id)
        assert level is not None
        assert level.buy_order_id == 7001
        assert level.sell_order_id == 7002

    def test_update_buy_order_raises_if_level_not_found(self, state: GridState) -> None:
        with pytest.raises(GridLevelNotFoundError):
            state.update_level_buy_order(99999, 1)

    def test_update_sell_order_raises_if_level_not_found(self, state: GridState) -> None:
        with pytest.raises(GridLevelNotFoundError):
            state.update_level_sell_order(99999, 1)


# --------------------------------------------------------------------------- #
# Snapshots
# --------------------------------------------------------------------------- #
class TestSnapshots:
    def test_save_and_get_latest_snapshot(self, state: GridState) -> None:
        snap = _make_snapshot(equity="1500.00")
        state.save_snapshot(snap)
        latest = state.get_latest_snapshot("SOLUSDT")
        assert latest is not None
        assert float(latest.equity) == pytest.approx(1500.0, rel=1e-4)

    def test_get_latest_returns_none_when_empty(self, state: GridState) -> None:
        assert state.get_latest_snapshot("XRPUSDT") is None

    def test_get_latest_returns_most_recent(self, state: GridState) -> None:
        import time

        state.save_snapshot(_make_snapshot(equity="1000"))
        time.sleep(0.01)
        state.save_snapshot(_make_snapshot(equity="1200"))
        latest = state.get_latest_snapshot("SOLUSDT")
        assert latest is not None
        assert float(latest.equity) == pytest.approx(1200.0, rel=1e-4)

    def test_snapshots_isolated_by_symbol(self, state: GridState) -> None:
        state.save_snapshot(_make_snapshot(symbol="SOLUSDT", equity="1000"))
        state.save_snapshot(_make_snapshot(symbol="BTCUSDT", equity="50000"))
        sol = state.get_latest_snapshot("SOLUSDT")
        btc = state.get_latest_snapshot("BTCUSDT")
        assert sol is not None
        assert btc is not None
        assert float(sol.equity) == pytest.approx(1000.0, rel=1e-4)
        assert float(btc.equity) == pytest.approx(50000.0, rel=1e-4)


# --------------------------------------------------------------------------- #
# Transacciones — rollback ACID
# --------------------------------------------------------------------------- #
class TestTransactionRollback:
    def test_rollback_on_exception_before_commit(self, state: GridState, engine) -> None:  # type: ignore[no-untyped-def]
        order = _make_order(order_id=8001, status="NEW")
        state.save_order(order)

        try:
            with Session(engine) as session:
                o = session.get(Order, 8001)
                assert o is not None
                o.status = "FILLED"
                second_order = _make_order(order_id=8002)
                session.add(second_order)
                raise RuntimeError("Crash simulado antes de commit")
                session.commit()  # type: ignore[unreachable]
        except RuntimeError:
            pass

        assert state.get_order(8001) is not None
        assert state.get_order(8001).status == "NEW"  # type: ignore[union-attr]
        assert state.get_order(8002) is None

    def test_multiple_saves_are_independent_transactions(self, state: GridState) -> None:
        state.save_order(_make_order(order_id=9001))
        state.save_order(_make_order(order_id=9002))
        state.save_order(_make_order(order_id=9003))
        assert state.get_order(9001) is not None
        assert state.get_order(9002) is not None
        assert state.get_order(9003) is not None
