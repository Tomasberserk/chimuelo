"""Módulo de Paper Trading y Broker Virtual para Chimuelo Prime.

Implementa un broker simulado determinista con aritmética Decimal pura,
soporte para micro-cuentas ($25.00 USDT iniciales), slippage, comisiones,
gestión intrabarra de Stop Loss y Take Profit, y despacho de alertas
estructuradas a través de `AlertManager`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.exchange_config.logger import get_logger
from chimuelo_prime.orchestrator.monitoring import AlertManager
from chimuelo_prime.strategies.models import Position, SignalType, TradeSignal


class PaperTradeExecution(BaseModel):
    """Registro inmutable de una operación de paper trading completada."""

    model_config = ConfigDict(frozen=True, strict=True)

    trade_id: int = Field(description="Identificador secuencial de la operación")
    symbol: str = Field(description="Símbolo del par operado (ej. SOLUSDT)")
    side: str = Field(default="BUY", description="Dirección de la operación (BUY / LONG)")
    entry_time: datetime = Field(description="Momento de apertura")
    exit_time: datetime = Field(description="Momento de cierre")
    entry_price: Decimal = Field(description="Precio de ejecución de entrada (con slippage)")
    exit_price: Decimal = Field(description="Precio de ejecución de salida (con slippage)")
    qty: Decimal = Field(description="Cantidad de activo base operada")
    notional: Decimal = Field(description="Valor total en quote currency a la entrada")
    stop_loss: Decimal = Field(description="Nivel de Stop Loss fijado")
    take_profit: Decimal = Field(description="Nivel de Take Profit fijado")
    gross_pnl: Decimal = Field(description="PnL bruto en quote currency")
    total_fees: Decimal = Field(description="Total comisiones pagadas (entrada + salida)")
    net_pnl: Decimal = Field(description="PnL neto final en quote currency")
    net_pnl_pct: Decimal = Field(description="Rendimiento porcentual neto respecto a la entrada")
    exit_reason: str = Field(
        description="Causa de cierre: STOP_LOSS, TAKE_PROFIT, SIGNAL_SELL, MANUAL_CLOSE"
    )
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


class VirtualBrokerState(BaseModel):
    """Snapshot inmutable del estado del VirtualBroker."""

    model_config = ConfigDict(frozen=True, strict=True)

    cash: Decimal = Field(description="Efectivo disponible en quote currency")
    equity: Decimal = Field(description="Patrimonio total (cash + valor actual de posiciones)")
    open_positions_count: int = Field(description="Número de posiciones abiertas")
    total_trades_count: int = Field(description="Número total de trades cerrados")
    total_realized_pnl: Decimal = Field(description="PnL neto acumulado realizado")

    @field_validator("cash", "equity", "total_realized_pnl", mode="before")
    @classmethod
    def reject_floats(cls, v: Any) -> Any:
        if isinstance(v, float):
            raise TypeError(f"Floats no permitidos en modelos financieros: {v!r}")
        if v is not None and not isinstance(v, Decimal):
            return Decimal(str(v))
        return v


class VirtualBroker:
    """Broker simulado de paper trading de alta fidelidad.

    Maneja saldos, validación de notional mínimo, ejecución con slippage,
    deducción de comisiones, evaluación intrabarra de Stop Loss / Take Profit
    y notificaciones en tiempo real vía AlertManager.
    """

    def __init__(
        self,
        initial_balance: Decimal = Decimal("25.00"),
        fee_rate: Decimal = Decimal("0.001"),
        slippage_pct: Decimal = Decimal("0.0005"),
        min_notional: Decimal = Decimal("5.00"),
        alert_manager: AlertManager | None = None,
    ) -> None:
        # Validación estricta contra floats en inicialización
        for name, val in [
            ("initial_balance", initial_balance),
            ("fee_rate", fee_rate),
            ("slippage_pct", slippage_pct),
            ("min_notional", min_notional),
        ]:
            if isinstance(val, float):
                raise TypeError(
                    f"Floats no permitidos en configuración de VirtualBroker: {name}={val!r}"
                )

        self._initial_balance = Decimal(str(initial_balance))
        self._fee_rate = Decimal(str(fee_rate))
        self._slippage_pct = Decimal(str(slippage_pct))
        self._min_notional = Decimal(str(min_notional))
        self._alert_manager = alert_manager or AlertManager()
        self._log = get_logger(__name__)

        self._cash = self._initial_balance
        self._positions: dict[str, Position] = {}
        self._trade_history: list[PaperTradeExecution] = []
        self._trade_id_seq = 1

    @property
    def cash(self) -> Decimal:
        """Efectivo disponible en quote currency (USDT)."""
        return self._cash

    @property
    def balance(self) -> Decimal:
        """Alias para el efectivo disponible."""
        return self._cash

    @property
    def positions(self) -> dict[str, Position]:
        """Diccionario de posiciones activas indexadas por símbolo."""
        return dict(self._positions)

    @property
    def trade_history(self) -> list[PaperTradeExecution]:
        """Historial de operaciones completadas."""
        return list(self._trade_history)

    def is_in_position(self, symbol: str) -> bool:
        """Verifica si existe una posición activa para el símbolo."""
        return symbol.upper() in self._positions

    def get_position(self, symbol: str) -> Position | None:
        """Obtiene la posición activa para un símbolo, o None."""
        return self._positions.get(symbol.upper())

    def get_equity(self, current_prices: dict[str, Decimal] | None = None) -> Decimal:
        """Calcula el patrimonio total (cash + valor de mercado de posiciones activas)."""
        prices = current_prices or {}
        positions_value = Decimal("0")
        for sym, pos in self._positions.items():
            mark_price = prices.get(sym, pos.entry_price)
            if isinstance(mark_price, float):
                raise TypeError(f"Floats no permitidos en precios de mercado: {mark_price!r}")
            positions_value += pos.qty * Decimal(str(mark_price))
        return self._cash + positions_value

    def get_state(self, current_prices: dict[str, Decimal] | None = None) -> VirtualBrokerState:
        """Retorna un snapshot inmutable del estado del broker."""
        total_pnl = sum((t.net_pnl for t in self._trade_history), Decimal("0"))
        return VirtualBrokerState(
            cash=self._cash,
            equity=self.get_equity(current_prices),
            open_positions_count=len(self._positions),
            total_trades_count=len(self._trade_history),
            total_realized_pnl=total_pnl,
        )

    def open_position(
        self,
        symbol: str,
        side: SignalType | str,
        entry_price: Decimal,
        qty: Decimal,
        stop_loss: Decimal,
        take_profit: Decimal,
        timestamp: datetime | None = None,
        reason: str = "",
    ) -> Position:
        """Abre una posición simulada con validación de fondos, slippage y fees."""
        # Validación de tipos
        for name, val in [
            ("entry_price", entry_price),
            ("qty", qty),
            ("stop_loss", stop_loss),
            ("take_profit", take_profit),
        ]:
            if isinstance(val, float):
                raise TypeError(f"Floats no permitidos en open_position: {name}={val!r}")

        sym = symbol.upper()
        if sym in self._positions:
            raise ValueError(
                f"Ya existe una posición abierta para {sym}. Ciérrela antes de abrir una nueva."
            )

        price_dec = Decimal(str(entry_price))
        qty_dec = Decimal(str(qty))
        sl_dec = Decimal(str(stop_loss))
        tp_dec = Decimal(str(take_profit))
        ts = timestamp or datetime.now(UTC).replace(tzinfo=None)

        if qty_dec <= Decimal("0") or price_dec <= Decimal("0"):
            raise ValueError("El precio y la cantidad deben ser estrictamente positivos.")

        # Slippage de entrada desfavorable
        exec_entry_price = price_dec * (Decimal("1.0") + self._slippage_pct)
        notional = qty_dec * exec_entry_price

        if notional < self._min_notional:
            raise ValueError(
                f"El notional ${notional:.2f} es inferior al mínimo requerido ${self._min_notional:.2f}"
            )

        entry_fee = notional * self._fee_rate
        total_cost = notional + entry_fee

        if self._cash < total_cost:
            self._alert_manager.trigger_alert(
                event="PAPER_TRADE_INSUFFICIENT_FUNDS",
                message=f"Fondos insuficientes para {sym}: requerido ${total_cost:.2f}, disponible ${self._cash:.2f}",
                symbol=sym,
                required_usd=str(total_cost),
                available_usd=str(self._cash),
            )
            raise ValueError(
                f"Fondos insuficientes: requerido ${total_cost:.4f}, disponible ${self._cash:.4f}"
            )

        # Deducción de fondos
        self._cash -= total_cost
        initial_risk = qty_dec * abs(exec_entry_price - sl_dec)

        pos = Position(
            symbol=sym,
            entry_price=exec_entry_price,
            qty=qty_dec,
            stop_loss=sl_dec,
            take_profit=tp_dec,
            entry_time=ts,
            initial_risk_usd=initial_risk,
        )
        self._positions[sym] = pos

        self._log.info(
            "paper_trading.position_opened",
            symbol=sym,
            entry_price=str(exec_entry_price),
            qty=str(qty_dec),
            notional=str(notional),
            stop_loss=str(sl_dec),
            take_profit=str(tp_dec),
        )

        self._alert_manager.trigger_alert(
            event="PAPER_TRADE_ENTRY",
            message=f"🟢 Apertura simulada {sym}: {qty_dec} @ ${exec_entry_price:.4f} USDT (Notional: ${notional:.2f}, SL: ${sl_dec:.4f}, TP: ${tp_dec:.4f})",
            symbol=sym,
            price=str(exec_entry_price),
            qty=str(qty_dec),
            notional=str(notional),
            stop_loss=str(sl_dec),
            take_profit=str(tp_dec),
            reason=reason,
        )

        return pos

    def close_position(
        self,
        symbol: str,
        exit_price: Decimal,
        exit_reason: str = "MANUAL_CLOSE",
        timestamp: datetime | None = None,
        reason: str = "",
    ) -> PaperTradeExecution | None:
        """Cierra una posición activa, liquida PnL, aplica slippage/fees y notifica."""
        if isinstance(exit_price, float):
            raise TypeError(f"Floats no permitidos en close_position: exit_price={exit_price!r}")

        sym = symbol.upper()
        pos = self._positions.pop(sym, None)
        if pos is None:
            self._log.warning("paper_trading.close_nonexistent", symbol=sym)
            return None

        raw_exit_price = Decimal(str(exit_price))
        ts = timestamp or datetime.now(UTC).replace(tzinfo=None)

        # Slippage de salida desfavorable
        exec_exit_price = raw_exit_price * (Decimal("1.0") - self._slippage_pct)

        gross_revenue = pos.qty * exec_exit_price
        exit_fee = gross_revenue * self._fee_rate
        net_revenue = gross_revenue - exit_fee

        entry_notional = pos.qty * pos.entry_price
        entry_fee = entry_notional * self._fee_rate
        gross_pnl = gross_revenue - entry_notional
        total_fees = entry_fee + exit_fee
        net_pnl = gross_pnl - total_fees
        net_pnl_pct = (
            (net_pnl / entry_notional) * Decimal("100")
            if entry_notional > Decimal("0")
            else Decimal("0")
        )

        # Retornar capital y PnL neto al saldo
        self._cash += net_revenue

        trade = PaperTradeExecution(
            trade_id=self._trade_id_seq,
            symbol=sym,
            side="BUY",
            entry_time=pos.entry_time,
            exit_time=ts,
            entry_price=pos.entry_price,
            exit_price=exec_exit_price,
            qty=pos.qty,
            notional=entry_notional,
            stop_loss=pos.stop_loss,
            take_profit=pos.take_profit,
            gross_pnl=gross_pnl,
            total_fees=total_fees,
            net_pnl=net_pnl,
            net_pnl_pct=net_pnl_pct,
            exit_reason=exit_reason,
            reason=reason or (f"Closed via {exit_reason}"),
        )
        self._trade_id_seq += 1
        self._trade_history.append(trade)

        self._log.info(
            "paper_trading.position_closed",
            symbol=sym,
            exit_price=str(exec_exit_price),
            exit_reason=exit_reason,
            net_pnl=str(net_pnl),
            net_pnl_pct=str(net_pnl_pct),
        )

        alert_event = (
            "PAPER_TRADE_STOP_LOSS"
            if exit_reason == "STOP_LOSS"
            else "PAPER_TRADE_TAKE_PROFIT"
            if exit_reason == "TAKE_PROFIT"
            else "PAPER_TRADE_EXIT"
        )
        icon = "🔴" if net_pnl < Decimal("0") else "🟢"
        self._alert_manager.trigger_alert(
            event=alert_event,
            message=(
                f"{icon} Cierre simulado {sym} [{exit_reason}]: {pos.qty} @ ${exec_exit_price:.4f} USDT | "
                f"Net PnL: ${net_pnl:+.4f} USDT ({net_pnl_pct:+.2f}%) | Saldo: ${self._cash:.2f} USDT"
            ),
            symbol=sym,
            exit_price=str(exec_exit_price),
            net_pnl=str(net_pnl),
            net_pnl_pct=str(net_pnl_pct),
            exit_reason=exit_reason,
            total_fees=str(total_fees),
            remaining_balance=str(self._cash),
        )

        return trade

    def execute_signal(
        self,
        signal: TradeSignal,
        current_price: Decimal | None = None,
    ) -> Position | PaperTradeExecution | None:
        """Ejecuta una señal cuantitativa (BUY/SELL) en la simulación."""
        sym = signal.symbol.upper()
        target_price = current_price if current_price is not None else signal.price
        if isinstance(target_price, float):
            raise TypeError(f"Floats no permitidos en precios de señal: {target_price!r}")

        price_dec = Decimal(str(target_price))

        if signal.signal_type == SignalType.BUY:
            if sym in self._positions:
                self._log.debug("paper_trading.signal_ignored_already_in_pos", symbol=sym)
                return self._positions[sym]

            if signal.stop_loss is None or signal.take_profit is None:
                self._log.warning("paper_trading.buy_signal_missing_sl_tp", symbol=sym)
                return None

            # Calcular tamaño de posición
            if signal.suggested_qty is not None and signal.suggested_qty > Decimal("0"):
                qty = signal.suggested_qty
            else:
                # Money Management defensivo: 2.5% de riesgo
                dollar_risk = self._cash * Decimal("0.025")
                stop_dist = abs(price_dec - signal.stop_loss)
                if stop_dist <= Decimal("0"):
                    return None
                qty = dollar_risk / stop_dist
                notional = qty * price_dec
                if notional < self._min_notional:
                    min_qty = self._min_notional / price_dec
                    if (min_qty * stop_dist) <= (self._cash * Decimal("0.06")) and (
                        min_qty * price_dec
                    ) <= self._cash:
                        qty = min_qty
                    else:
                        qty = Decimal("0")
                elif notional > self._cash:
                    qty = self._cash / price_dec

            if qty <= Decimal("0"):
                self._log.warning("paper_trading.qty_zero_or_not_viable", symbol=sym)
                return None

            try:
                return self.open_position(
                    symbol=sym,
                    side=SignalType.BUY,
                    entry_price=price_dec,
                    qty=qty,
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit,
                    timestamp=signal.timestamp,
                    reason=signal.reason,
                )
            except Exception as exc:
                self._log.error("paper_trading.open_failed", symbol=sym, error=str(exc))
                return None

        elif signal.signal_type == SignalType.SELL:
            if sym in self._positions:
                return self.close_position(
                    symbol=sym,
                    exit_price=price_dec,
                    exit_reason="SIGNAL_SELL",
                    timestamp=signal.timestamp,
                    reason=signal.reason,
                )
            return None

        return None

    def process_candle(
        self,
        candle: HistoricalCandle,
        signal: TradeSignal | None = None,
        symbol: str = "SOLUSDT",
    ) -> list[PaperTradeExecution]:
        """Procesa una vela entrante: evalúa SL/TP intrabarra y luego aplica señales."""
        sym = symbol.upper()
        closed_trades: list[PaperTradeExecution] = []

        # 1. Chequeo intrabarra de posición activa
        pos = self._positions.get(sym)
        if pos is not None:
            sl_hit = candle.low <= pos.stop_loss
            tp_hit = candle.high >= pos.take_profit

            if sl_hit or tp_hit:
                if sl_hit and tp_hit:
                    # En caso de coincidencia intrabarra extrema, conservadurismo: Stop Loss primero
                    raw_exit = pos.stop_loss
                    reason = "STOP_LOSS"
                elif sl_hit:
                    raw_exit = pos.stop_loss
                    reason = "STOP_LOSS"
                else:
                    raw_exit = pos.take_profit
                    reason = "TAKE_PROFIT"

                trade = self.close_position(
                    symbol=sym,
                    exit_price=raw_exit,
                    exit_reason=reason,
                    timestamp=candle.timestamp,
                )
                if trade:
                    closed_trades.append(trade)

        # 2. Evaluación de señal si no estamos en posición
        if sym not in self._positions and signal is not None and signal.symbol.upper() == sym:
            self.execute_signal(signal, current_price=candle.close)

        return closed_trades

    def reset(self, initial_balance: Decimal | None = None) -> None:
        """Reinicia el estado del broker a sus valores iniciales."""
        if initial_balance is not None:
            if isinstance(initial_balance, float):
                raise TypeError(
                    f"Floats no permitidos en reset: initial_balance={initial_balance!r}"
                )
            self._initial_balance = Decimal(str(initial_balance))

        self._cash = self._initial_balance
        self._positions.clear()
        self._trade_history.clear()
        self._trade_id_seq = 1
        self._log.info("paper_trading.broker_reset", balance=str(self._cash))
