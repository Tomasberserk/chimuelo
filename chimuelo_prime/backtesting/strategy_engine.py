"""Motor de simulación event-driven para Estrategias Cuantitativas de Señales.

Ejecuta velas históricas con modelado riguroso de:
- Precios de ejecución con slippage.
- Comisiones de exchange (Maker/Taker o Spot).
- Evaluación intrabarra de Stop Loss y Take Profit.
- Dimensionamiento dinámico de posición y reglas de Money Management Decimal.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.backtesting.metrics import (
    calculate_calmar_ratio,
    calculate_max_drawdown,
    calculate_profit_factor,
    calculate_sortino_ratio,
    calculate_total_return,
)
from chimuelo_prime.exchange_config.logger import get_logger
from chimuelo_prime.strategies.models import SignalType

if TYPE_CHECKING:
    from chimuelo_prime.strategies.base import BaseStrategy


class StrategyEquityPoint(BaseModel):
    """Snapshot del portafolio en una vela de la simulación."""

    model_config = ConfigDict(frozen=True, strict=True)

    timestamp: datetime = Field(description="Fecha y hora de la vela")
    cash: Decimal = Field(description="Efectivo en quote currency")
    position_qty: Decimal = Field(description="Activo base en posición")
    position_value: Decimal = Field(description="Valor de la posición al cierre de la vela")
    equity: Decimal = Field(description="Patrimonio total (cash + position_value)")
    drawdown_pct: Decimal = Field(description="Drawdown porcentual desde el pico")
    in_position: bool = Field(description="Indica si hay una posición activa")


class TradeExecutionRecord(BaseModel):
    """Registro de una operación completada con auditoría detallada."""

    model_config = ConfigDict(frozen=True, strict=True)

    trade_id: int = Field(description="Identificador correlativo")
    symbol: str = Field(description="Símbolo operado")
    entry_time: datetime = Field(description="Momento de entrada")
    exit_time: datetime = Field(description="Momento de salida")
    entry_price: Decimal = Field(description="Precio promedio de entrada (con slippage)")
    exit_price: Decimal = Field(description="Precio promedio de salida (con slippage)")
    qty: Decimal = Field(description="Cantidad de activo operada")
    notional: Decimal = Field(description="Valor en USD de la orden")
    stop_loss: Decimal = Field(description="Nivel de Stop Loss fijado")
    take_profit: Decimal = Field(description="Nivel de Take Profit fijado")
    gross_pnl: Decimal = Field(description="PnL bruto en USD")
    total_fees: Decimal = Field(description="Total comisiones pagadas en USD")
    net_pnl: Decimal = Field(description="PnL neto final en USD")
    net_pnl_pct: Decimal = Field(description="Rendimiento porcentual respecto a la entrada")
    exit_reason: str = Field(description="Causa de cierre: TAKE_PROFIT, STOP_LOSS, END_OF_DATA")
    reason: str = Field(default="", description="Razón cuantitativa de entrada")

    @field_validator(
        "entry_price",
        "exit_price",
        "qty",
        "notional",
        "stop_loss",
        "take_profit",
        "gross_pnl",
        "total_fees",
        "net_pnl",
        "net_pnl_pct",
        mode="before",
    )
    @classmethod
    def reject_floats(cls, v: Any) -> Any:
        if isinstance(v, float):
            raise TypeError(f"Floats no permitidos en modelos financieros: {v!r}")
        if v is not None and not isinstance(v, Decimal):
            return Decimal(str(v))
        return v


class SignalBacktestReport(BaseModel):
    """Reporte cuantitativo exhaustivo de un backtest de estrategia."""

    model_config = ConfigDict(frozen=True, strict=True)

    strategy_name: str = Field(description="Nombre de la estrategia simulada")
    symbol: str = Field(description="Símbolo del par")
    interval: str = Field(description="Temporalidad de las velas")
    start_time: datetime = Field(description="Inicio del periodo")
    end_time: datetime = Field(description="Fin del periodo")
    initial_cash: Decimal = Field(description="Capital inicial")
    final_cash: Decimal = Field(description="Efectivo final")
    final_equity: Decimal = Field(description="Patrimonio neto final")
    total_return_pct: Decimal = Field(description="Retorno total porcentual")
    net_profit_usd: Decimal = Field(description="Beneficio neto total en USD")
    total_trades: int = Field(description="Cantidad total de operaciones completadas")
    winning_trades: int = Field(description="Operaciones con PnL neto positivo")
    losing_trades: int = Field(description="Operaciones con PnL neto negativo o cero")
    win_rate_pct: Decimal = Field(description="Porcentaje de acierto (Win Rate)")
    profit_factor: Decimal = Field(description="Profit Factor (Ganancias / Pérdidas)")
    max_drawdown_pct: Decimal = Field(description="Máximo Drawdown porcentual")
    sortino_ratio: Decimal = Field(description="Ratio de Sortino anualizado")
    calmar_ratio: Decimal = Field(description="Ratio de Calmar anualizado")
    average_trade_pnl: Decimal = Field(description="Promedio de PnL por operación en USD")
    average_win_pnl: Decimal = Field(description="Promedio de ganancias en trades ganadores")
    average_loss_pnl: Decimal = Field(description="Promedio de pérdidas en trades perdedores")
    total_fees_paid: Decimal = Field(description="Total comisiones pagadas")
    trades: list[TradeExecutionRecord] = Field(description="Bitácora de trades")
    timeseries: list[StrategyEquityPoint] = Field(description="Curva de patrimonio histórica")


class SignalStrategyBacktester:
    """Simulador de alto rendimiento para estrategias direccionales cuantitativas."""

    def __init__(
        self,
        strategy: BaseStrategy,
        candles: list[HistoricalCandle],
        symbol: str = "SOLUSDT",
        interval: str = "15m",
        initial_cash: Decimal = Decimal("25.00"),
        fee_rate: Decimal = Decimal("0.001"),  # 0.1% Spot fee estándar
        slippage_pct: Decimal = Decimal("0.0005"),  # 0.05% Slippage estimado
        risk_per_trade_pct: Decimal = Decimal("0.025"),  # 2.5% de riesgo por trade
        min_notional: Decimal = Decimal("5.00"),  # $5 USDT min_notional Binance
    ) -> None:
        self._strategy = strategy
        self._candles = sorted(candles, key=lambda c: c.timestamp)
        self._symbol = symbol
        self._interval = interval
        self._initial_cash = initial_cash
        self._fee_rate = fee_rate
        self._slippage_pct = slippage_pct
        self._risk_per_trade = risk_per_trade_pct
        self._min_notional = min_notional
        self._log = get_logger(__name__)

    def run(self) -> SignalBacktestReport:
        """Ejecuta la simulación cronológica vela por vela."""
        if not self._candles:
            raise ValueError("No se proporcionaron velas para la simulación.")

        cash = self._initial_cash
        peak_equity = self._initial_cash

        in_position = False
        position_qty = Decimal("0")
        entry_price = Decimal("0")
        entry_time = self._candles[0].timestamp
        stop_loss = Decimal("0")
        take_profit = Decimal("0")
        signal_reason = ""
        entry_fee = Decimal("0")

        timeseries: list[StrategyEquityPoint] = []
        trades: list[TradeExecutionRecord] = []
        trade_id_seq = 1

        for i, candle in enumerate(self._candles):
            # 1. Monitoreo Intrabarra de Posición Abierta (Stop Loss / Take Profit)
            if in_position:
                sl_hit = candle.low <= stop_loss
                tp_hit = candle.high >= take_profit

                if sl_hit or tp_hit:
                    # Determinar precio de salida y motivo
                    if sl_hit and tp_hit:
                        # Si en la misma vela tocó ambos extremos, asumimos el peor caso (SL) por conservadurismo
                        exit_price_raw = stop_loss
                        exit_reason = "STOP_LOSS"
                    elif sl_hit:
                        exit_price_raw = stop_loss
                        exit_reason = "STOP_LOSS"
                    else:
                        exit_price_raw = take_profit
                        exit_reason = "TAKE_PROFIT"

                    # Aplicar slippage de salida desfavorable
                    if exit_reason == "STOP_LOSS":
                        exec_exit_price = exit_price_raw * (Decimal("1.0") - self._slippage_pct)
                    else:
                        exec_exit_price = exit_price_raw * (Decimal("1.0") - self._slippage_pct)

                    gross_revenue = position_qty * exec_exit_price
                    exit_fee = gross_revenue * self._fee_rate
                    net_revenue = gross_revenue - exit_fee

                    entry_notional = position_qty * entry_price
                    gross_pnl = gross_revenue - entry_notional
                    total_trade_fees = entry_fee + exit_fee
                    net_pnl = gross_pnl - total_trade_fees
                    net_pnl_pct = (net_pnl / entry_notional) * Decimal("100")

                    cash += net_revenue

                    trade_record = TradeExecutionRecord(
                        trade_id=trade_id_seq,
                        symbol=self._symbol,
                        entry_time=entry_time,
                        exit_time=candle.timestamp,
                        entry_price=entry_price,
                        exit_price=exec_exit_price,
                        qty=position_qty,
                        notional=entry_notional,
                        stop_loss=stop_loss,
                        take_profit=take_profit,
                        gross_pnl=gross_pnl,
                        total_fees=total_trade_fees,
                        net_pnl=net_pnl,
                        net_pnl_pct=net_pnl_pct,
                        exit_reason=exit_reason,
                        reason=signal_reason,
                    )
                    trades.append(trade_record)
                    trade_id_seq += 1

                    in_position = False
                    position_qty = Decimal("0")
                    self._log.debug(
                        "backtest.trade_closed",
                        reason=exit_reason,
                        net_pnl=str(net_pnl),
                        timestamp=candle.timestamp,
                    )

            # 2. Evaluación de Señal de Entrada si no hay posición activa
            if not in_position:
                signal = self._strategy.evaluate_candle(self._candles, i)
                if (
                    signal
                    and signal.signal_type == SignalType.BUY
                    and signal.stop_loss
                    and signal.take_profit
                ):
                    # Calcular tamaño de posición según Money Management
                    account_equity = cash
                    qty = self._strategy.calculate_position_size(
                        account_equity=account_equity,
                        entry_price=signal.price,
                        stop_loss_price=signal.stop_loss,
                        min_notional=self._min_notional,
                        risk_pct=self._risk_per_trade,
                    )

                    if qty > Decimal("0"):
                        # Aplicar slippage de entrada desfavorable
                        exec_entry_price = signal.price * (Decimal("1.0") + self._slippage_pct)
                        entry_cost = qty * exec_entry_price
                        entry_fee = entry_cost * self._fee_rate
                        total_required = entry_cost + entry_fee

                        # Si excede ligeramente el efectivo disponible por comisiones/slippage, ajustar qty
                        if total_required > cash and cash > Decimal("0"):
                            qty = cash / (exec_entry_price * (Decimal("1.0") + self._fee_rate))
                            entry_cost = qty * exec_entry_price
                            entry_fee = entry_cost * self._fee_rate
                            total_required = entry_cost + entry_fee

                        if cash >= total_required and qty > Decimal("0"):
                            cash -= total_required
                            in_position = True
                            position_qty = qty
                            entry_price = exec_entry_price
                            entry_time = candle.timestamp
                            stop_loss = signal.stop_loss
                            take_profit = signal.take_profit
                            signal_reason = signal.reason

                            self._log.debug(
                                "backtest.position_opened",
                                price=str(entry_price),
                                qty=str(qty),
                                cost=str(total_required),
                                timestamp=candle.timestamp,
                            )

            # 3. Snapshot de Serie de Tiempo al Cierre de la Vela
            position_val = (position_qty * candle.close) if in_position else Decimal("0")
            current_equity = cash + position_val
            peak_equity = max(peak_equity, current_equity)
            drawdown_pct = (
                ((peak_equity - current_equity) / peak_equity) * Decimal("100")
                if peak_equity > Decimal("0")
                else Decimal("0")
            )

            timeseries.append(
                StrategyEquityPoint(
                    timestamp=candle.timestamp,
                    cash=cash,
                    position_qty=position_qty,
                    position_value=position_val,
                    equity=current_equity,
                    drawdown_pct=drawdown_pct,
                    in_position=in_position,
                )
            )

        # 4. Cerrar posición remanente al final del dataset si quedó alguna abierta
        if in_position:
            last_candle = self._candles[-1]
            exec_exit_price = last_candle.close * (Decimal("1.0") - self._slippage_pct)
            gross_revenue = position_qty * exec_exit_price
            exit_fee = gross_revenue * self._fee_rate
            net_revenue = gross_revenue - exit_fee
            entry_notional = position_qty * entry_price
            gross_pnl = gross_revenue - entry_notional
            total_trade_fees = entry_fee + exit_fee
            net_pnl = gross_pnl - total_trade_fees
            net_pnl_pct = (net_pnl / entry_notional) * Decimal("100")
            cash += net_revenue

            trades.append(
                TradeExecutionRecord(
                    trade_id=trade_id_seq,
                    symbol=self._symbol,
                    entry_time=entry_time,
                    exit_time=last_candle.timestamp,
                    entry_price=entry_price,
                    exit_price=exec_exit_price,
                    qty=position_qty,
                    notional=entry_notional,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    gross_pnl=gross_pnl,
                    total_fees=total_trade_fees,
                    net_pnl=net_pnl,
                    net_pnl_pct=net_pnl_pct,
                    exit_reason="END_OF_DATA",
                    reason=signal_reason,
                )
            )

        # 5. Consolidación de Métricas Cuantitativas
        final_equity = cash
        total_ret_pct = calculate_total_return(self._initial_cash, final_equity)
        net_profit_usd = final_equity - self._initial_cash
        equities = [pt.equity for pt in timeseries]
        max_dd = calculate_max_drawdown(equities)

        total_trades = len(trades)
        winning_trades = [t for t in trades if t.net_pnl > Decimal("0")]
        losing_trades = [t for t in trades if t.net_pnl <= Decimal("0")]

        win_count = len(winning_trades)
        loss_count = len(losing_trades)
        win_rate = (
            (Decimal(win_count) / Decimal(total_trades) * Decimal("100"))
            if total_trades > 0
            else Decimal("0")
        )

        gross_gains = sum((t.net_pnl for t in winning_trades), Decimal("0"))
        gross_losses = abs(sum((t.net_pnl for t in losing_trades), Decimal("0")))
        profit_factor = calculate_profit_factor(gross_gains, gross_losses)

        sortino = calculate_sortino_ratio(equities, self._interval)
        calmar = calculate_calmar_ratio(equities, max_dd, self._interval)

        avg_pnl = (net_profit_usd / Decimal(total_trades)) if total_trades > 0 else Decimal("0")
        avg_win = (gross_gains / Decimal(win_count)) if win_count > 0 else Decimal("0")
        avg_loss = (gross_losses / Decimal(loss_count)) if loss_count > 0 else Decimal("0")
        total_fees = sum((t.total_fees for t in trades), Decimal("0"))

        return SignalBacktestReport(
            strategy_name=self._strategy.name,
            symbol=self._symbol,
            interval=self._interval,
            start_time=self._candles[0].timestamp,
            end_time=self._candles[-1].timestamp,
            initial_cash=self._initial_cash,
            final_cash=cash,
            final_equity=final_equity,
            total_return_pct=total_ret_pct,
            net_profit_usd=net_profit_usd,
            total_trades=total_trades,
            winning_trades=win_count,
            losing_trades=loss_count,
            win_rate_pct=win_rate,
            profit_factor=profit_factor,
            max_drawdown_pct=max_dd,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            average_trade_pnl=avg_pnl,
            average_win_pnl=avg_win,
            average_loss_pnl=avg_loss,
            total_fees_paid=total_fees,
            trades=trades,
            timeseries=timeseries,
        )
