"""Reconciliación del estado local con las órdenes reales en Binance (M3).

Problema que resuelve:
    Si el bot se cae (crash, reinicio, corte de red), las órdenes en Binance
    pueden cambiar de estado (FILLED, CANCELED, EXPIRED) sin que la DB local
    lo sepa. Al reiniciar, hay que sincronizar.

Algoritmo:
    1. GET /api/v3/openOrders → set de Binance order_ids activos.
    2. Leer DB local: órdenes con status NEW o PARTIALLY_FILLED.
    3. Órdenes en local PERO no en Binance → consultar su estado real
       via GET /api/v3/order y actualizar DB (FILLED o CANCELED/EXPIRED).
    4. Órdenes en Binance PERO no en local → inesperadas (manual / otro bot).
       Se loguean, NO se insertan en la DB (M3 no toma decisiones de negocio).
    5. Retornar ReconciliationResult con los conteos para que el orquestador (M7)
       pueda tomar acción.

Dependencias inyectadas:
    - GridState: acceso a DB local.
    - BinanceAuthenticatedClient: acceso al API de Binance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from chimuelo_prime.api_client.client import BinanceAuthenticatedClient
from chimuelo_prime.exchange_config.logger import get_logger
from chimuelo_prime.grid_state.exceptions import ReconciliationError
from chimuelo_prime.grid_state.grid_state import GridState

# Weights de endpoints usados (Binance Spot, 2024)
_WEIGHT_OPEN_ORDERS = 3  # GET /api/v3/openOrders con symbol
_WEIGHT_QUERY_ORDER = 2  # GET /api/v3/order


@dataclass(frozen=True)
class ReconciliationResult:
    """Resultado de una reconciliación con Binance.

    Attributes:
        symbol:          Par de trading reconciliado.
        filled_ids:      Órdenes locales marcadas como FILLED (desaparecieron de Binance).
        canceled_ids:    Órdenes locales marcadas como CANCELED/EXPIRED.
        unexpected_ids:  Órdenes en Binance que no están en la DB local (manuales).
    """

    symbol: str
    filled_ids: list[int] = field(default_factory=list)
    canceled_ids: list[int] = field(default_factory=list)
    unexpected_ids: list[int] = field(default_factory=list)

    @property
    def has_divergences(self) -> bool:
        """True si se encontró alguna divergencia entre Binance y la DB local."""
        return bool(self.filled_ids or self.canceled_ids or self.unexpected_ids)


class Reconciler:
    """Reconcilia el estado local del grid con las órdenes activas en Binance.

    Args:
        grid_state:  Acceso a la DB local (M3).
        api_client:  Cliente autenticado de Binance (M2).
    """

    def __init__(
        self,
        grid_state: GridState,
        api_client: BinanceAuthenticatedClient,
    ) -> None:
        self._grid_state = grid_state
        self._api_client = api_client
        self._log = get_logger(__name__)

    def reconcile(self, symbol: str) -> ReconciliationResult:
        """Reconcilia el estado del grid para un símbolo.

        Args:
            symbol: Par de trading (ej. "SOLUSDT").

        Returns:
            ReconciliationResult con los IDs afectados.

        Raises:
            ReconciliationError: si la API de Binance retorna un error inesperado.
        """
        self._log.info("reconciler.start", symbol=symbol)

        local_open = self._grid_state.get_open_orders(symbol)
        local_ids = {o.order_id for o in local_open}

        binance_open = self._fetch_open_orders(symbol)
        binance_ids = {int(o["orderId"]) for o in binance_open}

        filled_ids: list[int] = []
        canceled_ids: list[int] = []

        missing_ids = local_ids - binance_ids
        for order_id in missing_ids:
            actual_status = self._fetch_order_status(symbol, order_id)
            if actual_status in ("FILLED", "PARTIALLY_FILLED"):
                self._grid_state.update_order_status(order_id, "FILLED")
                filled_ids.append(order_id)
                self._log.info("reconciler.order_filled", order_id=order_id)
            else:
                self._grid_state.update_order_status(order_id, actual_status)
                canceled_ids.append(order_id)
                self._log.info(
                    "reconciler.order_closed",
                    order_id=order_id,
                    status=actual_status,
                )

        unexpected_ids = list(binance_ids - local_ids)
        if unexpected_ids:
            self._log.warning(
                "reconciler.unexpected_orders",
                symbol=symbol,
                count=len(unexpected_ids),
                order_ids=unexpected_ids,
            )

        result = ReconciliationResult(
            symbol=symbol,
            filled_ids=filled_ids,
            canceled_ids=canceled_ids,
            unexpected_ids=unexpected_ids,
        )
        self._log.info(
            "reconciler.done",
            symbol=symbol,
            filled=len(filled_ids),
            canceled=len(canceled_ids),
            unexpected=len(unexpected_ids),
        )
        return result

    def _fetch_open_orders(self, symbol: str) -> list[dict[str, Any]]:
        """GET /api/v3/openOrders — retorna lista de órdenes activas en Binance."""
        try:
            result = self._api_client.get(
                "/api/v3/openOrders",
                params={"symbol": symbol},
                weight=_WEIGHT_OPEN_ORDERS,
            )
        except Exception as exc:
            raise ReconciliationError(
                f"Error al obtener openOrders de Binance para {symbol}: {exc}"
            ) from exc
        if not isinstance(result, list):
            raise ReconciliationError(
                f"Respuesta inesperada de /api/v3/openOrders para {symbol}: {result!r}"
            )
        return result

    def _fetch_order_status(self, symbol: str, order_id: int) -> str:
        """GET /api/v3/order — retorna el status actual de una orden en Binance."""
        try:
            response = self._api_client.get(
                "/api/v3/order",
                params={"symbol": symbol, "orderId": order_id},
                weight=_WEIGHT_QUERY_ORDER,
            )
        except Exception as exc:
            raise ReconciliationError(
                f"Error al consultar orden {order_id} en Binance: {exc}"
            ) from exc
        return str(response["status"])
