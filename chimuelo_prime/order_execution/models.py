"""Modelos de dominio del módulo order_execution (M4).

Todos los modelos son frozen=True y Decimal-only para campos monetarios.
OrderStatus se importa de M3 (Single Source of Truth).

NO se redefinen modelos que ya existen en M1 o M3.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

from chimuelo_prime.grid_state.schema import OrderStatus


class PlacedOrder(BaseModel):
    """Resultado de colocar una orden en Binance (POST /api/v3/order).

    Attributes:
        order_id:        orderId de Binance — PK canónica en M3.
        client_order_id: clientOrderId (generado por Binance o provisto por M5).
        symbol:          Par de trading.
        side:            "BUY" | "SELL".
        price:           Precio límite de la orden.
        orig_qty:        Cantidad original solicitada.
        executed_qty:    Cantidad ejecutada al momento del placement (típicamente 0).
        status:          Estado inicial (típicamente NEW).
        level_id:        FK al GridLevel de M3 que originó esta orden.
        transact_time:   Timestamp UTC-naive de la transacción en Binance.
    """

    model_config = ConfigDict(frozen=True)

    order_id: int
    client_order_id: str
    symbol: str
    side: str
    price: Decimal
    orig_qty: Decimal
    executed_qty: Decimal
    status: OrderStatus
    level_id: int
    transact_time: datetime

    @field_validator("price", "orig_qty", "executed_qty", mode="before")
    @classmethod
    def _no_float(cls, v: object) -> object:
        if isinstance(v, float):
            raise ValueError(f"float prohibido en campos monetarios: {v!r}")
        return v


class CancelResult(BaseModel):
    """Resultado de cancelar una orden en Binance (DELETE /api/v3/order).

    Attributes:
        order_id:      orderId de Binance.
        symbol:        Par de trading.
        status:        Estado final tras la cancelación (CANCELED).
        orig_qty:      Cantidad original de la orden.
        executed_qty:  Cantidad ejecutada antes de la cancelación (puede ser > 0).
    """

    model_config = ConfigDict(frozen=True)

    order_id: int
    symbol: str
    status: OrderStatus
    orig_qty: Decimal
    executed_qty: Decimal

    @field_validator("orig_qty", "executed_qty", mode="before")
    @classmethod
    def _no_float(cls, v: object) -> object:
        if isinstance(v, float):
            raise ValueError(f"float prohibido en campos monetarios: {v!r}")
        return v


class OrderStatusUpdate(BaseModel):
    """Resultado de una sincronización de estado de orden con Binance.

    Attributes:
        order_id:        orderId de Binance.
        symbol:          Par de trading.
        previous_status: Estado en M3 antes de la sincronización.
        current_status:  Estado retornado por Binance.
        executed_qty:    Cantidad ejecutada según Binance.
        synced_at:       Timestamp UTC-naive del momento de sincronización.
        status_changed:  True si previous_status != current_status.
    """

    model_config = ConfigDict(frozen=True)

    order_id: int
    symbol: str
    previous_status: OrderStatus
    current_status: OrderStatus
    executed_qty: Decimal
    synced_at: datetime
    status_changed: bool

    @field_validator("executed_qty", mode="before")
    @classmethod
    def _no_float(cls, v: object) -> object:
        if isinstance(v, float):
            raise ValueError(f"float prohibido en campos monetarios: {v!r}")
        return v
