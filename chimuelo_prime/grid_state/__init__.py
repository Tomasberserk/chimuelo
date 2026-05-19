"""Exports públicos del módulo grid_state (M3).

API pública:
    GridState          — servicio de persistencia del grid (CRUD en SQLite).
    Reconciler         — reconciliación con órdenes activas en Binance.
    ReconciliationResult — resultado de una reconciliación.
    build_engine       — factory para el Engine SQLite con WAL + FKs.

Modelos ORM (para construir instancias en M4/M5):
    Order      — orden colocada en Binance.
    GridLevel  — nivel del grid (rango de precio + órdenes asociadas).
    Snapshot   — instantánea de portfolio.

Excepciones:
    GridStateError         — raíz de errores de M3.
    DatabaseError          — fallo irrecuperable de SQLite.
    OrderNotFoundError     — orden no existe en DB local.
    GridLevelNotFoundError — nivel de grid no existe en DB local.
    ReconciliationError    — fallo durante reconciliación.
"""

from chimuelo_prime.grid_state.database import build_engine
from chimuelo_prime.grid_state.exceptions import (
    DatabaseError,
    GridLevelNotFoundError,
    GridStateError,
    OrderNotFoundError,
    ReconciliationError,
)
from chimuelo_prime.grid_state.grid_state import GridState
from chimuelo_prime.grid_state.reconciler import Reconciler, ReconciliationResult
from chimuelo_prime.grid_state.schema import GridLevel, Order, OrderStatus, Snapshot

__all__ = [
    # Servicios
    "GridState",
    "Reconciler",
    "ReconciliationResult",
    "build_engine",
    # Modelos ORM
    "Order",
    "GridLevel",
    "Snapshot",
    "OrderStatus",
    # Excepciones
    "GridStateError",
    "DatabaseError",
    "OrderNotFoundError",
    "GridLevelNotFoundError",
    "ReconciliationError",
]
