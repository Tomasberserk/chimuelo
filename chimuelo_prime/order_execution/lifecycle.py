"""Seguimiento del ciclo de vida de órdenes existentes en Binance (M4).

OrderLifecycleManager sincroniza el estado de órdenes entre M3 (DB local) y
Binance. No coloca ni cancela órdenes — eso es OrderExecutor.

Responsabilidades:
    - sync_order_status:     consulta GET /api/v3/order y actualiza M3 si cambió.
    - sync_all_open_orders:  sincroniza todas las órdenes abiertas de un símbolo.
    - handle_fill_event:     registra un fill recibido externamente (ej. WebSocket futuro).

NO conoce:
    - Lógica de colocación o cancelación → OrderExecutor.
    - Estrategia del grid (niveles, ciclos) → M5.
    - Rate limiting → M2.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from chimuelo_prime.api_client.client import BinanceAuthenticatedClient
from chimuelo_prime.api_client.exceptions import BinanceAPIError
from chimuelo_prime.exchange_config.logger import get_logger
from chimuelo_prime.grid_state.exceptions import OrderNotFoundError
from chimuelo_prime.grid_state.grid_state import GridState
from chimuelo_prime.grid_state.schema import OrderStatus
from chimuelo_prime.order_execution.exceptions import StatusSyncError
from chimuelo_prime.order_execution.models import OrderStatusUpdate
from chimuelo_prime.shared.constants import WEIGHT_QUERY_ORDER


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class OrderLifecycleManager:
    """Sincroniza el estado de órdenes entre M3 y Binance.

    Args:
        client:     Cliente HTTP autenticado de M2.
        grid_state: Servicio de persistencia de M3.
    """

    def __init__(
        self,
        client: BinanceAuthenticatedClient,
        grid_state: GridState,
    ) -> None:
        self._client = client
        self._grid_state = grid_state
        self._log = get_logger(__name__)

    def sync_order_status(self, order_id: int, symbol: str) -> OrderStatusUpdate:
        """Sincroniza el estado de una orden con Binance.

        Consulta M3 para el estado local y Binance via GET /api/v3/order para
        el estado actual. Si difieren, actualiza M3.

        Args:
            order_id: Binance orderId.
            symbol:   Par de trading.

        Returns:
            OrderStatusUpdate con la transición observada.
            status_changed=False si el estado no varió.

        Raises:
            StatusSyncError:    si Binance retorna error al consultar la orden.
            OrderNotFoundError: si la orden no existe en M3.
        """
        local_order = self._grid_state.get_order(order_id)
        if local_order is None:
            raise OrderNotFoundError(f"Orden {order_id} no encontrada en M3.")

        previous_status = OrderStatus(local_order.status)

        try:
            response: dict[str, Any] = self._client.get(
                "/api/v3/order",
                params={"symbol": symbol, "orderId": order_id},
                weight=WEIGHT_QUERY_ORDER,
            )
        except BinanceAPIError as exc:
            raise StatusSyncError(f"Error al consultar orden {order_id} en Binance: {exc}") from exc

        current_status = OrderStatus(response["status"])
        executed_qty = Decimal(str(response["executedQty"]))
        status_changed = previous_status != current_status

        if status_changed:
            self._grid_state.update_order_status(order_id, current_status.value)
            self._log.info(
                "lifecycle.status_changed",
                order_id=order_id,
                symbol=symbol,
                previous=previous_status.value,
                current=current_status.value,
            )

        return OrderStatusUpdate(
            order_id=order_id,
            symbol=symbol,
            previous_status=previous_status,
            current_status=current_status,
            executed_qty=executed_qty,
            synced_at=_utcnow(),
            status_changed=status_changed,
        )

    def sync_all_open_orders(self, symbol: str) -> list[OrderStatusUpdate]:
        """Sincroniza todas las órdenes abiertas (NEW, PARTIALLY_FILLED) de un símbolo.

        Itera sobre grid_state.get_open_orders(symbol) y llama sync_order_status
        por cada una. Si alguna sincronización falla, la excepción se propaga.

        Returns:
            Lista de OrderStatusUpdate en el mismo orden que get_open_orders.
        """
        open_orders = self._grid_state.get_open_orders(symbol)
        return [self.sync_order_status(o.order_id, symbol) for o in open_orders]

    def handle_fill_event(
        self,
        order_id: int,
        symbol: str,
        filled_qty: Decimal,
        fill_price: Decimal,
    ) -> OrderStatusUpdate:
        """Registra un evento de fill recibido externamente (ej. WebSocket).

        Marca la orden como FILLED en M3 y retorna la transición.
        M5 usa el resultado para decidir si colocar la orden complementaria.

        Args:
            order_id:   Binance orderId.
            symbol:     Par de trading.
            filled_qty: Cantidad ejecutada reportada por el evento.
            fill_price: Precio de ejecución reportado (no se persiste; es para el log).

        Returns:
            OrderStatusUpdate con previous_status → FILLED.

        Raises:
            OrderNotFoundError: si la orden no existe en M3.
        """
        local_order = self._grid_state.get_order(order_id)
        if local_order is None:
            raise OrderNotFoundError(f"Orden {order_id} no encontrada en M3.")

        previous_status = OrderStatus(local_order.status)

        if previous_status == OrderStatus.FILLED:
            self._log.warning(
                "lifecycle.fill_event_duplicate",
                order_id=order_id,
                symbol=symbol,
                note="orden ya estaba FILLED — reentrega de evento ignorada",
            )
            return OrderStatusUpdate(
                order_id=order_id,
                symbol=symbol,
                previous_status=previous_status,
                current_status=OrderStatus.FILLED,
                executed_qty=filled_qty,
                synced_at=_utcnow(),
                status_changed=False,
            )

        self._grid_state.update_order_status(order_id, OrderStatus.FILLED.value)
        self._log.info(
            "lifecycle.fill_event",
            order_id=order_id,
            symbol=symbol,
            filled_qty=str(filled_qty),
            fill_price=str(fill_price),
        )

        return OrderStatusUpdate(
            order_id=order_id,
            symbol=symbol,
            previous_status=previous_status,
            current_status=OrderStatus.FILLED,
            executed_qty=filled_qty,
            synced_at=_utcnow(),
            status_changed=True,
        )
