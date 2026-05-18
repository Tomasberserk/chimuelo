"""Tests para los modelos ORM de M3 (schema.py).

Cubre:
    - Base.metadata crea las tres tablas esperadas.
    - Columnas obligatorias presentes con los tipos correctos.
    - FKs de GridLevel a orders definidas correctamente.
    - __repr__ de cada modelo es informativo.
    - Instanciación de objetos con campos correctos.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from chimuelo_prime.grid_state.database import build_engine
from chimuelo_prime.grid_state.schema import GridLevel, Order, Snapshot


@pytest.fixture
def engine() -> Engine:
    return build_engine("sqlite:///:memory:")


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# --------------------------------------------------------------------------- #
# Tablas creadas por Base.metadata
# --------------------------------------------------------------------------- #
class TestTablesCreated:
    def test_orders_table_exists(self, engine: Engine) -> None:
        insp = inspect(engine)
        assert "orders" in insp.get_table_names()

    def test_grid_levels_table_exists(self, engine: Engine) -> None:
        insp = inspect(engine)
        assert "grid_levels" in insp.get_table_names()

    def test_snapshots_table_exists(self, engine: Engine) -> None:
        insp = inspect(engine)
        assert "snapshots" in insp.get_table_names()

    def test_exactly_three_tables(self, engine: Engine) -> None:
        insp = inspect(engine)
        assert len(insp.get_table_names()) == 3


# --------------------------------------------------------------------------- #
# Columnas de orders
# --------------------------------------------------------------------------- #
class TestOrderColumns:
    def test_orders_has_order_id(self, engine: Engine) -> None:
        insp = inspect(engine)
        cols = {c["name"] for c in insp.get_columns("orders")}
        assert "order_id" in cols

    def test_orders_has_required_columns(self, engine: Engine) -> None:
        insp = inspect(engine)
        cols = {c["name"] for c in insp.get_columns("orders")}
        required = {
            "order_id",
            "symbol",
            "side",
            "price",
            "qty",
            "status",
            "created_at",
            "updated_at",
        }
        assert required.issubset(cols)

    def test_order_id_is_primary_key(self, engine: Engine) -> None:
        insp = inspect(engine)
        pk = insp.get_pk_constraint("orders")
        assert "order_id" in pk["constrained_columns"]


# --------------------------------------------------------------------------- #
# Columnas de grid_levels
# --------------------------------------------------------------------------- #
class TestGridLevelColumns:
    def test_grid_levels_has_level_id(self, engine: Engine) -> None:
        insp = inspect(engine)
        cols = {c["name"] for c in insp.get_columns("grid_levels")}
        assert "level_id" in cols

    def test_grid_levels_has_required_columns(self, engine: Engine) -> None:
        insp = inspect(engine)
        cols = {c["name"] for c in insp.get_columns("grid_levels")}
        required = {
            "level_id",
            "symbol",
            "lower_price",
            "upper_price",
            "buy_order_id",
            "sell_order_id",
            "created_at",
        }
        assert required.issubset(cols)

    def test_buy_order_id_nullable(self, engine: Engine) -> None:
        insp = inspect(engine)
        cols = {c["name"]: c for c in insp.get_columns("grid_levels")}
        assert cols["buy_order_id"]["nullable"] is True

    def test_sell_order_id_nullable(self, engine: Engine) -> None:
        insp = inspect(engine)
        cols = {c["name"]: c for c in insp.get_columns("grid_levels")}
        assert cols["sell_order_id"]["nullable"] is True


# --------------------------------------------------------------------------- #
# Columnas de snapshots
# --------------------------------------------------------------------------- #
class TestSnapshotColumns:
    def test_snapshots_has_required_columns(self, engine: Engine) -> None:
        insp = inspect(engine)
        cols = {c["name"] for c in insp.get_columns("snapshots")}
        required = {"snapshot_id", "symbol", "equity", "inventory", "cash", "created_at"}
        assert required.issubset(cols)


# --------------------------------------------------------------------------- #
# Instanciación de modelos ORM
# --------------------------------------------------------------------------- #
class TestModelInstantiation:
    def test_order_instantiation(self) -> None:
        now = _utcnow()
        order = Order(
            order_id=12345,
            symbol="SOLUSDT",
            side="BUY",
            price=Decimal("150.00"),
            qty=Decimal("1.5"),
            status="NEW",
            created_at=now,
            updated_at=now,
        )
        assert order.order_id == 12345
        assert order.symbol == "SOLUSDT"
        assert order.side == "BUY"
        assert order.price == Decimal("150.00")
        assert order.qty == Decimal("1.5")
        assert order.status == "NEW"

    def test_grid_level_instantiation(self) -> None:
        now = _utcnow()
        level = GridLevel(
            symbol="SOLUSDT",
            lower_price=Decimal("140.00"),
            upper_price=Decimal("150.00"),
            created_at=now,
        )
        assert level.symbol == "SOLUSDT"
        assert level.lower_price == Decimal("140.00")
        assert level.upper_price == Decimal("150.00")
        assert level.buy_order_id is None
        assert level.sell_order_id is None

    def test_snapshot_instantiation(self) -> None:
        now = _utcnow()
        snap = Snapshot(
            symbol="SOLUSDT",
            equity=Decimal("1000.00"),
            inventory=Decimal("5.0"),
            cash=Decimal("250.00"),
            created_at=now,
        )
        assert snap.symbol == "SOLUSDT"
        assert snap.equity == Decimal("1000.00")

    def test_order_repr_contains_order_id(self) -> None:
        now = _utcnow()
        order = Order(
            order_id=99,
            symbol="BTCUSDT",
            side="SELL",
            price=Decimal("50000"),
            qty=Decimal("0.001"),
            status="FILLED",
            created_at=now,
            updated_at=now,
        )
        assert "99" in repr(order)
        assert "BTCUSDT" in repr(order)

    def test_grid_level_repr_contains_prices(self) -> None:
        now = _utcnow()
        level = GridLevel(
            symbol="SOLUSDT",
            lower_price=Decimal("100"),
            upper_price=Decimal("110"),
            created_at=now,
        )
        assert "100" in repr(level)
        assert "110" in repr(level)

    def test_snapshot_repr_contains_equity(self) -> None:
        now = _utcnow()
        snap = Snapshot(
            symbol="SOLUSDT",
            equity=Decimal("500"),
            inventory=Decimal("2"),
            cash=Decimal("200"),
            created_at=now,
        )
        assert "500" in repr(snap)
