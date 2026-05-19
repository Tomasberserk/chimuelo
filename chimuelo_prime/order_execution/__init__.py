"""Exports públicos del módulo order_execution (M4).

API pública:
    OrderExecutor          — coloca y cancela órdenes en Binance.
    OrderLifecycleManager  — sincroniza estado de órdenes con Binance.

Modelos:
    PlacedOrder       — resultado de colocar una orden.
    CancelResult      — resultado de cancelar una orden.
    OrderStatusUpdate — resultado de una sincronización de estado.

Excepciones:
    OrderExecutionError        — raíz de errores de M4.
    OrderPlacementError        — fallo al colocar.
    FilterViolationError       — filtro M1 no pasado (pre-red).
    InsufficientBalanceError   — saldo insuficiente (-2021).
    DuplicateOrderError        — clientOrderId duplicado no recuperable (-2010).
    OrderRejectedError         — filtro server-side de Binance (-1013).
    OrderCancellationError     — fallo al cancelar.
    OrderNotCancelableError    — orden no cancelable (-2011); ver actual_status.
    AggregateCancellationError — fallos parciales en cancel_all_open_orders.
    LifecycleError             — fallo en seguimiento de ciclo de vida.
    StatusSyncError            — fallo al sincronizar estado.
    PayloadBuildError          — error de construcción de payload.

NO se exporta nada de _internal/.
"""

from chimuelo_prime.order_execution.exceptions import (
    AggregateCancellationError,
    DuplicateOrderError,
    FilterViolationError,
    InsufficientBalanceError,
    LifecycleError,
    OrderCancellationError,
    OrderExecutionError,
    OrderNotCancelableError,
    OrderPlacementError,
    OrderRejectedError,
    PayloadBuildError,
    StatusSyncError,
)
from chimuelo_prime.order_execution.executor import OrderExecutor
from chimuelo_prime.order_execution.lifecycle import OrderLifecycleManager
from chimuelo_prime.order_execution.models import (
    CancelResult,
    OrderStatusUpdate,
    PlacedOrder,
)

__all__ = [
    # Servicios
    "OrderExecutor",
    "OrderLifecycleManager",
    # Modelos
    "PlacedOrder",
    "CancelResult",
    "OrderStatusUpdate",
    # Excepciones
    "OrderExecutionError",
    "OrderPlacementError",
    "FilterViolationError",
    "InsufficientBalanceError",
    "DuplicateOrderError",
    "OrderRejectedError",
    "OrderCancellationError",
    "OrderNotCancelableError",
    "AggregateCancellationError",
    "LifecycleError",
    "StatusSyncError",
    "PayloadBuildError",
]
