"""Live Runner y Shadow Mode Runner para ejecución en tiempo real de Strategy C."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from chimuelo_prime.backtesting.data_loader import HistoricalCandle, HistoricalDataLoader
from chimuelo_prime.exchange_config.logger import get_logger
from chimuelo_prime.paper_trading.decision_engine import (
    CandleNotClosedError,
    SingleDecisionEngine,
)
from chimuelo_prime.paper_trading.decision_models import (
    DecisionAction,
    DecisionObject,
    ensure_utc_aware,
)
from chimuelo_prime.paper_trading.persistence import (
    BasePersistenceBackend,
    SQLitePersistenceBackend,
)
from chimuelo_prime.paper_trading.risk_engine import PortfolioRiskEngine
from chimuelo_prime.paper_trading.virtual_broker import VirtualBroker
from chimuelo_prime.strategies.structural_breakout import StructuralBreakoutStrategy


class LivePaperRunner:
    """Orquestador para Live Paper Trading y Shadow Mode en tiempo real."""

    def __init__(
        self,
        symbols: list[str] = ["BTCUSDT", "SOLUSDT"],
        initial_cash: Decimal = Decimal("100.00"),
        persistence: BasePersistenceBackend | None = None,
        data_loader: HistoricalDataLoader | None = None,
        shadow_only: bool = False,
        validate_closed: bool = False,
    ) -> None:
        self._symbols = [s.upper() for s in symbols]
        self._shadow_only = shadow_only
        self._validate_closed = validate_closed
        self._log = get_logger(__name__)
        self._persistence = persistence or SQLitePersistenceBackend("data/live_paper.db")
        self._data_loader = data_loader or HistoricalDataLoader()

        self._risk_engine = PortfolioRiskEngine(initial_equity=initial_cash)
        self._broker = VirtualBroker(persistence=self._persistence, initial_cash=initial_cash)

        # Recuperación automática de RiskState si existe en persistencia
        self._restore_risk_state()

        # Motores por símbolo
        self._strategies: dict[str, StructuralBreakoutStrategy] = {}
        self._engines: dict[str, SingleDecisionEngine] = {}
        for s in self._symbols:
            strat = StructuralBreakoutStrategy(symbol=s)
            self._strategies[s] = strat
            self._engines[s] = SingleDecisionEngine(
                symbol=s,
                strategy=strat,
                risk_engine=self._risk_engine,
                persistence=self._persistence,
                virtual_broker=None if shadow_only else self._broker,
                validate_closed=validate_closed,
            )

        self._is_running = False

    def _restore_risk_state(self) -> None:
        """Restaura el estado de riesgo desde la base de datos persistida."""
        if not self._persistence:
            return
        last_state = self._persistence.get_latest_risk_state()
        if last_state:
            self._risk_engine.restore_state(
                equity=last_state["equity"],
                high_water_mark=last_state["high_water_mark"],
                daily_start_equity=last_state["daily_start_equity"],
                consecutive_losses=last_state["consecutive_losses"],
                current_state=last_state["current_state"],
                last_day=last_state.get("current_day"),
                cooldown_until=last_state.get("cooldown_until"),
            )
            self._log.info(
                "risk.state_restored",
                equity=str(last_state["equity"]),
                hwm=str(last_state["high_water_mark"]),
                state=last_state["current_state"].value,
                losses=last_state["consecutive_losses"],
            )

    @property
    def risk_engine(self) -> PortfolioRiskEngine:
        return self._risk_engine

    @property
    def broker(self) -> VirtualBroker:
        return self._broker

    def process_closed_hourly_candle(
        self,
        symbol: str,
        recent_1h_candles: list[HistoricalCandle],
        btc_daily_candles: list[HistoricalCandle],
    ) -> DecisionObject:
        """Procesa una vela horaria cerrada y ejecuta el ciclo completo."""
        sym = symbol.upper()
        if sym not in self._engines:
            raise ValueError(f"Símbolo no soportado: {sym}")

        strat = self._strategies[sym]
        strat.set_btc_daily_context(btc_daily_candles)
        strat.prepare_indicators(recent_1h_candles)

        engine = self._engines[sym]
        idx = len(recent_1h_candles) - 1
        current_candle = recent_1h_candles[idx]

        # 1. Si no es shadow_only, evaluar salidas de la posición abierta en este símbolo
        if not self._shadow_only:
            closed_pos = self._broker.process_candle_for_exits(sym, current_candle)
            if closed_pos and closed_pos.net_pnl is not None:
                self._risk_engine.record_trade_result(closed_pos.net_pnl, current_candle.timestamp)
                self._log.info(
                    "paper.position_closed",
                    symbol=sym,
                    exit_reason=closed_pos.exit_reason,
                    net_pnl=float(closed_pos.net_pnl),
                    r_multiple=float(closed_pos.r_multiple or 0),
                )

        # 2. Evaluar nueva decisión
        decision = engine.evaluate_bar(
            candles=recent_1h_candles,
            idx=idx,
            execute_paper=not self._shadow_only,
        )

        # 3. Telemetría Estructurada
        self._log_decision_telemetry(decision)
        return decision

    def _log_decision_telemetry(self, decision: DecisionObject) -> None:
        """Emite logs estructurados detallados."""
        self._log.info(
            "decision.evaluated",
            decision_id=decision.decision_id,
            symbol=decision.symbol,
            timestamp=decision.timestamp.isoformat(),
            action=decision.action.value,
            why_signal=decision.why_signal,
            why_allowed=decision.why_allowed,
            why_blocked=decision.why_blocked,
            data_hash=decision.data_snapshot_hash[:12],
            config_hash=decision.config_hash[:12],
        )
