"""Tests unitarios para SignalStrategyBacktester (M6) y métricas cuantitativas."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.backtesting.strategy_engine import (
    SignalStrategyBacktester,
    TradeExecutionRecord,
)
from chimuelo_prime.strategies.base import BaseStrategy
from chimuelo_prime.strategies.models import SignalType, TradeSignal


class DummyStrategy(BaseStrategy):
    """Estrategia de prueba que dispara señales programadas."""

    def __init__(self, signals_map: dict[int, TradeSignal] | None = None) -> None:
        self._signals = signals_map or {}

    @property
    def name(self) -> str:
        return "DummyTestStrategy"

    def evaluate_candle(
        self,
        candles: list[HistoricalCandle],
        current_index: int,
    ) -> TradeSignal | None:
        return self._signals.get(current_index)


def _make_candle(
    idx: int,
    open_: Decimal,
    high: Decimal,
    low: Decimal,
    close: Decimal,
    vol: Decimal = Decimal("1000"),
) -> HistoricalCandle:
    return HistoricalCandle(
        timestamp=datetime(2024, 1, 1, 0, 0) + timedelta(hours=idx),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=vol,
    )


class TestSignalStrategyBacktester:
    """Pruebas del motor de simulación de estrategias cuantitativas."""

    def test_empty_candles_raises_value_error(self) -> None:
        strategy = DummyStrategy()
        backtester = SignalStrategyBacktester(strategy=strategy, candles=[])
        with pytest.raises(ValueError, match="No se proporcionaron velas"):
            backtester.run()

    def test_take_profit_execution_flow(self) -> None:
        # Vela 0: Genera señal BUY @ 100.0, SL=95.0, TP=110.0
        # Vela 1: High alcanza 112.0 -> Dispara Take Profit
        candles = [
            _make_candle(0, Decimal("99"), Decimal("101"), Decimal("98"), Decimal("100")),
            _make_candle(1, Decimal("100"), Decimal("112"), Decimal("99"), Decimal("111")),
        ]

        signal = TradeSignal(
            timestamp=candles[0].timestamp,
            symbol="SOLUSDT",
            signal_type=SignalType.BUY,
            price=Decimal("100.0"),
            stop_loss=Decimal("95.0"),
            take_profit=Decimal("110.0"),
            suggested_qty=Decimal("0.20"),  # $20 notional sobre $25
            reason="Test BUY signal",
        )

        strategy = DummyStrategy({0: signal})
        backtester = SignalStrategyBacktester(
            strategy=strategy,
            candles=candles,
            initial_cash=Decimal("25.00"),
            fee_rate=Decimal("0.001"),  # 0.1%
            slippage_pct=Decimal("0.001"),  # 0.1%
        )

        report = backtester.run()

        assert report.total_trades == 1
        assert report.winning_trades == 1
        assert report.losing_trades == 0
        assert report.win_rate_pct == Decimal("100")
        assert report.trades[0].exit_reason == "TAKE_PROFIT"
        assert report.trades[0].net_pnl > Decimal("0")

        # Entrada con slippage: 100.0 * 1.001 = 100.1
        # Salida con slippage: 110.0 * 0.999 = 109.89
        assert report.trades[0].entry_price == Decimal("100.10")
        assert report.trades[0].exit_price == Decimal("109.89")
        assert report.final_equity > report.initial_cash

    def test_stop_loss_execution_flow(self) -> None:
        # Vela 0: Genera señal BUY @ 100.0, SL=95.0, TP=115.0
        # Vela 1: Low cae a 93.0 -> Dispara Stop Loss
        candles = [
            _make_candle(0, Decimal("99"), Decimal("101"), Decimal("98"), Decimal("100")),
            _make_candle(1, Decimal("100"), Decimal("101"), Decimal("93"), Decimal("94")),
        ]

        signal = TradeSignal(
            timestamp=candles[0].timestamp,
            symbol="SOLUSDT",
            signal_type=SignalType.BUY,
            price=Decimal("100.0"),
            stop_loss=Decimal("95.0"),
            take_profit=Decimal("115.0"),
            suggested_qty=Decimal("0.20"),
            reason="Test BUY signal",
        )

        strategy = DummyStrategy({0: signal})
        backtester = SignalStrategyBacktester(
            strategy=strategy,
            candles=candles,
            initial_cash=Decimal("25.00"),
            fee_rate=Decimal("0.001"),
            slippage_pct=Decimal("0.001"),
        )

        report = backtester.run()

        assert report.total_trades == 1
        assert report.winning_trades == 0
        assert report.losing_trades == 1
        assert report.win_rate_pct == Decimal("0")
        assert report.trades[0].exit_reason == "STOP_LOSS"
        assert report.trades[0].net_pnl < Decimal("0")

        # Salida con slippage: 95.0 * 0.999 = 94.905
        assert report.trades[0].exit_price == Decimal("94.905")
        assert report.final_equity < report.initial_cash

    def test_intrabar_both_sl_and_tp_hit_prioritizes_sl(self) -> None:
        # Vela donde High >= 115 Y Low <= 95
        candles = [
            _make_candle(0, Decimal("99"), Decimal("101"), Decimal("98"), Decimal("100")),
            _make_candle(1, Decimal("100"), Decimal("120"), Decimal("90"), Decimal("105")),
        ]

        signal = TradeSignal(
            timestamp=candles[0].timestamp,
            symbol="SOLUSDT",
            signal_type=SignalType.BUY,
            price=Decimal("100.0"),
            stop_loss=Decimal("95.0"),
            take_profit=Decimal("115.0"),
            suggested_qty=Decimal("0.20"),
        )

        strategy = DummyStrategy({0: signal})
        backtester = SignalStrategyBacktester(strategy=strategy, candles=candles)
        report = backtester.run()

        # Debe elegir conservadoramente STOP_LOSS
        assert report.total_trades == 1
        assert report.trades[0].exit_reason == "STOP_LOSS"

    def test_end_of_data_closes_active_position(self) -> None:
        # Vela 0: Entra en posición
        # Vela 1: No toca SL ni TP -> Cierre forzoso al finalizar dataset
        candles = [
            _make_candle(0, Decimal("99"), Decimal("101"), Decimal("98"), Decimal("100")),
            _make_candle(1, Decimal("100"), Decimal("102"), Decimal("99"), Decimal("101")),
        ]

        signal = TradeSignal(
            timestamp=candles[0].timestamp,
            symbol="SOLUSDT",
            signal_type=SignalType.BUY,
            price=Decimal("100.0"),
            stop_loss=Decimal("90.0"),
            take_profit=Decimal("120.0"),
            suggested_qty=Decimal("0.20"),
        )

        strategy = DummyStrategy({0: signal})
        backtester = SignalStrategyBacktester(strategy=strategy, candles=candles)
        report = backtester.run()

        assert report.total_trades == 1
        assert report.trades[0].exit_reason == "END_OF_DATA"
        # Precio de salida con slippage sobre el cierre de la última vela (101.0)
        assert report.trades[0].exit_time == candles[1].timestamp

    def test_financial_metrics_consistency(self) -> None:
        # Ejecutar simulación con 2 trades: 1 ganador y 1 perdedor
        candles = [
            _make_candle(0, Decimal("100"), Decimal("102"), Decimal("98"), Decimal("100")),
            _make_candle(1, Decimal("100"), Decimal("112"), Decimal("99"), Decimal("111")),  # TP
            _make_candle(
                2, Decimal("110"), Decimal("111"), Decimal("108"), Decimal("110")
            ),  # BUY 2
            _make_candle(3, Decimal("110"), Decimal("111"), Decimal("100"), Decimal("102")),  # SL
        ]

        sig1 = TradeSignal(
            timestamp=candles[0].timestamp,
            symbol="SOLUSDT",
            signal_type=SignalType.BUY,
            price=Decimal("100.0"),
            stop_loss=Decimal("95.0"),
            take_profit=Decimal("110.0"),
            suggested_qty=Decimal("0.10"),
        )
        sig2 = TradeSignal(
            timestamp=candles[2].timestamp,
            symbol="SOLUSDT",
            signal_type=SignalType.BUY,
            price=Decimal("110.0"),
            stop_loss=Decimal("105.0"),
            take_profit=Decimal("120.0"),
            suggested_qty=Decimal("0.10"),
        )

        strategy = DummyStrategy({0: sig1, 2: sig2})
        backtester = SignalStrategyBacktester(
            strategy=strategy,
            candles=candles,
            initial_cash=Decimal("25.00"),
            fee_rate=Decimal("0.001"),
            slippage_pct=Decimal("0.0005"),
        )
        report = backtester.run()

        assert report.total_trades == 2
        assert report.winning_trades == 1
        assert report.losing_trades == 1
        assert report.win_rate_pct == Decimal("50")
        assert report.profit_factor > Decimal("0")
        assert len(report.timeseries) == 4
        assert report.total_fees_paid > Decimal("0")


class TestBacktestModelsPurity:
    """Verifica el rechazo de floats e inmutabilidad en modelos de backtesting."""

    def test_trade_record_rejects_floats(self) -> None:
        with pytest.raises(TypeError, match="Floats no permitidos"):
            TradeExecutionRecord(
                trade_id=1,
                symbol="SOLUSDT",
                entry_time=datetime(2024, 1, 1),
                exit_time=datetime(2024, 1, 2),
                entry_price=100.0,  # float
                exit_price=Decimal("110.0"),
                qty=Decimal("1.0"),
                notional=Decimal("100.0"),
                stop_loss=Decimal("95.0"),
                take_profit=Decimal("110.0"),
                gross_pnl=Decimal("10.0"),
                total_fees=Decimal("0.2"),
                net_pnl=Decimal("9.8"),
                net_pnl_pct=Decimal("9.8"),
                exit_reason="TAKE_PROFIT",
            )
