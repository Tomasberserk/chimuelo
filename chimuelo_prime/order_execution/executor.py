"""Colocación y cancelación de órdenes en Binance (M4).

OrderExecutor es el único punto de entrada para M5 cuando quiere:
    - Colocar una orden LIMIT BUY o SELL.
    - Cancelar una orden individual o todas las abiertas de un símbolo.

Flujo de colocación (place_limit_buy / place_limit_sell):
    1. Validación pre-vuelo via M1 (filtros) — sin red.
    2. Llamada a Binance via M2 (client.post).
    3. Persistencia en M3 (save_order + update_level_*_order).

Atomicidad:
    Entre el paso 2 y el paso 3 existe una ventana donde la orden existe en
    Binance pero no en M3. Si el proceso muere en esa ventana, M3.Reconciler
    resolverá la inconsistencia en el próximo ciclo de arranque de M5.
    El fallo en paso 3 emite log CRITICAL y relanza — nunca se silencia.

NO conoce:
    - Cuándo colocar órdenes → M5.
    - En qué precio colocar → M5 + M1.
    - Reconciliación de estado → M3.Reconciler.
    - Rate limiting y retry → M2.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from chimuelo_prime.api_client.client import BinanceAuthenticatedClient
from chimuelo_prime.api_client.exceptions import BinanceAPIError
from chimuelo_prime.exchange_config.exceptions import FilterValidationError
from chimuelo_prime.exchange_config.logger import get_logger
from chimuelo_prime.exchange_config.models import SymbolConfig
from chimuelo_prime.grid_state.grid_state import GridState
from chimuelo_prime.grid_state.schema import Order, OrderStatus
from chimuelo_prime.order_execution._internal.payload_builder import (
    build_cancel_payload,
    build_limit_order_payload,
)
from chimuelo_prime.order_execution.exceptions import (
    AggregateCancellationError,
    DuplicateOrderError,
    FilterViolationError,
    InsufficientBalanceError,
    OrderCancellationError,
    OrderNotCancelableError,
    OrderPlacementError,
    OrderRejectedError,
)
from chimuelo_prime.order_execution.models import CancelResult, PlacedOrder
from chimuelo_prime.shared.constants import (
    WEIGHT_CANCEL_ORDER,
    WEIGHT_PLACE_ORDER,
    WEIGHT_QUERY_ORDER,
)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _ms_to_datetime(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).replace(tzinfo=None)


class OrderExecutor:
    """Coloca y cancela órdenes en Binance, persistiendo cada resultado en M3.

    Todas las dependencias se inyectan — nunca se instancian internamente.
    Un único SymbolConfig por instancia: si M5 opera con múltiples símbolos,
    crea una instancia de OrderExecutor por símbolo.

    Args:
        client:     Cliente HTTP autenticado de M2.
        grid_state: Servicio de persistencia de M3.
        config:     Configuración del símbolo (filtros + parámetros de estrategia).
    """

    def __init__(
        self,
        client: BinanceAuthenticatedClient,
        grid_state: GridState,
        config: SymbolConfig,
    ) -> None:
        self._client = client
        self._grid_state = grid_state
        self._config = config
        self._log = get_logger(__name__)

    # ------------------------------------------------------------------ #
    # API pública
    # ------------------------------------------------------------------ #
    def place_limit_buy(
        self,
        price: Decimal,
        qty: Decimal,
        level_id: int,
        client_order_id: str | None = None,
    ) -> PlacedOrder:
        """Coloca una orden LIMIT BUY en Binance y la persiste en M3.

        Atomicidad: si Binance acepta la orden pero la escritura en M3 falla,
        se emite log CRITICAL y se relanza DatabaseError. M3.Reconciler
        recuperará la consistencia en el próximo arranque.

        Args:
            price:           Precio límite (se redondea al tick_size antes de enviar).
            qty:             Cantidad (se redondea al step_size antes de enviar).
            level_id:        ID del nivel de grid que origina esta orden.
            client_order_id: ID de orden clienta opcional; si None, Binance lo genera.

        Returns:
            PlacedOrder con los datos confirmados por Binance.

        Raises:
            FilterViolationError:     precio/cantidad/notional no pasan filtros de M1.
            InsufficientBalanceError: Binance rechazó por saldo insuficiente (-2021).
            DuplicateOrderError:      clientOrderId duplicado y no recuperable (-2010).
            OrderRejectedError:       Binance rechazó por filtro server-side (-1013).
            OrderPlacementError:      cualquier otro error de Binance al colocar.
            DatabaseError:            la orden llegó a Binance pero M3 falló al persistir.
        """
        return self._place_limit_order("BUY", price, qty, level_id, client_order_id)

    def place_limit_sell(
        self,
        price: Decimal,
        qty: Decimal,
        level_id: int,
        client_order_id: str | None = None,
    ) -> PlacedOrder:
        """Coloca una orden LIMIT SELL en Binance y la persiste en M3.

        Mismas garantías y excepciones que place_limit_buy.
        """
        return self._place_limit_order("SELL", price, qty, level_id, client_order_id)

    def cancel_order(self, order_id: int, symbol: str) -> CancelResult:
        """Cancela una orden en Binance y actualiza su estado en M3.

        Si Binance retorna -2011 (orden no cancelable), consulta el estado
        real via GET /api/v3/order y lo expone en OrderNotCancelableError.actual_status.
        Si el estado real es FILLED, actualiza M3 antes de lanzar la excepción.

        Args:
            order_id: Binance orderId a cancelar.
            symbol:   Par de trading.

        Returns:
            CancelResult con el estado final confirmado por Binance.

        Raises:
            OrderNotCancelableError: orden no cancelable; inspeccionar actual_status.
            OrderCancellationError:  otro error de Binance al cancelar.
        """
        payload = build_cancel_payload(symbol, order_id)
        try:
            response = self._client.delete(
                "/api/v3/order", params=payload, weight=WEIGHT_CANCEL_ORDER
            )
        except BinanceAPIError as exc:
            if exc.binance_code == -2011:
                actual_status = self._fetch_actual_status(order_id, symbol)
                if actual_status == OrderStatus.FILLED:
                    self._grid_state.update_order_status(order_id, OrderStatus.FILLED.value)
                    self._log.info(
                        "cancel.discovered_fill",
                        order_id=order_id,
                        symbol=symbol,
                    )
                raise OrderNotCancelableError(str(exc), actual_status=actual_status) from exc
            raise OrderCancellationError(str(exc)) from exc

        result = self._parse_cancel_result(response)
        self._grid_state.update_order_status(order_id, result.status.value)
        self._log.info(
            "order_canceled",
            order_id=order_id,
            symbol=symbol,
            executed_qty=str(result.executed_qty),
        )
        return result

    def cancel_all_open_orders(self, symbol: str) -> list[CancelResult]:
        """Cancela todas las órdenes abiertas del símbolo según M3.

        Enfoque collect-and-continue: intenta cancelar cada orden independientemente.
        Los fallos individuales se recolectan y se lanzan al final como
        AggregateCancellationError, que expone partial_results (éxitos) y errors
        (lista de tuplas order_id + excepción). Esto garantiza que un shutdown de
        emergencia intente cancelar todas las órdenes, no se detenga en la primera.

        Returns:
            Lista de CancelResult de las órdenes canceladas exitosamente.

        Raises:
            AggregateCancellationError: si una o más cancelaciones fallaron.
        """
        open_orders = self._grid_state.get_open_orders(symbol)
        results: list[CancelResult] = []
        errors: list[tuple[int, Exception]] = []

        for order in open_orders:
            try:
                results.append(self.cancel_order(order.order_id, symbol))
            except Exception as exc:
                self._log.error(
                    "cancel_all.order_failed",
                    order_id=order.order_id,
                    symbol=symbol,
                    error=str(exc),
                )
                errors.append((order.order_id, exc))

        if errors:
            raise AggregateCancellationError(
                f"{len(errors)} cancelación(es) fallaron de {len(open_orders)} abiertas.",
                partial_results=results,
                errors=errors,
            )
        return results

    # ------------------------------------------------------------------ #
    # Internos
    # ------------------------------------------------------------------ #
    def _place_limit_order(
        self,
        side: Literal["BUY", "SELL"],
        price: Decimal,
        qty: Decimal,
        level_id: int,
        client_order_id: str | None,
    ) -> PlacedOrder:
        # Paso 1: validación pre-vuelo (local, sin red)
        try:
            payload = build_limit_order_payload(self._config, side, price, qty, client_order_id)
        except FilterValidationError as exc:
            self._log.error(
                "filter_violation",
                side=side,
                price=str(price),
                qty=str(qty),
                level_id=level_id,
                error=str(exc),
            )
            raise FilterViolationError(str(exc)) from exc

        # Paso 2: llamada a Binance
        try:
            response = self._client.post(
                "/api/v3/order",
                params=payload,
                weight=WEIGHT_PLACE_ORDER,
                is_order=True,
            )
        except BinanceAPIError as exc:
            if exc.binance_code == -2021:
                self._log.error(
                    "insufficient_balance",
                    level_id=level_id,
                    binance_code=exc.binance_code,
                )
                raise InsufficientBalanceError(str(exc), binance_code=exc.binance_code) from exc

            if exc.binance_code == -2010:
                return self._recover_on_duplicate(exc, payload, level_id, side)

            if exc.binance_code == -1013:
                self._log.critical(
                    "filter_mismatch_server_side",
                    side=side,
                    price=str(price),
                    qty=str(qty),
                    binance_code=exc.binance_code,
                )
                raise OrderRejectedError(str(exc), binance_code=exc.binance_code) from exc

            raise OrderPlacementError(str(exc), binance_code=exc.binance_code) from exc

        # Paso 3: persistencia en M3
        placed = self._parse_placed_order(response, level_id)
        self._persist_placed_order(placed, level_id, side)

        self._log.info(
            "order_placed",
            order_id=placed.order_id,
            side=side,
            price=str(placed.price),
            qty=str(placed.orig_qty),
            level_id=level_id,
        )
        return placed

    def _recover_on_duplicate(
        self,
        original_exc: BinanceAPIError,
        payload: dict[str, str],
        level_id: int,
        side: Literal["BUY", "SELL"],
    ) -> PlacedOrder:
        """Intenta recuperar una orden duplicada via GET /api/v3/order.

        Si clientOrderId fue provisto, consulta Binance para ver si la orden
        ya existe (el intento anterior llegó pero M4 no recibió la confirmación).
        Si la orden existe, la persiste en M3 y retorna PlacedOrder.
        Si no (-2013), o si no había clientOrderId, lanza DuplicateOrderError.
        Cualquier otro error de Binance (rate-limit, auth, red) se propaga sin silenciar.
        """
        client_order_id = payload.get("newClientOrderId")
        if client_order_id:
            try:
                response = self._client.get(
                    "/api/v3/order",
                    params={"symbol": payload["symbol"], "origClientOrderId": client_order_id},
                    weight=WEIGHT_QUERY_ORDER,
                )
                placed = self._parse_placed_order(response, level_id)
                self._persist_placed_order(placed, level_id, side)
                self._log.warning(
                    "duplicate_order_recovered",
                    order_id=placed.order_id,
                    client_order_id=client_order_id,
                    level_id=level_id,
                )
                return placed
            except BinanceAPIError as recovery_exc:
                if recovery_exc.binance_code != -2013:
                    raise  # rate-limit, auth, red — no silenciar
                # -2013: orden genuinamente no encontrada → continuar a DuplicateOrderError

        self._log.warning(
            "duplicate_order_not_recoverable",
            client_order_id=client_order_id,
            level_id=level_id,
        )
        raise DuplicateOrderError(
            str(original_exc), binance_code=original_exc.binance_code
        ) from original_exc

    def _fetch_actual_status(self, order_id: int, symbol: str) -> OrderStatus | None:
        """Consulta el estado real de una orden en Binance. Retorna None si falla."""
        try:
            response = self._client.get(
                "/api/v3/order",
                params={"symbol": symbol, "orderId": order_id},
                weight=WEIGHT_QUERY_ORDER,
            )
            return OrderStatus(response["status"])
        except BinanceAPIError:
            return None

    def _parse_placed_order(self, response: dict[str, Any], level_id: int) -> PlacedOrder:
        transact_ms = response.get("transactTime") or response.get("time") or 0
        transact_time = _ms_to_datetime(transact_ms) if transact_ms else _utcnow()
        return PlacedOrder(
            order_id=int(response["orderId"]),
            client_order_id=str(response["clientOrderId"]),
            symbol=str(response["symbol"]),
            side=str(response["side"]),
            price=Decimal(str(response["price"])),
            orig_qty=Decimal(str(response["origQty"])),
            executed_qty=Decimal(str(response["executedQty"])),
            status=OrderStatus(response["status"]),
            level_id=level_id,
            transact_time=transact_time,
        )

    def _parse_cancel_result(self, response: dict[str, Any]) -> CancelResult:
        return CancelResult(
            order_id=int(response["orderId"]),
            symbol=str(response["symbol"]),
            status=OrderStatus(response["status"]),
            orig_qty=Decimal(str(response["origQty"])),
            executed_qty=Decimal(str(response["executedQty"])),
        )

    def _persist_placed_order(
        self, placed: PlacedOrder, level_id: int, side: Literal["BUY", "SELL"]
    ) -> None:
        order = Order(
            order_id=placed.order_id,
            symbol=placed.symbol,
            side=placed.side,
            price=placed.price,
            qty=placed.orig_qty,
            status=placed.status.value,
            created_at=placed.transact_time,
            updated_at=placed.transact_time,
        )
        try:
            self._grid_state.save_order(order)
            if side == "BUY":
                self._grid_state.update_level_buy_order(level_id, placed.order_id)
            else:
                self._grid_state.update_level_sell_order(level_id, placed.order_id)
        except Exception as exc:
            self._log.critical(
                "m3_write_failure_after_binance_success",
                order_id=placed.order_id,
                symbol=placed.symbol,
                level_id=level_id,
                error=str(exc),
            )
            raise
