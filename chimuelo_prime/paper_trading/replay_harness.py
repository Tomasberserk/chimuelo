"""Arnés de Replay Determinista para Validación de Paridad (Live == Replay)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.paper_trading.decision_engine import SingleDecisionEngine
from chimuelo_prime.paper_trading.decision_models import DecisionObject, ensure_utc_aware
from chimuelo_prime.paper_trading.persistence import (
    BasePersistenceBackend,
    SQLitePersistenceBackend,
)
from chimuelo_prime.paper_trading.risk_engine import PortfolioRiskEngine
from chimuelo_prime.paper_trading.virtual_broker import VirtualBroker
from chimuelo_prime.strategies.structural_breakout import StructuralBreakoutStrategy


class ReplayHarness:
    """Motor de Replay que reproduce feeds históricos y valida igualdad estricta con Live."""

    def __init__(
        self,
        symbol: str = "SOLUSDT",
        initial_cash: Decimal = Decimal("100.00"),
        db_path: str = "data/replay_test.db",
    ) -> None:
        self._symbol = symbol.upper()
        self._persistence = SQLitePersistenceBackend(db_path=db_path)
        self._risk_engine = PortfolioRiskEngine(initial_equity=initial_cash)
        self._strategy = StructuralBreakoutStrategy(symbol=self._symbol)
        self._broker = VirtualBroker(persistence=self._persistence, initial_cash=initial_cash)
        self._decision_engine = SingleDecisionEngine(
            symbol=self._symbol,
            strategy=self._strategy,
            risk_engine=self._risk_engine,
            persistence=self._persistence,
            virtual_broker=self._broker,
            validate_closed=False,
        )

    def run_replay(
        self,
        candles_1h: list[HistoricalCandle],
        btc_daily_candles: list[HistoricalCandle],
        execute_paper: bool = True,
    ) -> list[DecisionObject]:
        """Ejecuta la reproducción secuencial de velas barra a barra."""
        self._strategy.set_btc_daily_context(btc_daily_candles)
        self._strategy.prepare_indicators(candles_1h)

        decisions: list[DecisionObject] = []
        for idx in range(100, len(candles_1h)):
            candle = candles_1h[idx]

            # 1. Procesar salidas de posiciones abiertas en este símbolo
            if execute_paper:
                closed_pos = self._broker.process_candle_for_exits(self._symbol, candle)
                if closed_pos and closed_pos.net_pnl is not None:
                    self._risk_engine.record_trade_result(closed_pos.net_pnl, candle.timestamp)

            # 2. Evaluar nueva decisión
            decision = self._decision_engine.evaluate_bar(
                candles=candles_1h,
                idx=idx,
                execute_paper=execute_paper,
            )
            decisions.append(decision)

        return decisions

    @staticmethod
    def assert_decisions_equal(d_live: DecisionObject, d_replay: DecisionObject) -> None:
        """Verifica la igualdad estricta campo por campo (model_dump) entre dos DecisionObjects."""
        live_dump = d_live.model_dump()
        replay_dump = d_replay.model_dump()
        assert live_dump == replay_dump, f"Discrepancia en DecisionObject:\nLive: {live_dump}\nReplay: {replay_dump}"
