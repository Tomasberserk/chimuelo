"""Servicio de lectura/escritura del estado persistente del grid (M3).

GridState encapsula toda la lógica de acceso a la base de datos SQLite.
Módulos downstream (M4, M5) usan esta clase — nunca abren sesiones directamente.

Responsabilidades:
    - CRUD de órdenes (save, get, status update).
    - CRUD de niveles de grid (create, get, link orders).
    - CRUD de snapshots de portfolio.

Transacciones:
    Cada método abre su propia sesión y hace commit atómicamente.
    Si ocurre una excepción antes del commit, SQLAlchemy hace rollback automático
    al salir del bloque `with Session() as session`.

NO conoce:
    - Lógica de grid (niveles, distribución de capital) → M5.
    - Ejecución de órdenes en Binance → M4.
    - Reconciliación con Binance → Reconciler.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from chimuelo_prime.exchange_config.logger import get_logger
from chimuelo_prime.grid_state.exceptions import GridLevelNotFoundError, OrderNotFoundError
from chimuelo_prime.grid_state.schema import GridLevel, Order, Snapshot

# Statuses que Binance incluye en /api/v3/openOrders (órdenes activas)
_OPEN_STATUSES = {"NEW", "PARTIALLY_FILLED"}


def _utcnow() -> datetime:
    """Timestamp UTC-naive para columnas DateTime de SQLite."""
    return datetime.now(UTC).replace(tzinfo=None)


class GridState:
    """Acceso transaccional al estado persistente del grid en SQLite.

    Args:
        engine: SQLAlchemy Engine inicializado con build_engine().
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._log = get_logger(__name__)

    # ------------------------------------------------------------------ #
    # Órdenes
    # ------------------------------------------------------------------ #
    def save_order(self, order: Order) -> None:
        """Persiste una orden nueva o actualiza una existente (upsert).

        Usa session.merge() para INSERT OR UPDATE basado en order_id (PK).
        """
        order_id = order.order_id
        with Session(self._engine) as session:
            session.merge(order)
            session.commit()
        self._log.debug("grid_state.order_saved", order_id=order_id)

    def get_order(self, order_id: int) -> Order | None:
        """Retorna la orden con ese Binance order_id, o None si no existe."""
        with Session(self._engine) as session:
            return session.get(Order, order_id)

    def get_open_orders(self, symbol: str) -> list[Order]:
        """Retorna todas las órdenes activas (NEW, PARTIALLY_FILLED) del símbolo."""
        with Session(self._engine) as session:
            rows = session.scalars(
                select(Order).where(
                    Order.symbol == symbol,
                    Order.status.in_(_OPEN_STATUSES),
                )
            ).all()
            return list(rows)

    def update_order_status(self, order_id: int, status: str) -> None:
        """Actualiza el status de una orden existente.

        Raises:
            OrderNotFoundError: si order_id no existe en la DB.
        """
        with Session(self._engine) as session:
            order = session.get(Order, order_id)
            if order is None:
                raise OrderNotFoundError(f"Orden {order_id} no encontrada en DB.")
            order.status = status
            order.updated_at = _utcnow()
            session.commit()
        self._log.info("grid_state.order_status_updated", order_id=order_id, status=status)

    def bulk_update_order_statuses(self, updates: dict[int, str]) -> None:
        """Actualiza el status de múltiples órdenes en una sola transacción atómica.

        Todos los cambios se aplican juntos o ninguno. Si falla cualquier
        actualización (orden no encontrada), se hace rollback completo y
        la DB queda en el estado previo a la llamada.

        Args:
            updates: {order_id: new_status}. Vacío es noop sin abrir sesión.

        Raises:
            OrderNotFoundError: si algún order_id no existe en la DB.
        """
        if not updates:
            return
        with Session(self._engine) as session:
            for order_id, status in updates.items():
                order = session.get(Order, order_id)
                if order is None:
                    raise OrderNotFoundError(f"Orden {order_id} no encontrada en DB.")
                order.status = status
                order.updated_at = _utcnow()
            session.commit()
        for order_id, status in updates.items():
            self._log.info("grid_state.order_status_updated", order_id=order_id, status=status)

    # ------------------------------------------------------------------ #
    # Niveles de grid
    # ------------------------------------------------------------------ #
    def save_grid_level(self, level: GridLevel) -> int:
        """Persiste un nuevo nivel de grid y retorna su level_id asignado.

        Returns:
            level_id asignado por SQLite (autoincrement).
        """
        with Session(self._engine) as session:
            session.add(level)
            session.flush()
            level_id: int = level.level_id
            session.commit()
        self._log.debug("grid_state.level_saved", level_id=level_id)
        return level_id

    def get_grid_levels(self, symbol: str) -> list[GridLevel]:
        """Retorna todos los niveles del grid para el símbolo, ordenados por lower_price."""
        with Session(self._engine) as session:
            rows = session.scalars(
                select(GridLevel).where(GridLevel.symbol == symbol).order_by(GridLevel.lower_price)
            ).all()
            return list(rows)

    def get_grid_level(self, level_id: int) -> GridLevel | None:
        """Retorna el nivel con ese level_id, o None si no existe."""
        with Session(self._engine) as session:
            return session.get(GridLevel, level_id)

    def update_level_buy_order(self, level_id: int, order_id: int) -> None:
        """Asocia una orden de compra a un nivel.

        Raises:
            GridLevelNotFoundError: si level_id no existe.
        """
        with Session(self._engine) as session:
            level = session.get(GridLevel, level_id)
            if level is None:
                raise GridLevelNotFoundError(f"Nivel {level_id} no encontrado en DB.")
            level.buy_order_id = order_id
            session.commit()

    def update_level_sell_order(self, level_id: int, order_id: int) -> None:
        """Asocia una orden de venta a un nivel.

        Raises:
            GridLevelNotFoundError: si level_id no existe.
        """
        with Session(self._engine) as session:
            level = session.get(GridLevel, level_id)
            if level is None:
                raise GridLevelNotFoundError(f"Nivel {level_id} no encontrado en DB.")
            level.sell_order_id = order_id
            session.commit()

    # ------------------------------------------------------------------ #
    # Snapshots
    # ------------------------------------------------------------------ #
    def save_snapshot(self, snapshot: Snapshot) -> None:
        """Persiste una instantánea de portfolio."""
        symbol = snapshot.symbol
        with Session(self._engine) as session:
            session.add(snapshot)
            session.commit()
        self._log.debug("grid_state.snapshot_saved", symbol=symbol)

    def get_latest_snapshot(self, symbol: str) -> Snapshot | None:
        """Retorna el snapshot más reciente del símbolo, o None si no hay ninguno."""
        with Session(self._engine) as session:
            return session.scalars(
                select(Snapshot)
                .where(Snapshot.symbol == symbol)
                .order_by(Snapshot.created_at.desc())
                .limit(1)
            ).first()
