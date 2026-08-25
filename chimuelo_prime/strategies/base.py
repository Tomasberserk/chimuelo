"""Clase base e interfaz abstracta para estrategias de trading algorítmico."""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.strategies.models import TradeSignal


class BaseStrategy(ABC):
    """Interfaz abstracta que define el contrato de cualquier estrategia de trading."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Nombre identificador de la estrategia."""
        ...

    @abstractmethod
    def evaluate_candle(
        self,
        candles: list[HistoricalCandle],
        current_index: int,
    ) -> TradeSignal | None:
        """Evalúa las condiciones de entrada/salida sobre una vela específica.

        Args:
            candles: Serie completa de velas históricas disponibles hasta el momento.
            current_index: Índice de la vela actual a evaluar (evita look-ahead bias).

        Returns:
            TradeSignal si se dispara una condición, o None.
        """
        ...

    def calculate_position_size(
        self,
        account_equity: Decimal,
        entry_price: Decimal,
        stop_loss_price: Decimal,
        min_notional: Decimal = Decimal("5.0"),
        risk_pct: Decimal = Decimal("0.025"),
    ) -> Decimal:
        """Calcula el tamaño óptimo de posición en activo base según el riesgo definido.

        Fórmula de Money Management:
            Riesgo en Dólares ($R) = account_equity * risk_pct (ej. 2.5% de $25 = $0.625 USD)
            Distancia de Stop Loss ($D) = |entry_price - stop_loss_price|
            Cantidad Teórica = $R / $D
            Notional = Cantidad * entry_price
            Si Notional < min_notional (ej. $5 USDT):
                Para cuentas micro ($25 USD), se asigna la cantidad mínima que cumpla min_notional
                siempre que el riesgo resultante no exceda el límite de seguridad (ej. max 5% de la cuenta).

        Args:
            account_equity: Capital total actual de la cuenta.
            entry_price: Precio estimado de entrada.
            stop_loss_price: Precio de corte de pérdidas.
            min_notional: Notional mínimo exigido por el exchange (Binance $5 USDT).
            risk_pct: Porcentaje de riesgo por operación (default 2.5%).

        Returns:
            Cantidad calculada de activo base. Retorna Decimal("0") si no es viable.
        """
        if account_equity <= Decimal("0") or entry_price <= Decimal("0"):
            return Decimal("0")

        stop_distance = abs(entry_price - stop_loss_price)
        if stop_distance <= Decimal("0"):
            return Decimal("0")

        dollar_risk = account_equity * risk_pct
        theoretical_qty = dollar_risk / stop_distance
        notional = theoretical_qty * entry_price

        # Si el notional es menor que el mínimo del exchange (ej. $5.00 USDT en Binance Spot)
        if notional < min_notional:
            min_qty = min_notional / entry_price
            effective_risk = min_qty * stop_distance
            # Permitir si el riesgo efectivo no supera el 5% del capital total
            max_allowed_risk = account_equity * Decimal("0.06")
            if effective_risk <= max_allowed_risk and (min_qty * entry_price) <= account_equity:
                return min_qty
            return Decimal("0")

        # Si el notional excede el capital total disponible, limitar al 100% del capital
        if notional > account_equity:
            return account_equity / entry_price

        return theoretical_qty
