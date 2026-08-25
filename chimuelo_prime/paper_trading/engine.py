"""Motor de Ejecución de Paper Trading en Tiempo Real para Chimuelo Prime.

Responsabilidades:
    - Conectarse al API público de Binance para descargar velas recientes (Klines) en tiempo real.
    - Discriminar velas cerradas vs. la vela en formación (intrabarra).
    - Evaluar la estrategia cuantitativa de divergencia RSI (`RSIDivergenceStrategy`) en cada vela cerrada.
    - Alimentar `VirtualBroker` para ejecutar señales de entrada y gestionar Stop Loss / Take Profit.
    - Monitorear intrabarra / tick por tick las posiciones activas en la vela en formación.
    - Despachar alertas instantáneas con emojis y contexto financiero a Telegram vía `AlertManager`.
    - Generar resúmenes periódicos del estado del portafolio ($25.00 USDT iniciales).
    - Manejar reconexión y tolerancia a fallos de red con retroceso exponencial (exponential backoff).
    - Ofrecer un ciclo no bloqueante (`step()`) para tests unitarios y un bucle de ejecución resiliente (`start()`).
"""

from __future__ import annotations

import signal
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

# Asegurar soporte de encoding UTF-8 en consolas Windows
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass

import requests
from pydantic import BaseModel, ConfigDict, Field, field_validator

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.exchange_config.exceptions import ExchangeUnreachableError
from chimuelo_prime.exchange_config.logger import get_logger
from chimuelo_prime.orchestrator.monitoring import AlertManager
from chimuelo_prime.paper_trading.virtual_broker import (
    PaperTradeExecution,
    VirtualBroker,
    VirtualBrokerState,
)
from chimuelo_prime.strategies.base import BaseStrategy
from chimuelo_prime.strategies.models import Position, SignalType, TradeSignal
from chimuelo_prime.strategies.rsi_divergence import RSIDivergenceStrategy


class PaperTradingConfig(BaseModel):
    """Configuración inmutable para la ejecución de Paper Trading en vivo."""

    model_config = ConfigDict(frozen=True, strict=True)

    symbol: str = Field(default="SOLUSDT", description="Símbolo del par a operar (ej. SOLUSDT)")
    interval: str = Field(default="15m", description="Intervalo de velas (ej. 15m, 1h)")
    initial_balance: Decimal = Field(
        default=Decimal("25.00"),
        description="Balance inicial de la micro-cuenta simulada en USDT",
    )
    fee_rate: Decimal = Field(
        default=Decimal("0.001"),
        description="Tasa de comisión simulada (0.1% Spot estándar)",
    )
    slippage_pct: Decimal = Field(
        default=Decimal("0.0005"),
        description="Slippage simulado por operación (0.05%)",
    )
    min_notional: Decimal = Field(
        default=Decimal("5.00"),
        description="Notional mínimo exigido por Binance ($5.00 USDT)",
    )
    poll_interval_seconds: float = Field(
        default=10.0,
        description="Intervalo de sondeo del mercado en segundos",
    )
    report_interval_seconds: float = Field(
        default=3600.0,
        description="Intervalo entre resúmenes periódicos de portafolio a Telegram en segundos",
    )
    candle_limit: int = Field(
        default=300,
        description="Número de velas recientes a descargar por ciclo para calcular indicadores",
    )
    base_url: str = Field(
        default="https://api.binance.com",
        description="URL base del API público de Binance",
    )
    request_timeout: float = Field(
        default=10.0,
        description="Timeout para peticiones HTTP en segundos",
    )

    @field_validator(
        "initial_balance",
        "fee_rate",
        "slippage_pct",
        "min_notional",
        mode="before",
    )
    @classmethod
    def reject_floats(cls, v: Any) -> Any:
        if isinstance(v, float):
            raise TypeError(f"Floats no permitidos en PaperTradingConfig: {v!r}")
        if v is not None and not isinstance(v, Decimal):
            return Decimal(str(v))
        return v


class PaperTradingCycleResult(BaseModel):
    """Resultado estructurado de un ciclo individual de sondeo y evaluación."""

    model_config = ConfigDict(frozen=True)

    timestamp: datetime = Field(description="Timestamp del ciclo de ejecución (UTC naive)")
    symbol: str = Field(description="Símbolo operado")
    current_price: Decimal = Field(description="Precio actual de mercado / último cierre")
    is_new_candle: bool = Field(default=False, description="Indica si se detectó una nueva vela cerrada")
    signal: TradeSignal | None = Field(default=None, description="Señal cuantitativa evaluada")
    trades_closed: list[PaperTradeExecution] = Field(
        default_factory=list,
        description="Operaciones cerradas en el ciclo",
    )
    active_position: Position | None = Field(
        default=None,
        description="Posición activa actualmente en el broker",
    )
    cash: Decimal = Field(description="Efectivo disponible en USDT")
    equity: Decimal = Field(description="Patrimonio total actual en USDT")
    status_message: str = Field(default="", description="Mensaje de estado legible")


