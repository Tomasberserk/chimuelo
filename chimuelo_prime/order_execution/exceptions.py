"""Excepciones tipificadas del módulo order_execution (M4).

Jerarquía:
    ChimueloException (M1 — raíz del proyecto)
    └── OrderExecutionError
        ├── OrderPlacementError
        │   ├── FilterViolationError       # pre-validación local via M1; no llega a Binance
        │   ├── InsufficientBalanceError   # Binance -2021
        │   ├── DuplicateOrderError        # Binance -2010 (no recuperable)
        │   └── OrderRejectedError         # Binance -1013 (filtro server-side)
        ├── OrderCancellationError
        │   ├── OrderNotCancelableError    # Binance -2011; expone actual_status
        │   └── AggregateCancellationError # cancel_all_open_orders con fallos parciales
        ├── LifecycleError
        │   └── StatusSyncError            # fallo en GET /api/v3/order durante sync
        └── PayloadBuildError              # error de construcción de payload pre-red

Regla: M5 captura por tipo, nunca `except Exception` genérico.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from chimuelo_prime.exchange_config.exceptions import ChimueloException
from chimuelo_prime.grid_state.schema import OrderStatus

if TYPE_CHECKING:
    from chimuelo_prime.order_execution.models import CancelResult


class OrderExecutionError(ChimueloException):
    """Raíz de todas las excepciones de M4."""


# --------------------------------------------------------------------------- #
# Placement
# --------------------------------------------------------------------------- #
class OrderPlacementError(OrderExecutionError):
    """Fallo al intentar colocar una orden en Binance."""

    def __init__(self, message: str, binance_code: int | None = None) -> None:
        super().__init__(message)
        self.binance_code = binance_code


class FilterViolationError(OrderPlacementError):
    """El precio, cantidad o notional no pasaron validación de M1.

    Se lanza ANTES de llamar a Binance — el error es local, sin tráfico de red.
    `binance_code` es None en este caso.
    """


class InsufficientBalanceError(OrderPlacementError):
    """Saldo insuficiente para cubrir la orden.

    Binance code: -2021.
    La orden NUNCA fue creada en Binance. M3 no debe actualizarse.
    """

    BINANCE_CODE: int = -2021


class DuplicateOrderError(OrderPlacementError):
    """clientOrderId ya existe en Binance y la orden no pudo recuperarse.

    Binance code: -2010.
    El ejecutor intentó GET /api/v3/order y no encontró la orden.
    Si la hubiese encontrado, habría retornado PlacedOrder sin lanzar esta excepción.
    """

    BINANCE_CODE: int = -2010


class OrderRejectedError(OrderPlacementError):
    """Binance rechazó la orden por violación de filtro detectada server-side.

    Binance code: -1013.
    Si M1 (SymbolFilters) funciona correctamente, esto NO debería ocurrir.
    Su presencia indica desincronización entre SymbolFilters y los filtros reales.
    """

    BINANCE_CODE: int = -1013


# --------------------------------------------------------------------------- #
# Cancellation
# --------------------------------------------------------------------------- #
class OrderCancellationError(OrderExecutionError):
    """Fallo al intentar cancelar una orden en Binance."""


class OrderNotCancelableError(OrderCancellationError):
    """La orden no puede cancelarse: no existe o ya está en estado final.

    Binance code: -2011.
    El ejecutor consulta GET /api/v3/order antes de lanzar esta excepción
    para determinar el estado real y exponerlo en `actual_status`.

    M5 inspecciona `actual_status` para decidir si colocar la orden
    complementaria (ej. si actual_status=FILLED, el ciclo de compra se completó).
    """

    BINANCE_CODE: int = -2011

    def __init__(self, message: str, actual_status: OrderStatus | None = None) -> None:
        super().__init__(message)
        self.actual_status = actual_status


class AggregateCancellationError(OrderCancellationError):
    """Una o más cancelaciones fallaron durante cancel_all_open_orders.

    Permite a M5 inspeccionar qué órdenes se cancelaron exitosamente
    (partial_results) y qué órdenes fallaron (errors), y decidir cómo
    reintentar o manejar las posiciones residuales.

    Attributes:
        partial_results: CancelResult de las órdenes canceladas exitosamente.
        errors:          Lista de (order_id, excepción) para las que fallaron.
    """

    def __init__(
        self,
        message: str,
        partial_results: list[CancelResult],
        errors: list[tuple[int, Exception]],
    ) -> None:
        super().__init__(message)
        self.partial_results = partial_results
        self.errors = errors


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #
class LifecycleError(OrderExecutionError):
    """Fallo en operaciones de seguimiento del ciclo de vida de órdenes."""


class StatusSyncError(LifecycleError):
    """Fallo al sincronizar el estado de una orden con Binance via GET /api/v3/order."""


# --------------------------------------------------------------------------- #
# Payload
# --------------------------------------------------------------------------- #
class PayloadBuildError(OrderExecutionError):
    """Fallo al construir el payload antes de llamar a Binance.

    Indica un error de programación (dato faltante, tipo incorrecto),
    no un error de red ni de exchange.
    """
