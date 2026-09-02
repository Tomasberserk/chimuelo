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
        self._symbol = symbol
        self._persistence = SQLitePersistenceBackend(db_path=db_path)
        self._risk_engine = PortfolioRiskEngine(initial_equity=initial_cash)
        self._strategy = StructuralBreakoutStrategy(symbol=symbol)
        self._broker = VirtualBroker(persistence=self._persistence, initial_cash=initial_cash)
        self._decision_engine = SingleDecisionEngine(
            strategy=self._strategy,
            risk_engine=self._risk_engine,
            persistence=self._persistence,
            broker=self._broker,
        )

    def run_replay(
        self,
        candles_1h: list[HistoricalCandle],
        btc_daily_candles: list[HistoricalCandle],
        btc_4h_candles: list[HistoricalCandle] | None = None,
        execute_paper: bool = True,
    ) -> list[DecisionObject]:
        """Ejecuta la reproducción secuencial de velas barra a barra."""
        decisions: list[DecisionObject] = []

        for idx in range(100, len(candles_1h)):
            candle = candles_1h[idx]

            # 1. Procesar salidas de posiciones abiertas existentes en esta vela
            if execute_paper:
                closed_pos = self._broker.process_candle_for_exits(candle)
                if closed_pos and closed_pos.net_pnl is not None:
                    self._risk_engine.record_trade_result(closed_pos.net_pnl, candle.timestamp)

            # 2. Evaluar nueva decisión
            decision, new_pos = self._decision_engine.evaluate_bar(
                candles_1h=candles_1h,
                idx=idx,
                btc_daily_candles=btc_daily_candles,
                btc_4h_candles=btc_4h_candles,
                execute_paper=execute_paper,
            )
            decisions.append(decision)

        return decisions

    @staticmethod
    def assert_decisions_equal(d_live: DecisionObject, d_replay: DecisionObject) -> None:
        """Verifica la igualdad estricta campo por campo entre dos DecisionObjects."""
        assert d_live.symbol == d_replay.symbol, f"Symbol mismatch: {d_live.symbol} != {d_replay.symbol}"
        assert d_live.timestamp == d_replay.timestamp, f"Timestamp mismatch: {d_live.timestamp} != {d_replay.timestamp}"
        assert d_live.strategy_version == d_replay.strategy_version
        assert d_live.config_hash == d_replay.config_hash, f"Config hash mismatch: {d_live.config_hash} != {d_replay.config_hash}"
        assert d_live.data_snapshot_hash == d_replay.data_snapshot_hash, "Data snapshot hash mismatch"
        assert d_live.action == d_replay.action, f"Action mismatch: {d_live.action} != {d_replay.action}"
        assert d_live.lifecycle_event == d_replay.lifecycle_event
        assert d_live.filters.all_gates_passed == d_replay.filters.all_gates_passed
        assert d_live.suggested_entry_price == d_replay.suggested_entry_price
        assert d_live.suggested_stop_loss == d_replay.suggested_stop_loss
        assert d_live.suggested_take_profit == d_replay.suggested_take_profit
        assert d_live.suggested_quantity == d_replay.suggested_quantity
