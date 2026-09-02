"""Modelos SQLAlchemy 2.x para el estado persistente del grid (M3).

Tablas:
    orders       — órdenes colocadas en Binance (una por fila, PK = Binance order_id).
    grid_levels  — niveles del grid (lower/upper price + órdenes asociadas).
    snapshots    — instantáneas de portfolio (equity, inventory, cash).

Convenciones:
    - Precios y cantidades: Numeric(20, 8) — cubre todos los pares de Binance.
    - Timestamps: DateTime UTC-naive (siempre guardar con datetime.now(UTC).replace(tzinfo=None)).
    - FKs: GridLevel → Order (buy_order_id, sell_order_id). Sin circulares.
    - Order.order_id es el Binance order_id (externo, no autoincrement).
    - GridLevel.level_id y Snapshot.snapshot_id son autoincrement internos.
"""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class OrderStatus(str, enum.Enum):
    """Ciclo de vida de una orden en Binance.

    Single Source of Truth para estados de orden del proyecto.
    Importar desde aquí en M4, M5, M7 — nunca redefinir.
    """

    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


class Base(DeclarativeBase):
    """Base declarativa compartida por todos los modelos de M3."""


class Order(Base):
    """Orden colocada en Binance.

    PK = order_id de Binance (externo, asignado por la exchange).
    status sigue el ciclo de vida: NEW → PARTIALLY_FILLED → FILLED / CANCELED / EXPIRED.
    """

    __tablename__ = "orders"

    order_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(precision=20, scale=8), nullable=False)
    qty: Mapped[Decimal] = mapped_column(Numeric(precision=20, scale=8), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    def __repr__(self) -> str:
        return (
            f"Order(order_id={self.order_id}, symbol={self.symbol!r}, "
            f"side={self.side!r}, status={self.status!r})"
        )


class GridLevel(Base):
    """Nivel del grid: rango de precio + órdenes asociadas.

    level_id: asignado por SQLite (autoincrement).
    buy_order_id: FK a la orden de compra colocada en este nivel (nullable hasta que se coloca).
    sell_order_id: FK a la orden de venta colocada cuando el buy se ejecuta (nullable).
    """

    __tablename__ = "grid_levels"

    level_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    lower_price: Mapped[Decimal] = mapped_column(Numeric(precision=20, scale=8), nullable=False)
    upper_price: Mapped[Decimal] = mapped_column(Numeric(precision=20, scale=8), nullable=False)
    buy_order_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("orders.order_id"),
        nullable=True,
    )
    sell_order_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("orders.order_id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    def __repr__(self) -> str:
        return (
            f"GridLevel(level_id={self.level_id}, symbol={self.symbol!r}, "
            f"lower={self.lower_price}, upper={self.upper_price})"
        )


class Snapshot(Base):
    """Instantánea de portfolio en un momento dado.

    Registra equity total, inventario de base asset y cash disponible.
    Se persiste periódicamente para análisis y auditoría.
    """

    __tablename__ = "snapshots"

    snapshot_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    equity: Mapped[Decimal] = mapped_column(Numeric(precision=20, scale=8), nullable=False)
    inventory: Mapped[Decimal] = mapped_column(Numeric(precision=20, scale=8), nullable=False)
    cash: Mapped[Decimal] = mapped_column(Numeric(precision=20, scale=8), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    def __repr__(self) -> str:
        return (
            f"Snapshot(snapshot_id={self.snapshot_id}, symbol={self.symbol!r}, "
            f"equity={self.equity})"
        )


class PaperTradeRecord(Base):
    """Registro persistente en SQLite de una operación cerrada de Paper Trading."""

    __tablename__ = "paper_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_id: Mapped[int] = mapped_column(Integer, nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(10), default="BUY", nullable=False)
    entry_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    exit_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(precision=20, scale=8), nullable=False)
    exit_price: Mapped[Decimal] = mapped_column(Numeric(precision=20, scale=8), nullable=False)
    qty: Mapped[Decimal] = mapped_column(Numeric(precision=20, scale=8), nullable=False)
    notional: Mapped[Decimal] = mapped_column(Numeric(precision=20, scale=8), nullable=False)
    stop_loss: Mapped[Decimal] = mapped_column(Numeric(precision=20, scale=8), nullable=False)
    take_profit: Mapped[Decimal] = mapped_column(Numeric(precision=20, scale=8), nullable=False)
    gross_pnl: Mapped[Decimal] = mapped_column(Numeric(precision=20, scale=8), nullable=False)
    total_fees: Mapped[Decimal] = mapped_column(Numeric(precision=20, scale=8), nullable=False)
    net_pnl: Mapped[Decimal] = mapped_column(Numeric(precision=20, scale=8), nullable=False)
    net_pnl_pct: Mapped[Decimal] = mapped_column(Numeric(precision=20, scale=8), nullable=False)
    exit_reason: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    def __repr__(self) -> str:
        return (
            f"PaperTradeRecord(id={self.id}, trade_id={self.trade_id}, symbol={self.symbol!r}, "
            f"net_pnl={self.net_pnl}, exit_reason={self.exit_reason!r})"
        )

