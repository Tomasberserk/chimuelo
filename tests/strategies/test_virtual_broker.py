"""Tests unitarios exhaustivos para el broker virtual de Paper Trading (virtual_broker.py)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.orchestrator.monitoring import AlertManager
from chimuelo_prime.paper_trading.virtual_broker import (
    VirtualBroker,
    VirtualBrokerState,
)
from chimuelo_prime.strategies.models import SignalType, TradeSignal


@pytest.fixture
def mock_alert_manager() -> MagicMock:
    """Mock de AlertManager para verificar el despacho de alertas estructuradas."""
    manager = MagicMock(spec=AlertManager)
    return manager


class TestVirtualBrokerInit:
    """Pruebas de inicialización y pureza Decimal del VirtualBroker."""

    def test_default_initialization(self) -> None:
        broker = VirtualBroker()
        assert broker.cash == Decimal("25.00")
        assert broker.balance == Decimal("25.00")
        assert broker.positions == {}
        assert broker.trade_history == []
        assert broker.get_equity() == Decimal("25.00")

    def test_custom_balance_and_config(self) -> None:
        broker = VirtualBroker(
            initial_balance=Decimal("100.00"),
            fee_rate=Decimal("0.00075"),
            slippage_pct=Decimal("0.0002"),
            min_notional=Decimal("10.00"),
        )
        assert broker.cash == Decimal("100.00")
        assert broker._fee_rate == Decimal("0.00075")
        assert broker._slippage_pct == Decimal("0.0002")
        assert broker._min_notional == Decimal("10.00")

    def test_rejects_floats_in_init(self) -> None:
        with pytest.raises(TypeError, match="Floats no permitidos"):
            VirtualBroker(initial_balance=25.0)  # float

        with pytest.raises(TypeError, match="Floats no permitidos"):
            VirtualBroker(fee_rate=0.001)  # float

        with pytest.raises(TypeError, match="Floats no permitidos"):
            VirtualBroker(slippage_pct=0.0005)  # float

        with pytest.raises(TypeError, match="Floats no permitidos"):
            VirtualBroker(min_notional=5.0)  # float


class TestVirtualBrokerPositionOpening:
    """Pruebas para open_position y validaciones de capital."""

    def test_rejects_floats_in_open_position(self, mock_alert_manager: MagicMock) -> None:
        broker = VirtualBroker(alert_manager=mock_alert_manager)
        with pytest.raises(TypeError, match="Floats no permitidos"):
            broker.open_position(
                symbol="SOLUSDT",
                side="BUY",
                entry_price=100.0,  # float
                qty=Decimal("0.1"),
                stop_loss=Decimal("95.0"),
                take_profit=Decimal("110.0"),
            )

    def test_successful_position_opening(self, mock_alert_manager: MagicMock) -> None:
        broker = VirtualBroker(
            initial_balance=Decimal("25.00"),
            fee_rate=Decimal("0.001"),
            slippage_pct=Decimal("0.001"),
            alert_manager=mock_alert_manager,
        )

        # Entrada: price=100.0 -> exec_price = 100.0 * 1.001 = 100.10
        # qty=0.15 -> notional = 0.15 * 100.10 = 15.015 USDT
        # fee = 15.015 * 0.001 = 0.015015 USDT
        # total_cost = 15.030015 USDT
        # remaining cash = 25.00 - 15.030015 = 9.969985 USDT
        pos = broker.open_position(
            symbol="SOLUSDT",
            side=SignalType.BUY,
            entry_price=Decimal("100.00"),
            qty=Decimal("0.15"),
            stop_loss=Decimal("95.00"),
            take_profit=Decimal("110.00"),
            reason="Test Open",
        )

        assert broker.is_in_position("SOLUSDT")
        assert broker.get_position("SOLUSDT") == pos
        assert pos.entry_price == Decimal("100.10")
        assert pos.qty == Decimal("0.15")
        assert broker.cash < Decimal("25.00")

        # Verificar despacho de alerta
        mock_alert_manager.trigger_alert.assert_called_once()
        call_kwargs = mock_alert_manager.trigger_alert.call_args.kwargs
        assert call_kwargs["event"] == "PAPER_TRADE_ENTRY"
        assert call_kwargs["symbol"] == "SOLUSDT"

    def test_insufficient_funds_raises_and_alerts(self, mock_alert_manager: MagicMock) -> None:
        broker = VirtualBroker(initial_balance=Decimal("25.00"), alert_manager=mock_alert_manager)

        # Intentar operar $100 notional con balance de $25
        with pytest.raises(ValueError, match="Fondos insuficientes"):
            broker.open_position(
                symbol="SOLUSDT",
                side="BUY",
                entry_price=Decimal("100.00"),
                qty=Decimal("1.0"),  # $100 notional
                stop_loss=Decimal("95.00"),
                take_profit=Decimal("110.00"),
            )

        assert not broker.is_in_position("SOLUSDT")
        mock_alert_manager.trigger_alert.assert_called_once()
        call_kwargs = mock_alert_manager.trigger_alert.call_args.kwargs
        assert call_kwargs["event"] == "PAPER_TRADE_INSUFFICIENT_FUNDS"

    def test_min_notional_violation_raises(self, mock_alert_manager: MagicMock) -> None:
        broker = VirtualBroker(
            initial_balance=Decimal("25.00"),
            min_notional=Decimal("5.00"),
            alert_manager=mock_alert_manager,
        )

        # Qty = 0.01 @ $100 = $1.00 notional (< $5.00)
        with pytest.raises(ValueError, match="inferior al mínimo requerido"):
            broker.open_position(
                symbol="SOLUSDT",
                side="BUY",
                entry_price=Decimal("100.00"),
                qty=Decimal("0.01"),
                stop_loss=Decimal("95.00"),
                take_profit=Decimal("110.00"),
            )

    def test_duplicate_position_opening_raises(self, mock_alert_manager: MagicMock) -> None:
        broker = VirtualBroker(alert_manager=mock_alert_manager)
        broker.open_position(
            symbol="SOLUSDT",
            side="BUY",
            entry_price=Decimal("100.00"),
            qty=Decimal("0.10"),
            stop_loss=Decimal("95.00"),
            take_profit=Decimal("110.00"),
        )
        with pytest.raises(ValueError, match="Ya existe una posición abierta"):
            broker.open_position(
                symbol="SOLUSDT",
                side="BUY",
                entry_price=Decimal("100.00"),
                qty=Decimal("0.10"),
                stop_loss=Decimal("95.00"),
                take_profit=Decimal("110.00"),
            )


class TestVirtualBrokerPositionClosing:
    """Pruebas para close_position, liquidación de PnL y notificaciones."""

    def test_close_nonexistent_returns_none(self) -> None:
        broker = VirtualBroker()
        assert broker.close_position("BTCUSDT", exit_price=Decimal("50000")) is None

    def test_close_position_take_profit(self, mock_alert_manager: MagicMock) -> None:
        broker = VirtualBroker(
            initial_balance=Decimal("25.00"),
            fee_rate=Decimal("0.001"),
            slippage_pct=Decimal("0.001"),
            alert_manager=mock_alert_manager,
        )

        broker.open_position(
            symbol="SOLUSDT",
            side="BUY",
            entry_price=Decimal("100.00"),
            qty=Decimal("0.15"),
            stop_loss=Decimal("95.00"),
            take_profit=Decimal("110.00"),
        )

        mock_alert_manager.reset_mock()

        trade = broker.close_position(
            symbol="SOLUSDT",
            exit_price=Decimal("110.00"),
            exit_reason="TAKE_PROFIT",
        )

        assert trade is not None
        assert not broker.is_in_position("SOLUSDT")
        assert len(broker.trade_history) == 1
        assert trade.net_pnl > Decimal("0")
        assert trade.exit_reason == "TAKE_PROFIT"
        assert broker.cash > Decimal("25.00")

        # Verificar despacho de alerta TP
        mock_alert_manager.trigger_alert.assert_called_once()
        call_kwargs = mock_alert_manager.trigger_alert.call_args.kwargs
        assert call_kwargs["event"] == "PAPER_TRADE_TAKE_PROFIT"
        assert call_kwargs["exit_reason"] == "TAKE_PROFIT"

    def test_close_position_stop_loss(self, mock_alert_manager: MagicMock) -> None:
        broker = VirtualBroker(
            initial_balance=Decimal("25.00"),
            fee_rate=Decimal("0.001"),
            slippage_pct=Decimal("0.001"),
            alert_manager=mock_alert_manager,
        )

        broker.open_position(
            symbol="SOLUSDT",
            side="BUY",
            entry_price=Decimal("100.00"),
            qty=Decimal("0.15"),
            stop_loss=Decimal("95.00"),
            take_profit=Decimal("110.00"),
        )

        mock_alert_manager.reset_mock()

        trade = broker.close_position(
            symbol="SOLUSDT",
            exit_price=Decimal("95.00"),
            exit_reason="STOP_LOSS",
        )

        assert trade is not None
        assert trade.net_pnl < Decimal("0")
        assert trade.exit_reason == "STOP_LOSS"
        assert broker.cash < Decimal("25.00")

        mock_alert_manager.trigger_alert.assert_called_once()
        call_kwargs = mock_alert_manager.trigger_alert.call_args.kwargs
        assert call_kwargs["event"] == "PAPER_TRADE_STOP_LOSS"


class TestVirtualBrokerCandleFeedAndSignals:
    """Pruebas de ejecución secuencial vela por vela (process_candle) y señales."""

    def test_process_candle_intrabar_stop_loss(self, mock_alert_manager: MagicMock) -> None:
        broker = VirtualBroker(alert_manager=mock_alert_manager)

        # Abrir posición SOLUSDT @ 100 con SL @ 95, TP @ 110
        broker.open_position(
            symbol="SOLUSDT",
            side="BUY",
            entry_price=Decimal("100.00"),
            qty=Decimal("0.10"),
            stop_loss=Decimal("95.00"),
            take_profit=Decimal("110.00"),
        )

        # Vela donde low cae a 94.0 -> Dispara Stop Loss
        candle = HistoricalCandle(
            timestamp=datetime(2024, 1, 1, 12, 0),
            open=Decimal("99.0"),
            high=Decimal("101.0"),
            low=Decimal("94.0"),
            close=Decimal("96.0"),
            volume=Decimal("1000.0"),
        )

        closed = broker.process_candle(candle, symbol="SOLUSDT")
        assert len(closed) == 1
        assert closed[0].exit_reason == "STOP_LOSS"
        assert not broker.is_in_position("SOLUSDT")

    def test_process_candle_intrabar_take_profit(self, mock_alert_manager: MagicMock) -> None:
        broker = VirtualBroker(alert_manager=mock_alert_manager)

        broker.open_position(
            symbol="SOLUSDT",
            side="BUY",
            entry_price=Decimal("100.00"),
            qty=Decimal("0.10"),
            stop_loss=Decimal("95.00"),
            take_profit=Decimal("110.00"),
        )

        # Vela donde high sube a 111.0 -> Dispara Take Profit
        candle = HistoricalCandle(
            timestamp=datetime(2024, 1, 1, 12, 0),
            open=Decimal("102.0"),
            high=Decimal("111.0"),
            low=Decimal("101.0"),
            close=Decimal("108.0"),
            volume=Decimal("1000.0"),
        )

        closed = broker.process_candle(candle, symbol="SOLUSDT")
        assert len(closed) == 1
        assert closed[0].exit_reason == "TAKE_PROFIT"
        assert not broker.is_in_position("SOLUSDT")

    def test_process_candle_executes_signal_when_flat(self, mock_alert_manager: MagicMock) -> None:
        broker = VirtualBroker(alert_manager=mock_alert_manager)
        candle = HistoricalCandle(
            timestamp=datetime(2024, 1, 1, 12, 0),
            open=Decimal("100.0"),
            high=Decimal("101.0"),
            low=Decimal("99.0"),
            close=Decimal("100.5"),
            volume=Decimal("1000.0"),
        )

        signal = TradeSignal(
            timestamp=candle.timestamp,
            symbol="SOLUSDT",
            signal_type=SignalType.BUY,
            price=Decimal("100.5"),
            stop_loss=Decimal("96.0"),
            take_profit=Decimal("112.0"),
            suggested_qty=Decimal("0.10"),
        )

        closed = broker.process_candle(candle, signal=signal, symbol="SOLUSDT")
        assert closed == []
        assert broker.is_in_position("SOLUSDT")


class TestVirtualBrokerStateAndReset:
    """Pruebas de consulta de estado y reseteo del broker."""

    def test_equity_mark_to_market(self) -> None:
        broker = VirtualBroker(
            initial_balance=Decimal("25.00"), fee_rate=Decimal("0"), slippage_pct=Decimal("0")
        )
        broker.open_position(
            symbol="SOLUSDT",
            side="BUY",
            entry_price=Decimal("100.00"),
            qty=Decimal("0.10"),
            stop_loss=Decimal("90.00"),
            take_profit=Decimal("120.00"),
        )
        # Cash = 25 - 10 = 15 USDT
        # Mark price = 120 -> Position value = 0.10 * 120 = 12 USDT -> Equity = 15 + 12 = 27 USDT
        equity = broker.get_equity({"SOLUSDT": Decimal("120.00")})
        assert equity == Decimal("27.00")

    def test_equity_rejects_floats_in_prices(self) -> None:
        broker = VirtualBroker()
        broker.open_position(
            symbol="SOLUSDT",
            side="BUY",
            entry_price=Decimal("100.00"),
            qty=Decimal("0.10"),
            stop_loss=Decimal("90.00"),
            take_profit=Decimal("120.00"),
        )
        with pytest.raises(TypeError, match="Floats no permitidos"):
            broker.get_equity({"SOLUSDT": 120.0})  # float

    def test_get_state(self) -> None:
        broker = VirtualBroker()
        state = broker.get_state()
        assert isinstance(state, VirtualBrokerState)
        assert state.cash == Decimal("25.00")
        assert state.open_positions_count == 0
        assert state.total_trades_count == 0

    def test_reset(self) -> None:
        broker = VirtualBroker(initial_balance=Decimal("25.00"))
        broker.open_position(
            symbol="SOLUSDT",
            side="BUY",
            entry_price=Decimal("100.00"),
            qty=Decimal("0.10"),
            stop_loss=Decimal("90.00"),
            take_profit=Decimal("120.00"),
        )
        broker.close_position("SOLUSDT", exit_price=Decimal("110.00"))
        assert len(broker.trade_history) == 1

        broker.reset(initial_balance=Decimal("50.00"))
        assert broker.cash == Decimal("50.00")
        assert broker.positions == {}
        assert broker.trade_history == []


class TestVirtualBrokerDatabasePersistence:
    """Valida la persistencia y carga de operaciones en SQLite."""

    def test_persists_trade_to_db_and_reloads_on_new_instance(self) -> None:
        from chimuelo_prime.grid_state.database import build_engine

        engine = build_engine("sqlite:///:memory:")

        broker1 = VirtualBroker(
            initial_balance=Decimal("100.00"),
            db_engine=engine,
        )

        broker1.open_position(
            symbol="SOLUSDT",
            side="BUY",
            entry_price=Decimal("100.00"),
            qty=Decimal("0.5"),
            stop_loss=Decimal("90.00"),
            take_profit=Decimal("120.00"),
        )

        broker1.close_position(
            symbol="SOLUSDT",
            exit_price=Decimal("120.00"),
            exit_reason="TAKE_PROFIT",
        )

        assert len(broker1.trade_history) == 1

        # Crear una nueva instancia de broker conectada a la misma BD
        broker2 = VirtualBroker(
            initial_balance=Decimal("100.00"),
            db_engine=engine,
        )

        assert len(broker2.trade_history) == 1
        reloaded_trade = broker2.trade_history[0]
        assert reloaded_trade.symbol == "SOLUSDT"
        assert reloaded_trade.exit_reason == "TAKE_PROFIT"
        assert broker2.cash == broker1.cash