class PaperTradingEngine:
    """Motor de ejecución de Paper Trading en tiempo real.

    Conecta con la API pública de Binance para obtener velas en tiempo real,
    evalúa la estrategia (default RSIDivergenceStrategy), alimenta el VirtualBroker,
    monitorea Stop Loss y Take Profit intrabarra / tick por tick, y despacha alertas
    formateadas a Telegram vía AlertManager.
    """

    def __init__(
        self,
        config: PaperTradingConfig | None = None,
        broker: VirtualBroker | None = None,
        strategy: BaseStrategy | None = None,
        alert_manager: AlertManager | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self._config = config or PaperTradingConfig()
        self._alert_manager = alert_manager or AlertManager()
        self._broker = broker or VirtualBroker(
            initial_balance=self._config.initial_balance,
            fee_rate=self._config.fee_rate,
            slippage_pct=self._config.slippage_pct,
            min_notional=self._config.min_notional,
            alert_manager=self._alert_manager,
        )
        self._strategy = strategy or RSIDivergenceStrategy(
            symbol=self._config.symbol,
            rsi_oversold_threshold=Decimal("42.0"),
            lookback_bars=35,
            volume_multiplier=Decimal("0.9"),
            risk_reward_ratio=Decimal("2.5"),
        )
        self._session = session or requests.Session()
        self._log = get_logger(__name__)

        self._is_running = False
        self._last_processed_candle_time: datetime | None = None
        self._last_report_time: float = 0.0
        self._consecutive_errors: int = 0
        self._iteration_count: int = 0
        self._last_cycle_result: PaperTradingCycleResult | None = None

    @property
    def config(self) -> PaperTradingConfig:
        """Configuración activa del motor."""
        return self._config

    @property
    def broker(self) -> VirtualBroker:
        """Instancia del VirtualBroker simulado."""
        return self._broker

    @property
    def strategy(self) -> BaseStrategy:
        """Estrategia cuantitativa en ejecución."""
        return self._strategy

    @property
    def alert_manager(self) -> AlertManager:
        """Instancia de AlertManager para notificaciones."""
        return self._alert_manager

    @property
    def is_running(self) -> bool:
        """Indica si el bucle de ejecución está activo."""
        return self._is_running

    @property
    def iteration_count(self) -> int:
        """Número de ciclos completados."""
        return self._iteration_count

    @property
    def last_cycle_result(self) -> PaperTradingCycleResult | None:
        """Resultado del último ciclo ejecutado."""
        return self._last_cycle_result

    def fetch_klines(self) -> list[HistoricalCandle]:
        """Descarga las últimas Klines desde la API pública de Binance.

        Returns:
            Lista de `HistoricalCandle` ordenada cronológicamente.

        Raises:
            ExchangeUnreachableError: Si la petición falla por timeout o error de red.
        """
        url = f"{self._config.base_url.rstrip('/')}/api/v3/klines"
        params: dict[str, str | int] = {
            "symbol": self._config.symbol.upper(),
            "interval": self._config.interval,
            "limit": self._config.candle_limit,
        }

        try:
            response = self._session.get(
                url,
                params=params,
                timeout=self._config.request_timeout,
            )
            response.raise_for_status()
        except requests.exceptions.Timeout as exc:
            raise ExchangeUnreachableError(
                f"Timeout ({self._config.request_timeout}s) descargando Klines de {self._config.symbol}"
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise ExchangeUnreachableError(
                f"Error de red descargando Klines de {self._config.symbol}: {exc}"
            ) from exc

        data = response.json()
        if not isinstance(data, list) or not data:
            raise ExchangeUnreachableError(
                f"Respuesta inválida o vacía de Binance para {self._config.symbol}: {data!r}"
            )

        candles: list[HistoricalCandle] = []
        for item in data:
            open_time_ms = int(item[0])
            dt = datetime.fromtimestamp(open_time_ms / 1000, tz=UTC).replace(tzinfo=None)
            candles.append(
                HistoricalCandle(
                    timestamp=dt,
                    open=Decimal(str(item[1])),
                    high=Decimal(str(item[2])),
                    low=Decimal(str(item[3])),
                    close=Decimal(str(item[4])),
                    volume=Decimal(str(item[5])),
                )
            )

        candles.sort(key=lambda c: c.timestamp)
        return candles

    def step(self) -> PaperTradingCycleResult:
        """Ejecuta un paso determinista del ciclo de Paper Trading.

        Flujo del ciclo:
        1. Descarga las velas más recientes de Binance.
        2. Discrimina velas cerradas vs. vela activa en formación.
        3. Si hay una nueva vela cerrada:
           a. Si hay posición abierta, evalúa SL/TP intrabarra con la vela cerrada.
           b. Si no hay posición abierta, evalúa la estrategia y aplica señales.
        4. Si hay una posición abierta activa, monitorea la vela en formación (intrabarra)
           para ejecución reactiva inmediata de SL / TP si el precio actual o extremos los tocan.
        5. Verifica si corresponde enviar un resumen periódico de portafolio a Telegram.
        6. Retorna un snapshot inmutable `PaperTradingCycleResult`.
        """
        now_ts = datetime.now(UTC).replace(tzinfo=None)
        candles = self.fetch_klines()

        if len(candles) < 2:
            raise ValueError(
                f"Datos insuficientes: se requieren al menos 2 velas, obtenidas {len(candles)}"
            )

        # En Binance, candles[:-1] son velas cerradas y candles[-1] es la vela en formación
        closed_candles = candles[:-1]
        active_candle = candles[-1]
        current_price = active_candle.close
        latest_closed_candle = closed_candles[-1]

        sym = self._config.symbol.upper()
        closed_trades: list[PaperTradeExecution] = []
        evaluated_signal: TradeSignal | None = None
        is_new_candle = False

        # Detectar si hay una nueva vela cerrada desde el último ciclo
        if (
            self._last_processed_candle_time is None
            or latest_closed_candle.timestamp > self._last_processed_candle_time
        ):
            is_new_candle = True
            self._log.debug(
                "paper_trading.new_closed_candle",
                symbol=sym,
                timestamp=str(latest_closed_candle.timestamp),
                close=str(latest_closed_candle.close),
            )

            # 1. Si estamos en posición, procesar la vela cerrada en el broker para chequear SL/TP
            if self._broker.is_in_position(sym):
                trades = self._broker.process_candle(
                    latest_closed_candle,
                    signal=None,
                    symbol=sym,
                )
                closed_trades.extend(trades)

            # 2. Si no estamos en posición (o si se cerró justo ahora), evaluar señal de estrategia
            if not self._broker.is_in_position(sym):
                # Requiere historial suficiente para EMA 200 y filtros
                if len(closed_candles) >= 200:
                    evaluated_signal = self._strategy.evaluate_candle(
                        closed_candles,
                        len(closed_candles) - 1,
                    )
                    if (
                        evaluated_signal
                        and evaluated_signal.signal_type == SignalType.BUY
                        and evaluated_signal.stop_loss
                        and evaluated_signal.take_profit
                    ):
                        self._log.info(
                            "paper_trading.signal_detected",
                            symbol=sym,
                            signal_type=str(evaluated_signal.signal_type),
                            price=str(evaluated_signal.price),
                            sl=str(evaluated_signal.stop_loss),
                            tp=str(evaluated_signal.take_profit),
                        )
                        self._broker.process_candle(
                            latest_closed_candle,
                            signal=evaluated_signal,
                            symbol=sym,
                        )

            self._last_processed_candle_time = latest_closed_candle.timestamp

        # 3. Monitoreo reactivo de la vela en formación (intrabarra) si hay posición abierta
        pos = self._broker.get_position(sym)
        if pos is not None:
            sl_hit = active_candle.low <= pos.stop_loss
            tp_hit = active_candle.high >= pos.take_profit

            if sl_hit or tp_hit:
                if sl_hit and tp_hit:
                    exit_price = pos.stop_loss
                    reason = "STOP_LOSS"
                elif sl_hit:
                    exit_price = pos.stop_loss
                    reason = "STOP_LOSS"
                else:
                    exit_price = pos.take_profit
                    reason = "TAKE_PROFIT"

                trade = self._broker.close_position(
                    symbol=sym,
                    exit_price=exit_price,
                    exit_reason=reason,
                    timestamp=active_candle.timestamp,
                    reason=f"Live intrabar hit: {reason}",
                )
                if trade:
                    closed_trades.append(trade)

        # 4. Chequeo de resumen periódico de portafolio
        current_time_epoch = time.time()
        if (
            self._last_report_time == 0.0
            or (current_time_epoch - self._last_report_time) >= self._config.report_interval_seconds
        ):
            self.send_portfolio_summary(current_price)
            self._last_report_time = current_time_epoch

        # 5. Consolidación del resultado del ciclo
        current_equity = self._broker.get_equity({sym: current_price})
        active_pos = self._broker.get_position(sym)

        status_desc = (
            f"En posición: {active_pos.qty} @ ${active_pos.entry_price:.4f}"
            if active_pos
            else "Flat (Sin posición)"
        )
        if closed_trades:
            status_desc += f" | {len(closed_trades)} trade(s) cerrado(s)"

        result = PaperTradingCycleResult(
            timestamp=now_ts,
            symbol=sym,
            current_price=current_price,
            is_new_candle=is_new_candle,
            signal=evaluated_signal,
            trades_closed=closed_trades,
            active_position=active_pos,
            cash=self._broker.cash,
            equity=current_equity,
            status_message=status_desc,
        )

        self._last_cycle_result = result
        return result

    def send_portfolio_summary(self, current_price: Decimal | None = None) -> None:
        """Genera y despacha un resumen estructurado del portafolio a Telegram."""
        sym = self._config.symbol.upper()
        prices = {sym: current_price} if current_price is not None else None
        state = self._broker.get_state(prices)
        active_pos = self._broker.get_position(sym)

        initial_bal = self._config.initial_balance
        total_pnl = state.total_realized_pnl
        total_return_pct = (
            ((state.equity - initial_bal) / initial_bal * Decimal("100"))
            if initial_bal > Decimal("0")
            else Decimal("0")
        )

        trades = self._broker.trade_history
        total_trades = len(trades)
        wins = sum(1 for t in trades if t.net_pnl > Decimal("0"))
        win_rate = (
            (Decimal(wins) / Decimal(total_trades) * Decimal("100"))
            if total_trades > 0
            else Decimal("0")
        )

        if active_pos:
            mark = current_price or active_pos.entry_price
            unrealized_pnl = active_pos.qty * (mark - active_pos.entry_price)
            unrealized_pct = (
                (unrealized_pnl / (active_pos.qty * active_pos.entry_price) * Decimal("100"))
                if active_pos.entry_price > Decimal("0")
                else Decimal("0")
            )
            pos_icon = "🟢" if unrealized_pnl >= Decimal("0") else "🔴"
            pos_info = (
                f"{pos_icon} LONG {active_pos.qty} @ ${active_pos.entry_price:.4f}\n"
                f"  • Precio Actual: `${mark:.4f} USDT`\n"
                f"  • PnL Flotante: `${unrealized_pnl:+.4f} USDT` ({unrealized_pct:+.2f}%)\n"
                f"  • Stop Loss: `${active_pos.stop_loss:.4f}` | Take Profit: `${active_pos.take_profit:.4f}`"
            )
        else:
            pos_info = "⚪ Sin posición abierta (Flat)"

        summary_msg = (
            f"📊 *[Resumen de Portafolio Paper Trading]*\n\n"
            f"• *Par:* `{sym}` ({self._config.interval})\n"
            f"• *Capital Inicial:* `${initial_bal:.2f} USDT`\n"
            f"• *Saldo Efectivo (Cash):* `${state.cash:.2f} USDT`\n"
            f"• *Patrimonio Total (Equity):* `${state.equity:.2f} USDT`\n"
            f"• *PnL Realizado Neto:* `${total_pnl:+.4f} USDT` ({total_return_pct:+.2f}%)\n"
            f"• *Trades Cerrados:* `{total_trades}` (Win Rate: `{win_rate:.1f}%`)\n\n"
            f"*Posición Actual:*\n{pos_info}"
        )

        self._alert_manager.trigger_alert(
            event="PAPER_TRADE_PORTFOLIO_SUMMARY",
            message=summary_msg,
            symbol=sym,
            cash=str(state.cash),
            equity=str(state.equity),
            total_realized_pnl=str(total_pnl),
            total_trades=str(total_trades),
            win_rate_pct=str(win_rate),
        )

    def start(self, max_iterations: int | None = None) -> None:
        """Inicia el bucle de Paper Trading en tiempo real.

        Args:
            max_iterations: Límite opcional de ciclos para tests o ejecuciones finitas.
        """
        self._is_running = True
        self._consecutive_errors = 0
        sym = self._config.symbol.upper()

        self._log.info(
            "paper_trading.started",
            symbol=sym,
            interval=self._config.interval,
            initial_balance=str(self._config.initial_balance),
            poll_interval=self._config.poll_interval_seconds,
        )

        self._alert_manager.trigger_alert(
            event="PAPER_TRADE_STARTED",
            message=(
                f"🚀 *Paper Trading Iniciado*\n\n"
                f"• Par: `{sym}`\n"
                f"• Intervalo: `{self._config.interval}`\n"
                f"• Capital Inicial: `${self._config.initial_balance:.2f} USDT`\n"
                f"• Estrategia: `{self._strategy.name}`"
            ),
            symbol=sym,
            initial_balance=str(self._config.initial_balance),
        )

        def _handle_signal(signum: int, frame: Any) -> None:
            self._log.info("paper_trading.interrupt_signal_received", signal=signum)
            self._is_running = False

        # Registrar manejadores de interrupción limpios si se ejecuta en hilo principal
        try:
            signal.signal(signal.SIGINT, _handle_signal)
            signal.signal(signal.SIGTERM, _handle_signal)
        except (ValueError, AttributeError):
            pass

        try:
            while self._is_running:
                if max_iterations is not None and self._iteration_count >= max_iterations:
                    break

                try:
                    result = self.step()
                    self._consecutive_errors = 0
                    self._iteration_count += 1

                    self._log.debug(
                        "paper_trading.cycle_completed",
                        cycle=self._iteration_count,
                        price=str(result.current_price),
                        equity=str(result.equity),
                        status=result.status_message,
                    )

                    # Si vamos a continuar, dormir el intervalo configurado
                    if self._is_running and (
                        max_iterations is None or self._iteration_count < max_iterations
                    ):
                        time.sleep(self._config.poll_interval_seconds)

                except (ExchangeUnreachableError, requests.RequestException) as exc:
                    self._consecutive_errors += 1
                    backoff = min(
                        30.0,
                        2.0 * (2 ** min(self._consecutive_errors - 1, 4)),
                    )
                    self._log.warning(
                        "paper_trading.network_error",
                        error=str(exc),
                        consecutive_errors=self._consecutive_errors,
                        retry_in_seconds=backoff,
                    )

                    if self._consecutive_errors == 3:
                        self._alert_manager.trigger_alert(
                            event="PAPER_TRADE_NETWORK_ERROR",
                            message=f"⚠️ Conexión degradada con Binance ({self._consecutive_errors} fallos consecutivos): {exc}",
                            symbol=sym,
                            consecutive_errors=str(self._consecutive_errors),
                        )

                    time.sleep(backoff)

                except KeyboardInterrupt:
                    self._log.info("paper_trading.keyboard_interrupt")
                    break

                except Exception as exc:
                    self._log.error("paper_trading.unexpected_cycle_error", error=str(exc))
                    self._alert_manager.trigger_alert(
                        event="PAPER_TRADE_ERROR",
                        message=f"❌ Error no controlado en ciclo de Paper Trading: {exc}",
                        symbol=sym,
                    )
                    time.sleep(self._config.poll_interval_seconds)

        finally:
            self.stop()

    def stop(self) -> None:
        """Detiene el motor de forma segura, consolidando el estado final y alertando."""
        if not self._is_running and self._iteration_count > 0:
            return

        self._is_running = False
        sym = self._config.symbol.upper()
        state = self._broker.get_state()

        self._log.info(
            "paper_trading.stopped",
            symbol=sym,
            final_cash=str(state.cash),
            final_equity=str(state.equity),
            total_realized_pnl=str(state.total_realized_pnl),
            total_trades=state.total_trades_count,
        )

        self._alert_manager.trigger_alert(
            event="PAPER_TRADE_STOPPED",
            message=(
                f"🛑 *Paper Trading Detenido*\n\n"
                f"• Par: `{sym}`\n"
                f"• Saldo Efectivo: `${state.cash:.2f} USDT`\n"
                f"• Patrimonio Final: `${state.equity:.2f} USDT`\n"
                f"• PnL Realizado: `${state.total_realized_pnl:+.4f} USDT`\n"
                f"• Total Trades: `{state.total_trades_count}`"
            ),
            symbol=sym,
            final_cash=str(state.cash),
            final_equity=str(state.equity),
            total_realized_pnl=str(state.total_realized_pnl),
            total_trades=str(state.total_trades_count),
        )
