"""Construcción determinista de payloads para la API de Binance (M4 interno).

Módulo puro: dado un SymbolConfig y parámetros de orden, retorna un dict[str, str]
listo para pasar a BinanceAuthenticatedClient. Sin efectos secundarios ni I/O.

Solo debe ser importado por executor.py dentro de order_execution/.
Ningún módulo externo (M5, M3) debe importar desde _internal/.

Raises:
    FilterValidationError (de M1): si precio, cantidad o notional violan filtros.
    No lanza excepciones propias de M4 — la causa es siempre una violación de filtro.
"""

from __future__ import annotations

from decimal import Decimal

from chimuelo_prime.exchange_config.models import SymbolConfig

_ORDER_TYPE = "LIMIT"
_TIME_IN_FORCE = "GTC"


def build_limit_order_payload(
    config: SymbolConfig,
    side: str,
    price: Decimal,
    qty: Decimal,
    client_order_id: str | None,
) -> dict[str, str]:
    """Construye el payload para POST /api/v3/order (orden LIMIT GTC).

    Aplica redondeo hacia abajo via M1 antes de validar:
        - round_price_to_tick: precio al múltiplo de tick_size más cercano hacia abajo.
        - round_qty_to_step:   cantidad al múltiplo de step_size más cercano hacia abajo.

    Luego valida precio, cantidad y notional contra los filtros de M1.
    Si cualquier validación falla, lanza FilterValidationError — la llamada a Binance
    nunca ocurre.

    Todos los valores Decimal se convierten a str en el dict retornado:
    Binance espera strings, no Decimals ni floats.

    Args:
        config:           SymbolConfig con filtros del exchange y parámetros de estrategia.
        side:             "BUY" o "SELL".
        price:            Precio límite propuesto (puede redondearse).
        qty:              Cantidad propuesta (puede redondearse).
        client_order_id:  Si se provee, se incluye como newClientOrderId.

    Returns:
        dict[str, str] con todos los campos listos para la API.

    Raises:
        FilterValidationError: si precio, cantidad o notional no pasan filtros de M1.
    """
    price_r = config.filters.round_price_to_tick(price)
    qty_r = config.filters.round_qty_to_step(qty)

    config.filters.validate_price(price_r)
    config.filters.validate_quantity(qty_r)
    config.filters.validate_notional(price_r, qty_r)

    payload: dict[str, str] = {
        "symbol": config.filters.symbol,
        "side": side,
        "type": _ORDER_TYPE,
        "timeInForce": _TIME_IN_FORCE,
        "quantity": str(qty_r),
        "price": str(price_r),
    }
    if client_order_id is not None:
        payload["newClientOrderId"] = client_order_id
    return payload


def build_cancel_payload(symbol: str, order_id: int) -> dict[str, str]:
    """Construye el payload para DELETE /api/v3/order.

    Args:
        symbol:   Par de trading.
        order_id: Binance orderId a cancelar.

    Returns:
        dict[str, str] con symbol y orderId como strings.
    """
    return {
        "symbol": symbol,
        "orderId": str(order_id),
    }
