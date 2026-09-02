"""Live Runner y Shadow Mode Runner para ejecución en tiempo real de Strategy C."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from chimuelo_prime.backtesting.data_loader import HistoricalCandle, HistoricalDataLoader
from chimuelo_prime.exchange_config.logger import get_logger
from chimuelo_prime.paper_trading.decision_engine import SingleDecisionEngine
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
    ) -> None:
        self._symbols = symbols
        self._shadow_only = shadow_only
        self._log = get_logger(__name__)
        self._persistence = persistence or SQLitePersistenceBackend("data/live_paper.db")
        self._data_loader = data_loader or HistoricalDataLoader()

        self._risk_engine = PortfolioRiskEngine(initial_equity=initial_cash)
        self._broker = VirtualBroker(persistence=self._persistence, initial_cash=initial_cash)

        # Motores por símbolo
        self._engines: dict[str, SingleDecisionEngine] = {}
        for s in symbols:
            strat = StructuralBreakoutStrategy(symbol=s)
            self._engines[s] = SingleDecisionEngine(
                strategy=strat,
                risk_engine=self._risk_engine,
                persistence=self._persistence,
                broker=None if shadow_only else self._broker,
            )

        self._is_running = False

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
        btc_4h_candles: list[HistoricalCandle] | None = None,
    ) -> DecisionObject:
        """Procesa una vela horaria cerrada y ejecuta el ciclo completo."""
        if symbol not in self._engines:
            raise ValueError(f"Símbolo no soportado: {symbol}")

        engine = self._engines[symbol]
        idx = len(recent_1h_candles) - 1
        current_candle = recent_1h_candles[idx]

        # 1. Si no es shadow_only, evaluar salidas de posiciones abiertas existentes
        if not self._shadow_only:
            closed_pos = self._broker.process_candle_for_exits(current_candle)
            if closed_pos and closed_pos.net_pnl is not None:
                self._risk_engine.record_trade_result(closed_pos.net_pnl, current_candle.timestamp)
                self._log.info(
                    "paper.position_closed",
                    symbol=symbol,
                    exit_reason=closed_pos.exit_reason,
                    net_pnl=float(closed_pos.net_pnl),
                    r_multiple=float(closed_pos.r_multiple or 0),
                )

        # 2. Evaluar nueva decisión
        decision, new_pos = engine.evaluate_bar(
            candles_1h=recent_1h_candles,
            idx=idx,
            btc_daily_candles=btc_daily_candles,
            btc_4h_candles=btc_4h_candles,
            execute_paper=not self._shadow_only,
        )

        # 3. Telemetría Estructurada
        self._log_decision_telemetry(decision, new_pos)
        return decision

    def _log_decision_telemetry(self, decision: DecisionObject, new_pos: Any | None) -> None:
        """Emite logs estructurados detallados."""
        self._log.info(
            "decision.evaluated",
            decision_id=decision.decision_id,
            symbol=decision.symbol,
            timestamp=decision.timestamp.isoformat(),
            action=decision.action.value,
            lifecycle=decision.lifecycle_event.value,
            why_signal=decision.why_signal,
            why_allowed=decision.why_allowed,
            why_blocked=decision.why_blocked,
            btc_macro=decision.regime.btc_daily_state,
            risk_state=decision.risk.current_state.value,
            equity=float(decision.risk.current_equity),
            daily_dd=float(decision.risk.daily_drawdown_pct),
            peak_dd=float(decision.risk.peak_to_trough_drawdown_pct),
            paper_position_opened=bool(new_pos is not None),
        )
