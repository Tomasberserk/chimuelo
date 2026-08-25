"""Motor de simulación event-driven de alta fidelidad para backtesting (M6).

Replica la máquina de estados de `GridEngine` (M5) sobre velas históricas,
garantizando pureza Decimal y consistencia en el balance, inventario y órdenes.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.backtesting.metrics import (
    calculate_calmar_ratio,
    calculate_max_drawdown,
    calculate_profit_factor,
    calculate_sortino_ratio,
    calculate_total_return,
)
from chimuelo_prime.exchange_config.logger import get_logger
from chimuelo_prime.exchange_config.models import SymbolConfig
from chimuelo_prime.grid_engine.calculator import GridCalculator, LevelSpec


class EquityPoint(BaseModel):
    """Punto de la serie de tiempo del portafolio en un instante de tiempo."""

    model_config = ConfigDict(frozen=True, strict=True)

    timestamp: datetime = Field(description="Fecha y hora del snapshot")
    cash: Decimal = Field(description="Efectivo en quote currency")
    inventory: Decimal = Field(description="Cantidad de activo base en inventario")
    inventory_value: Decimal = Field(description="Valor del inventario en quote currency")
    equity: Decimal = Field(description="Patrimonio neto (cash + inventory_value)")
    drawdown_pct: Decimal = Field(description="Drawdown porcentual desde el pico histórico")


class TradeRecord(BaseModel):
    """Registro de una operación de compra y venta completada."""

    model_config = ConfigDict(frozen=True, strict=True)

    level_index: int = Field(description="Índice del nivel del grid")
    buy_price: Decimal = Field(description="Precio de ejecución de la compra")
    sell_price: Decimal = Field(description="Precio de ejecución de la venta")
    qty: Decimal = Field(description="Cantidad de activo operada")
    buy_time: datetime = Field(description="Fecha y hora de compra")
    sell_time: datetime = Field(description="Fecha y hora de venta")
    pnl: Decimal = Field(description="Beneficio neto en quote currency")
    pnl_pct: Decimal = Field(description="Rentabilidad porcentual respecto al precio de compra")


class BacktestReport(BaseModel):
    """Reporte final unificado de un backtest."""

    model_config = ConfigDict(frozen=True, strict=True)

    symbol: str = Field(description="Símbolo operado")
    interval: str = Field(description="Intervalo de velas utilizado")
    start_time: datetime = Field(description="Fecha de inicio de la simulación")
    end_time: datetime = Field(description="Fecha de fin de la simulación")
    initial_cash: Decimal = Field(description="Capital inicial")
    final_cash: Decimal = Field(description="Efectivo final")
    initial_equity: Decimal = Field(description="Patrimonio inicial")
    final_equity: Decimal = Field(description="Patrimonio final")
    total_return_pct: Decimal = Field(description="Retorno total porcentual")
    max_drawdown_pct: Decimal = Field(description="Máximo drawdown porcentual")
    profit_factor: Decimal = Field(description="Profit Factor (ratio ganancia/pérdida)")
    sortino_ratio: Decimal = Field(description="Ratio de Sortino (anualizado)")
    calmar_ratio: Decimal = Field(description="Ratio de Calmar (anualizado)")
    win_rate_pct: Decimal = Field(description="Porcentaje de operaciones ganadoras")
    total_trades: int = Field(description="Número de operaciones intentadas/abiertas")
    completed_trades: int = Field(description="Número de operaciones completadas")
    recreate_buy_on_sell_fill: bool = Field(description="Indica si se usó el modo continuo")
    timeseries: list[EquityPoint] = Field(description="Serie temporal del portafolio")
    trades: list[TradeRecord] = Field(description="Lista de trades completados")


class BacktestSimulator:
    """Simulador de grid trading event-driven con precisión Decimal."""

    def __init__(
        self,
        config: SymbolConfig,
        candles: list[HistoricalCandle],
        initial_cash: Decimal | None = None,
        fee_rate: Decimal = Decimal("0.0"),
    ) -> None:
        """Inicializa el simulador con su configuración y datos.

        Args:
            config: Configuración del símbolo y del grid.
            candles: Lista ordenada de velas históricas.
            initial_cash: Capital en quote currency. Si es None, se calcula
                          dinámicamente como `capital_per_order * grid_levels`.
            fee_rate: Tasa de comisión (ej. Decimal("0.001") para 0.1%).
        """
        self._config = config
        self._candles = sorted(candles, key=lambda c: c.timestamp)
        self._fee_rate = fee_rate
        self._log = get_logger(__name__)

        if initial_cash is None:
            self._initial_cash = config.capital_per_order * Decimal(config.grid_levels)
        else:
            self._initial_cash = initial_cash

    def run(self, recreate_buy_on_sell_fill: bool = False) -> BacktestReport:
        """Ejecuta la simulación sobre el set de velas históricas.

        Args:
            recreate_buy_on_sell_fill: Modo Continuo si True, Modo Strict si False.

        Returns:
            BacktestReport con métricas completas y series de tiempo.
        """
        if not self._candles:
            raise ValueError("No se proporcionaron velas históricas para la simulación.")

        # Inicialización del Grid usando GridCalculator
        levels = GridCalculator.compute_levels(self._config)
        spot_price = self._candles[0].open

        # Determinar qué niveles iniciales tienen BUY activo
        below = GridCalculator.levels_below_price(levels, spot_price)
        below_indices = {spec.level_index for spec in below}

        # Estado operativo de cada nivel
        # Status puede ser: "PENDING_BUY", "PENDING_SELL", "COMPLETED", "INACTIVE"
        level_states: dict[int, dict[str, Any]] = {}
        for lvl in levels:
            is_below = lvl.level_index in below_indices
            level_states[lvl.level_index] = {
                "spec": lvl,
                "status": "PENDING_BUY" if is_below else "INACTIVE",
                "buy_filled_price": None,
                "buy_filled_time": None,
                "sell_filled_price": None,
                "sell_filled_time": None,
            }

        # Variables de balance
        cash = self._initial_cash
        inventory = Decimal("0")
        max_equity = self._initial_cash

        # Listas de registro
        timeseries: list[EquityPoint] = []
        completed_trades: list[TradeRecord] = []

        # Recorrer velas cronológicamente
        for candle in self._candles:
            # Para evitar loops infinitos dentro de la misma vela en modo continuo,
            # limitamos a una transacción de cada tipo (compra, venta) por nivel en cada vela.
            for idx, state in level_states.items():
                spec: LevelSpec = state["spec"]
                sell_filled_this_candle = False

                # 1. Evaluar si se ejecuta una orden BUY
                if state["status"] == "PENDING_BUY" and candle.low <= spec.lower_price:
                    # Costo de la orden de compra
                    cost = spec.lower_price * spec.qty
                    fee = cost * self._fee_rate
                    total_cost = cost + fee

                    if cash >= total_cost:
                        cash -= total_cost
                        inventory += spec.qty

                        state["status"] = "PENDING_SELL"
                        state["buy_filled_price"] = spec.lower_price
                        state["buy_filled_time"] = candle.timestamp

                        self._log.debug(
                            "backtest.buy_filled",
                            level=idx,
                            price=str(spec.lower_price),
                            qty=str(spec.qty),
                            timestamp=candle.timestamp,
                        )
                    else:
                        self._log.warning(
                            "backtest.insufficient_funds_buy",
                            level=idx,
                            needed=str(total_cost),
                            cash=str(cash),
                            timestamp=candle.timestamp,
                        )

                # 2. Evaluar si se ejecuta una orden SELL complementaria
                if (
                    state["status"] == "PENDING_SELL"
                    and candle.high >= spec.upper_price
                    and not sell_filled_this_candle
                ):
                    # Ingreso de la orden de venta
                    revenue = spec.upper_price * spec.qty
                    fee = revenue * self._fee_rate
                    net_revenue = revenue - fee

                    cash += net_revenue
                    inventory -= spec.qty

                    # Registrar trade completado
                    buy_price = state["buy_filled_price"]
                    buy_time = state["buy_filled_time"]
                    pnl = net_revenue - (
                        buy_price * spec.qty + (buy_price * spec.qty * self._fee_rate)
                    )
                    pnl_pct = ((spec.upper_price - buy_price) / buy_price) * Decimal("100")

                    trade = TradeRecord(
                        level_index=idx,
                        buy_price=buy_price,
                        sell_price=spec.upper_price,
                        qty=spec.qty,
                        buy_time=buy_time,
                        sell_time=candle.timestamp,
                        pnl=pnl,
                        pnl_pct=pnl_pct,
                    )
                    completed_trades.append(trade)
                    sell_filled_this_candle = True

                    self._log.debug(
                        "backtest.sell_filled",
                        level=idx,
                        price=str(spec.upper_price),
                        qty=str(spec.qty),
                        pnl=str(pnl),
                        timestamp=candle.timestamp,
                    )

                    # Actualizar estado según el modo de simulación
                    if recreate_buy_on_sell_fill:
                        state["status"] = "PENDING_BUY"
                        state["buy_filled_price"] = None
                        state["buy_filled_time"] = None
                    else:
                        state["status"] = "COMPLETED"

                # 3. Edge-case: Si estaba INACTIVE, pero el precio cruzó hacia arriba o abajo?
                # En v1, un nivel INACTIVE no tiene órdenes puestas.
                # Pero en modo Continuo, si el precio baja por debajo del lower_price de un nivel INACTIVE,
                # ¿deberíamos activarlo colocando un BUY?
                # Para fidelidad absoluta con el bot real, el bot real colocaría BUYs cuando
                # se inicia. Si no se inicia ahí, no los coloca.
                # En M6, los niveles inactivos se quedan inactivos, emulando la geometría de M5.

            # Registrar punto en la serie de tiempo al final de la vela
            inventory_value = inventory * candle.close
            equity = cash + inventory_value
            max_equity = max(max_equity, equity)
            drawdown_pct = (
                ((max_equity - equity) / max_equity) * Decimal("100")
                if max_equity > 0
                else Decimal("0.0")
            )

            timeseries.append(
                EquityPoint(
                    timestamp=candle.timestamp,
                    cash=cash,
                    inventory=inventory,
                    inventory_value=inventory_value,
                    equity=equity,
                    drawdown_pct=drawdown_pct,
                )
            )

        # Calcular métricas globales usando las funciones de metrics.py
        total_returns = [ep.equity for ep in timeseries]
        total_return_pct = calculate_total_return(self._initial_cash, total_returns[-1])
        max_dd = calculate_max_drawdown(total_returns)

        # Calcular Profit Factor
        # Ganancias brutas de los trades cerrados
        gross_profits = sum((t.pnl for t in completed_trades if t.pnl > 0), Decimal("0"))
        # Pérdidas flotantes (unrealized losses) al final de la simulación
        unrealized_losses = Decimal("0")
        last_close = self._candles[-1].close
        for state in level_states.values():
            if state["status"] == "PENDING_SELL":
                buy_p = state["buy_filled_price"]
                qty = state["spec"].qty
                if last_close < buy_p:
                    unrealized_losses += (buy_p - last_close) * qty

        profit_factor = calculate_profit_factor(gross_profits, unrealized_losses)

        # Calcular Sortino y Calmar Ratios
        interval_str = self._config.filters.symbol  # Placeholder o configuración de tiempo
        # Para Sortino/Calmar necesitamos la lista de equitites
        sortino = calculate_sortino_ratio(total_returns, interval_str)
        calmar = calculate_calmar_ratio(total_returns, max_dd, interval_str)

        # Win Rate
        total_completed = len(completed_trades)
        wins = sum((1 for t in completed_trades if t.pnl > 0), 0)
        win_rate = (
            (Decimal(wins) / Decimal(total_completed) * Decimal("100"))
            if total_completed > 0
            else Decimal("0.0")
        )

        # Contar total de trades intentados (completados + compras que se quedaron abiertas)
        open_buys_count = sum(
            (1 for state in level_states.values() if state["status"] == "PENDING_SELL"), 0
        )
        total_trades = total_completed + open_buys_count

        return BacktestReport(
            symbol=self._config.filters.symbol,
            interval="1h",  # Predeterminado para v1
            start_time=self._candles[0].timestamp,
            end_time=self._candles[-1].timestamp,
            initial_cash=self._initial_cash,
            final_cash=cash,
            initial_equity=self._initial_cash,
            final_equity=total_returns[-1],
            total_return_pct=total_return_pct,
            max_drawdown_pct=max_dd,
            profit_factor=profit_factor,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            win_rate_pct=win_rate,
            total_trades=total_trades,
            completed_trades=total_completed,
            recreate_buy_on_sell_fill=recreate_buy_on_sell_fill,
            timeseries=timeseries,
            trades=completed_trades,
        )
