"""Tests para build_engine y configuración de pragmas SQLite (database.py).

Cubre:
    - build_engine(:memory:) crea las tres tablas.
    - build_engine es idempotente (llamar dos veces no duplica tablas).
    - PRAGMA foreign_keys=ON activo en conexiones en memoria.
    - PRAGMA journal_mode=WAL activo en DB de archivo.
    - FK constraint enforceado: insertar GridLevel con buy_order_id inexistente falla.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from chimuelo_prime.grid_state.database import build_engine
from chimuelo_prime.grid_state.schema import GridLevel, Order


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# --------------------------------------------------------------------------- #
# build_engine — memoria
# --------------------------------------------------------------------------- #
class TestBuildEngineMemory:
    def test_returns_engine(self) -> None:
        engine = build_engine("sqlite:///:memory:")
        assert engine is not None

    def test_creates_orders_table(self) -> None:
        from sqlalchemy import inspect

        engine = build_engine("sqlite:///:memory:")
        assert "orders" in inspect(engine).get_table_names()

    def test_creates_grid_levels_table(self) -> None:
        from sqlalchemy import inspect

        engine = build_engine("sqlite:///:memory:")
        assert "grid_levels" in inspect(engine).get_table_names()

    def test_creates_snapshots_table(self) -> None:
        from sqlalchemy import inspect

        engine = build_engine("sqlite:///:memory:")
        assert "snapshots" in inspect(engine).get_table_names()

    def test_idempotent_second_call(self) -> None:
        from sqlalchemy import inspect

        engine = build_engine("sqlite:///:memory:")
        # Segunda llamada sobre el mismo engine (create_all es idempotente)
        from chimuelo_prime.grid_state.schema import Base

        Base.metadata.create_all(engine)
        assert len(inspect(engine).get_table_names()) == 4
        assert "paper_trades" in inspect(engine).get_table_names()

    def test_foreign_keys_enabled(self) -> None:
        engine = build_engine("sqlite:///:memory:")
        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA foreign_keys"))
            value = result.scalar()
        assert value == 1


# --------------------------------------------------------------------------- #
# build_engine — archivo (WAL mode)
# --------------------------------------------------------------------------- #
class TestBuildEngineFile:
    def test_wal_mode_enabled(self, tmp_path: pytest.TempdirFactory) -> None:
        db_file = os.path.join(str(tmp_path), "test.db")
        engine = build_engine(f"sqlite:///{db_file}")
        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA journal_mode"))
            mode = result.scalar()
        engine.dispose()
        assert mode == "wal"

    def test_creates_db_file(self, tmp_path: pytest.TempdirFactory) -> None:
        db_file = os.path.join(str(tmp_path), "chimuelo_test.db")
        assert not os.path.exists(db_file)
        engine = build_engine(f"sqlite:///{db_file}")
        engine.dispose()
        assert os.path.exists(db_file)


# --------------------------------------------------------------------------- #
# FK constraint enforcement
# --------------------------------------------------------------------------- #
class TestForeignKeyConstraint:
    def test_fk_violation_raises_integrity_error(self) -> None:
        engine = build_engine("sqlite:///:memory:")
        now = _utcnow()
        # Insertar GridLevel con buy_order_id que no existe en orders
        level = GridLevel(
            symbol="SOLUSDT",
            lower_price=Decimal("100"),
            upper_price=Decimal("110"),
            buy_order_id=99999,  # FK violation — order 99999 no existe
            created_at=now,
        )
        with pytest.raises(IntegrityError), Session(engine) as session:
            session.add(level)
            session.commit()

    def test_valid_fk_reference_succeeds(self) -> None:
        engine = build_engine("sqlite:///:memory:")
        now = _utcnow()
        order = Order(
            order_id=1001,
            symbol="SOLUSDT",
            side="BUY",
            price=Decimal("100"),
            qty=Decimal("1"),
            status="NEW",
            created_at=now,
            updated_at=now,
        )
        # INSERT order primero (satisface FK antes de insertar el nivel)
        with Session(engine) as session:
            session.add(order)
            session.commit()

        level = GridLevel(
            symbol="SOLUSDT",
            lower_price=Decimal("100"),
            upper_price=Decimal("110"),
            buy_order_id=1001,  # FK válida — order ya existe
            created_at=now,
        )
        with Session(engine) as session:
            session.add(level)
            session.commit()

        with Session(engine) as session:
            saved = session.get(GridLevel, 1)
            assert saved is not None
            assert saved.buy_order_id == 1001
