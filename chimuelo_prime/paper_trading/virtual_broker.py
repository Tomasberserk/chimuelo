"""Módulo de Paper Trading y Broker Virtual para Chimuelo Prime.

Implementa un broker simulado determinista con aritmética Decimal pura,
soporte para micro-cuentas ($25.00 USDT iniciales), slippage, comisiones,
gestión intrabarra de Stop Loss y Take Profit, y despacho de alertas
estructuradas a través de `AlertManager`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.exchange_config.logger import get_logger
from chimuelo_prime.orchestrator.monitoring import AlertManager
from chimuelo_prime.paper_trading.decision_models import (
    PaperFill,
    PaperOrder,
    PaperPosition,
    ensure_utc_aware,
)
from chimuelo_prime.paper_trading.persistence import BasePersistenceBackend
from chimuelo_prime.strategies.models import Position, SignalType, TradeSignal


class RealCredentialsDetectedError(Exception):
    """Lanzada cuando se intenta inicializar el VirtualBroker con claves de API reales."""


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
        initial_cash: Decimal | None = None,
        fee_rate: Decimal = Decimal("0.001"),
        slippage_pct: Decimal = Decimal("0.0005"),
        min_notional: Decimal = Decimal("5.00"),
        alert_manager: AlertManager | None = None,
        persistence: BasePersistenceBackend | None = None,
        db_engine: Any = None,
        db_url: str | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
        **kwargs: Any,
    ) -> None:
        # HARD KILL SWITCH
        if api_key is not None or api_secret is not None:
            raise RealCredentialsDetectedError(
                "SEGURIDAD CRÍTICA: VirtualBroker no acepta credenciales de exchange reales. "
                "El modo Paper Trading opera exclusivamente en un sandbox simulado."
            )

        start_bal = initial_cash if initial_cash is not None else initial_balance
        # Validación estricta contra floats en inicialización
        for name, val in [
            ("initial_balance", start_bal),
            ("fee_rate", fee_rate),
            ("slippage_pct", slippage_pct),
            ("min_notional", min_notional),
        ]:
            if isinstance(val, float):
                raise TypeError(
                    f"Floats no permitidos en configuración de VirtualBroker: {name}={val!r}"
                )

        self._initial_balance = Decimal(str(start_bal))
        self._fee_rate = Decimal(str(fee_rate))
        self._slippage_pct = Decimal(str(slippage_pct))
        self._min_notional = Decimal(str(min_notional))
        self._alert_manager = alert_manager or AlertManager()
        self._persistence = persistence
        self._db_engine = db_engine
        if db_url and not self._db_engine:
            from chimuelo_prime.grid_state.database import build_engine
            self._db_engine = build_engine(db_url)
        self._log = get_logger(__name__)

        self._cash = self._initial_balance
        self._positions: dict[str, Position] = {}
        self._open_positions: dict[str, PaperPosition] = {}
        self._trade_history: list[PaperTradeExecution] = []
        self._trade_id_seq = 1

        if self._db_engine:
            self._init_db_engine()

        if self._persistence:
            self._restore_open_positions()

    def _init_db_engine(self) -> None:
        from sqlalchemy import text
        with self._db_engine.connect() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS paper_trades (
                        trade_id INTEGER PRIMARY KEY,
                        symbol VARCHAR(20),
                        side VARCHAR(10),
                        entry_time DATETIME,
                        exit_time DATETIME,
                        entry_price NUMERIC(20,8),
                        exit_price NUMERIC(20,8),
                        qty NUMERIC(20,8),
                        notional NUMERIC(20,8),
                        stop_loss NUMERIC(20,8),
                        take_profit NUMERIC(20,8),
                        gross_pnl NUMERIC(20,8),
                        total_fees NUMERIC(20,8),
                        net_pnl NUMERIC(20,8),
                        net_pnl_pct NUMERIC(20,8),
                        exit_reason VARCHAR(30),
                        reason TEXT
                    )
                    """
                )
            )
            conn.commit()
            res = conn.execute(text("SELECT * FROM paper_trades ORDER BY trade_id"))
            for r in res.mappings():
                e_time = datetime.fromisoformat(r["entry_time"]) if isinstance(r["entry_time"], str) else r["entry_time"]
                x_time = datetime.fromisoformat(r["exit_time"]) if isinstance(r["exit_time"], str) else r["exit_time"]
                t = PaperTradeExecution(
                    trade_id=r["trade_id"],
                    symbol=r["symbol"],
                    side=r["side"],
                    entry_time=e_time,
                    exit_time=x_time,
                    entry_price=Decimal(str(r["entry_price"])),
                    exit_price=Decimal(str(r["exit_price"])),
                    qty=Decimal(str(r["qty"])),
                    notional=Decimal(str(r["notional"])),
                    stop_loss=Decimal(str(r["stop_loss"])),
                    take_profit=Decimal(str(r["take_profit"])),
                    gross_pnl=Decimal(str(r["gross_pnl"])),
                    total_fees=Decimal(str(r["total_fees"])),
                    net_pnl=Decimal(str(r["net_pnl"])),
                    net_pnl_pct=Decimal(str(r["net_pnl_pct"])),
                    exit_reason=r["exit_reason"],
                    reason=r["reason"] or "",
                )
                self._trade_history.append(t)
                self._trade_id_seq = max(self._trade_id_seq, r["trade_id"] + 1)
            self._cash += sum((t.net_pnl for t in self._trade_history), Decimal("0"))

    def is_in_position(self, symbol: str) -> bool:
        """Indica si el broker mantiene una posición activa para el par dado."""
        return symbol.upper() in self._positions or symbol.upper() in self._open_positions

    @property
    def cash(self) -> Decimal:
        """Efectivo disponible en quote currency (USDT)."""
        return self._cash

    @property
    def current_cash(self) -> Decimal:
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

    def _restore_open_positions(self) -> None:
        if not self._persistence:
            return
        persisted_open = self._persistence.get_open_positions()
        for p in persisted_open:
            self._open_positions[p.symbol] = p

    def get_open_position(self, symbol: str) -> PaperPosition | None:
        return self._open_positions.get(symbol)

    def get_open_positions_count(self) -> int:
        return len(self._open_positions) + len(self._positions)

    def get_total_exposure_usd(self) -> Decimal:
        return sum(
            (p.fill_price * p.quantity for p in self._open_positions.values()),
            Decimal("0"),
        ) + sum((p.cost for p in self._positions.values()), Decimal("0"))

    def get_total_exposure(self) -> Decimal:
        return self.get_total_exposure_usd()

    def get_equity(self, current_prices: dict[str, Decimal] | None = None) -> Decimal:
        """Calcula el patrimonio neto total a precio de mercado (Mark-to-Market)."""
        prices = current_prices or {}
        equity = self._cash

        for sym, pos in self._positions.items():
            price = prices.get(sym, pos.entry_price)
            if isinstance(price, float):
                raise TypeError(f"Floats no permitidos en precios de valuación: {price!r}")
            price_dec = Decimal(str(price))
            pos_value = pos.qty * price_dec
            equity += pos_value

        for sym, p_pos in self._open_positions.items():
            price = prices.get(sym, p_pos.fill_price)
            price_dec = Decimal(str(price))
            pos_value = p_pos.quantity * price_dec
            equity += pos_value

        return equity

    def get_state(self, current_prices: dict[str, Decimal] | None = None) -> VirtualBrokerState:
        """Retorna un snapshot inmutable del estado del VirtualBroker."""
        equity = self.get_equity(current_prices)
        total_pnl = sum((t.net_pnl for t in self._trade_history), Decimal("0"))
        return VirtualBrokerState(
            cash=self._cash,
            equity=equity,
            open_positions_count=self.get_open_positions_count(),
            total_trades_count=len(self._trade_history),
            total_realized_pnl=total_pnl,
        )

    def execute_paper_order(
        self,
        decision_id: str,
        symbol: str,
        timestamp: datetime,
        signal_price: Decimal,
        stop_loss: Decimal,
        take_profit: Decimal,
        quantity: Decimal,
        risk_pct_used: Decimal,
    ) -> tuple[PaperOrder, PaperFill, PaperPosition]:
        """Ejecuta una orden virtual canónica para Strategy C con atomicidad transaccional."""
        utc_ts = ensure_utc_aware(timestamp)
        sym = symbol.upper()

        if sym in self._open_positions or sym in self._positions:
            raise ValueError(f"Ya existe una posición abierta en {sym}. Imposible abrir nueva posición.")

        notional_signal = signal_price * quantity
        if notional_signal < self._min_notional:
            raise ValueError(f"Orden por debajo del mínimo notional (${self._min_notional}): ${notional_signal}")

        order_id = f"ord_{uuid.uuid4().hex[:12]}"
        order = PaperOrder(
            order_id=order_id,
            decision_id=decision_id,
            symbol=sym,
            side="BUY",
            timestamp=utc_ts,
            requested_price=signal_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            quantity=quantity,
            risk_pct_used=risk_pct_used,
        )

        fill_price = signal_price * (Decimal("1.0") + self._slippage_pct)
        notional_fill = fill_price * quantity
        fee_entry = notional_fill * self._fee_rate

        fill_id = f"fill_{uuid.uuid4().hex[:12]}"
        fill = PaperFill(
            fill_id=fill_id,
            order_id=order_id,
            decision_id=decision_id,
            symbol=sym,
            timestamp=utc_ts,
            signal_price=signal_price,
            fill_price=fill_price,
            slippage_pct=self._slippage_pct,
            quantity=quantity,
            fee_usd=fee_entry,
            fee_rate=self._fee_rate,
        )

        position_id = f"pos_{uuid.uuid4().hex[:12]}"
        position = PaperPosition(
            position_id=position_id,
            symbol=sym,
            status="OPEN",
            entry_time=utc_ts,
            entry_signal_price=signal_price,
            fill_price=fill_price,
            slippage_pct=self._slippage_pct,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            fee_entry=fee_entry,
        )

        if self._persistence:
            self._persistence.atomic_save_order_fill_position(order, fill, position)

        self._open_positions[sym] = position
        self._cash -= (notional_fill + fee_entry)
        return order, fill, position

    def process_candle_for_exits(
        self, symbol: str, candle: HistoricalCandle
    ) -> PaperPosition | None:
        """Evalúa si una vela horaria activa el Take Profit o Stop Loss de la posición abierta del símbolo."""
        sym = symbol.upper()
        if sym not in self._open_positions:
            return None

        pos = self._open_positions[sym]
        exit_price: Decimal | None = None
        exit_reason: str | None = None

        # Prioridad absoluta a Stop Loss en caso de brecha intrabarra
        if candle.low <= pos.stop_loss:
            exit_price = pos.stop_loss
            exit_reason = "STOP_LOSS"
        elif candle.high >= pos.take_profit:
            exit_price = pos.take_profit
            exit_reason = "TAKE_PROFIT"

        if exit_price is not None and exit_reason is not None:
            exec_exit_price = exit_price * (Decimal("1.0") - self._slippage_pct)
            gross_revenue = pos.quantity * exec_exit_price
            fee_exit = gross_revenue * self._fee_rate
            net_revenue = gross_revenue - fee_exit

            entry_notional = pos.quantity * pos.fill_price
            gross_pnl = gross_revenue - entry_notional
            total_fees = pos.fee_entry + fee_exit
            net_pnl = gross_pnl - total_fees

            r_multiple = Decimal("0")
            initial_risk = abs(pos.fill_price - pos.stop_loss) * pos.quantity
            if initial_risk > Decimal("0"):
                r_multiple = net_pnl / initial_risk

            duration_hours = max(
                1, int((candle.timestamp - pos.entry_time).total_seconds() // 3600)
            )

            closed_pos = PaperPosition(
                position_id=pos.position_id,
                symbol=pos.symbol,
                status="CLOSED",
                entry_time=pos.entry_time,
                entry_signal_price=pos.entry_signal_price,
                fill_price=pos.fill_price,
                slippage_pct=pos.slippage_pct,
                quantity=pos.quantity,
                stop_loss=pos.stop_loss,
                take_profit=pos.take_profit,
                fee_entry=pos.fee_entry,
                exit_time=ensure_utc_aware(candle.timestamp),
                exit_price=exec_exit_price,
                exit_reason=exit_reason,
                fee_exit=fee_exit,
                gross_pnl=gross_pnl,
                net_pnl=net_pnl,
                r_multiple=r_multiple.quantize(Decimal("0.0001")),
                duration_hours=duration_hours,
            )

            if self._persistence:
                self._persistence.update_paper_position(closed_pos)
            del self._open_positions[sym]
            self._cash += net_revenue
            return closed_pos

        return None

    def get_position(self, symbol: str) -> Position | None:
        """Retorna la posición activa del par dado o None si está flat."""
        return self._positions.get(symbol.upper())

    def open_position(
        self,
        symbol: str,
        side: SignalType,
        entry_price: Decimal,
        qty: Decimal,
        stop_loss: Decimal,
        take_profit: Decimal,
        timestamp: datetime | None = None,
        reason: str = "",
    ) -> Position:
        """Abre una posición virtual con cálculo de slippage y comisiones (Legacy)."""
        sym = symbol.upper()
        if sym in self._positions or sym in self._open_positions:
            raise ValueError(f"Ya existe una posición abierta en {sym}")

        if any(
            isinstance(v, float)
            for v in [entry_price, qty, stop_loss, take_profit]
        ):
            raise TypeError("Floats no permitidos en open_position")

        entry_dec = Decimal(str(entry_price))
        qty_dec = Decimal(str(qty))
        sl_dec = Decimal(str(stop_loss))
        tp_dec = Decimal(str(take_profit))
        ts = timestamp or datetime.now(UTC).replace(tzinfo=None)

        exec_entry_price = entry_dec * (Decimal("1.0") + self._slippage_pct)
        notional = qty_dec * exec_entry_price
        fee = notional * self._fee_rate
        total_required = notional + fee

        if total_required > self._cash:
            self._alert_manager.trigger_alert(
                event="PAPER_TRADE_INSUFFICIENT_FUNDS",
                message=f"Saldo insuficiente para abrir {sym}",
                symbol=sym,
                required=str(total_required),
                available=str(self._cash),
            )
            raise ValueError(
                f"Fondos insuficientes: requerido=${total_required:.4f}, disponible=${self._cash:.4f}"
            )

        if notional < self._min_notional:
            raise ValueError(
                f"Notional inferior al mínimo requerido (${self._min_notional:.2f}): ${notional:.4f}"
            )

        self._cash -= total_required

        pos = Position(
            symbol=sym,
            entry_price=exec_entry_price,
            qty=qty_dec,
            stop_loss=sl_dec,
            take_profit=tp_dec,
            entry_time=ts,
            initial_risk_usd=abs(exec_entry_price - sl_dec) * qty_dec,
        )
        self._positions[sym] = pos

        self._alert_manager.trigger_alert(
            event="PAPER_TRADE_ENTRY",
            message=f"Apertura simulada {sym}: {qty_dec} @ ${exec_entry_price:.4f} USDT",
            symbol=sym,
            side="BUY",
            entry_price=str(exec_entry_price),
            qty=str(qty_dec),
            stop_loss=str(sl_dec),
            take_profit=str(tp_dec),
            notional=str(notional),
            remaining_balance=str(self._cash),
        )
        return pos

    def close_position(
        self,
        symbol: str,
        exit_price: Decimal,
        exit_reason: str = "MANUAL",
        timestamp: datetime | None = None,
        reason: str = "",
    ) -> PaperTradeExecution | None:
        """Cierra una posición abierta, calcula comisiones de salida y registra el trade (Legacy)."""
        sym = symbol.upper()
        pos = self._positions.pop(sym, None)
        if pos is None:
            return None

        raw_exit_price = Decimal(str(exit_price))
        ts = timestamp or datetime.now(UTC).replace(tzinfo=None)

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
            stop_loss=pos.stop_loss or Decimal("0"),
            take_profit=pos.take_profit or Decimal("0"),
            gross_pnl=gross_pnl,
            total_fees=total_fees,
            net_pnl=net_pnl,
            net_pnl_pct=net_pnl_pct,
            exit_reason=exit_reason,
            reason=reason or (f"Closed via {exit_reason}"),
        )
        self._trade_id_seq += 1
        self._trade_history.append(trade)

        if self._db_engine:
            from sqlalchemy import text
            with self._db_engine.connect() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO paper_trades (
                            trade_id, symbol, side, entry_time, exit_time, entry_price, exit_price,
                            qty, notional, stop_loss, take_profit, gross_pnl, total_fees, net_pnl,
                            net_pnl_pct, exit_reason, reason
                        ) VALUES (
                            :trade_id, :symbol, :side, :entry_time, :exit_time, :entry_price, :exit_price,
                            :qty, :notional, :stop_loss, :take_profit, :gross_pnl, :total_fees, :net_pnl,
                            :net_pnl_pct, :exit_reason, :reason
                        )
                        """
                    ),
                    {
                        "trade_id": trade.trade_id,
                        "symbol": trade.symbol,
                        "side": trade.side,
                        "entry_time": trade.entry_time,
                        "exit_time": trade.exit_time,
                        "entry_price": float(trade.entry_price),
                        "exit_price": float(trade.exit_price),
                        "qty": float(trade.qty),
                        "notional": float(trade.notional),
                        "stop_loss": float(trade.stop_loss),
                        "take_profit": float(trade.take_profit),
                        "gross_pnl": float(trade.gross_pnl),
                        "total_fees": float(trade.total_fees),
                        "net_pnl": float(trade.net_pnl),
                        "net_pnl_pct": float(trade.net_pnl_pct),
                        "exit_reason": trade.exit_reason,
                        "reason": trade.reason,
                    },
                )
                conn.commit()

        alert_event = (
            "PAPER_TRADE_STOP_LOSS"
            if exit_reason == "STOP_LOSS"
            else "PAPER_TRADE_TAKE_PROFIT"
            if exit_reason == "TAKE_PROFIT"
            else "PAPER_TRADE_EXIT"
        )
        self._alert_manager.trigger_alert(
            event=alert_event,
            message=f"Cierre simulado {sym} [{exit_reason}]: Net PnL ${net_pnl:+.4f}",
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
            if sym in self._positions or sym in self._open_positions:
                return self._positions.get(sym)

            if signal.stop_loss is None or signal.take_profit is None:
                return None

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
            except Exception:
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

        pos = self._positions.get(sym)
        if pos is not None:
            sl_hit = pos.stop_loss is not None and candle.low <= pos.stop_loss
            tp_hit = pos.take_profit is not None and candle.high >= pos.take_profit

            if sl_hit or tp_hit:
                if sl_hit and tp_hit:
                    raw_exit = pos.stop_loss or candle.low
                    reason = "STOP_LOSS"
                elif sl_hit:
                    raw_exit = pos.stop_loss or candle.low
                    reason = "STOP_LOSS"
                else:
                    raw_exit = pos.take_profit or candle.high
                    reason = "TAKE_PROFIT"

                trade = self.close_position(
                    symbol=sym,
                    exit_price=raw_exit,
                    exit_reason=reason,
                    timestamp=candle.timestamp,
                )
                if trade:
                    closed_trades.append(trade)

        if sym not in self._positions and sym not in self._open_positions and signal is not None and signal.symbol.upper() == sym:
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
        self._open_positions.clear()
        self._trade_history.clear()
        self._trade_id_seq = 1
