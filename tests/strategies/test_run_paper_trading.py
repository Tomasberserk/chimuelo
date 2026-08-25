"""Tests exhaustivos para PaperTradingEngine y el ejecutor CLI run_paper_trading.py."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.exchange_config.exceptions import ExchangeUnreachableError
from chimuelo_prime.orchestrator.monitoring import AlertManager
from chimuelo_prime.paper_trading.engine import (
    PaperTradingConfig,
    PaperTradingCycleResult,
    PaperTradingEngine,
)
from chimuelo_prime.paper_trading.virtual_broker import VirtualBroker
from chimuelo_prime.strategies.models import Position, SignalType, TradeSignal
from chimuelo_prime.strategies.rsi_divergence import RSIDivergenceStrategy
from run_paper_trading import main, print_banner, run_paper_trading_service


def _build_raw_binance_klines(
    count: int = 210,
    base_price: float = 100.0,
) -> list[list[Any]]:
    """Genera datos crudos con el formato exacto devuelto por GET /api/v3/klines de Binance."""
    base_time_ms = 1704067200000  # 2024-01-01 00:00:00 UTC
    step_ms = 15 * 60 * 1000  # 15m
    klines = []
    for i in range(count):
        open_time = base_time_ms + (i * step_ms)
        close_time = open_time + step_ms - 1
        price = base_price + (i * 0.1)
        klines.append(
            [
                open_time,  # 0: Open time
                f"{price:.4f}",  # 1: Open
                f"{(price + 1.0):.4f}",  # 2: High
                f"{(price - 1.0):.4f}",  # 3: Low
                f"{(price + 0.5):.4f}",  # 4: Close
                "1500.0000",  # 5: Volume
                close_time,  # 6: Close time
                "150000.00",  # 7: Quote asset volume
                100,  # 8: Number of trades
                "800.0000",  # 9: Taker buy base asset volume
                "80000.00",  # 10: Taker buy quote asset volume
                "0",  # 11: Ignore
            ]
        )
    return klines


def _build_historical_candles(
    count: int = 210,
    base_price: Decimal = Decimal("100.0"),
) -> list[HistoricalCandle]:
    """Genera una lista de HistoricalCandle inmutables para tests."""
    base_time = datetime(2024, 1, 1, 0, 0)
    candles = []
    for i in range(count):
        price = base_price + Decimal(str(i * 0.1))
        candles.append(
            HistoricalCandle(
                timestamp=base_time + timedelta(minutes=15 * i),
                open=price,
                high=price + Decimal("1.0"),
                low=price - Decimal("1.0"),
                close=price + Decimal("0.5"),
                volume=Decimal("1500.0"),
            )
        )
    return candles


class TestPaperTradingConfig:
    """Verificación de invariantes y rechazo de tipos float en PaperTradingConfig."""

    def test_default_config(self) -> None:
        cfg = PaperTradingConfig()
        assert cfg.symbol == "SOLUSDT"
        assert cfg.interval == "15m"
        assert cfg.initial_balance == Decimal("25.00")
        assert cfg.fee_rate == Decimal("0.001")
        assert cfg.slippage_pct == Decimal("0.0005")
        assert cfg.min_notional == Decimal("5.00")
        assert cfg.poll_interval_seconds == 10.0
        assert cfg.report_interval_seconds == 3600.0
        assert cfg.candle_limit == 300

    def test_custom_valid_config(self) -> None:
        cfg = PaperTradingConfig(
            symbol="BTCUSDT",
            interval="1h",
            initial_balance=Decimal("50.00"),
            fee_rate=Decimal("0.00075"),
            slippage_pct=Decimal("0.0002"),
            min_notional=Decimal("10.00"),
            poll_interval_seconds=5.0,
            report_interval_seconds=1800.0,
            candle_limit=150,
        )
        assert cfg.symbol == "BTCUSDT"
        assert cfg.initial_balance == Decimal("50.00")
        assert cfg.poll_interval_seconds == 5.0

    def test_rejects_floats_in_financial_fields(self) -> None:
        with pytest.raises(TypeError, match="Floats no permitidos"):
            PaperTradingConfig(initial_balance=25.0)  # type: ignore[arg-type]

        with pytest.raises(TypeError, match="Floats no permitidos"):
            PaperTradingConfig(fee_rate=0.001)  # type: ignore[arg-type]

        with pytest.raises(TypeError, match="Floats no permitidos"):
            PaperTradingConfig(slippage_pct=0.0005)  # type: ignore[arg-type]

        with pytest.raises(TypeError, match="Floats no permitidos"):
            PaperTradingConfig(min_notional=5.0)  # type: ignore[arg-type]


class TestPaperTradingCycleResult:
    """Verificación del modelo de resultado de ciclo."""

    def test_cycle_result_structure(self) -> None:
        ts = datetime(2024, 1, 1, 12, 0)
        res = PaperTradingCycleResult(
            timestamp=ts,
            symbol="SOLUSDT",
            current_price=Decimal("105.50"),
            is_new_candle=True,
            cash=Decimal("25.00"),
            equity=Decimal("25.00"),
            status_message="Flat",
        )
        assert res.symbol == "SOLUSDT"
        assert res.current_price == Decimal("105.50")
        assert res.is_new_candle is True
        assert res.trades_closed == []
        assert res.active_position is None


class TestPaperTradingEngineFetchKlines:
    """Verificación de la descarga y parseo de Klines desde Binance."""

    def test_fetch_klines_success(self) -> None:
        raw_klines = _build_raw_binance_klines(count=5)
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = raw_klines
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response

        engine = PaperTradingEngine(session=mock_session)
        candles = engine.fetch_klines()

        assert len(candles) == 5
        assert isinstance(candles[0], HistoricalCandle)
        assert candles[0].open == Decimal("100.0000")
        assert candles[0].close == Decimal("100.5000")
        assert candles[0].volume == Decimal("1500.0000")

    def test_fetch_klines_timeout_raises_exchange_unreachable(self) -> None:
        mock_session = MagicMock()
        mock_session.get.side_effect = requests.exceptions.Timeout("Timeout")

        engine = PaperTradingEngine(session=mock_session)
        with pytest.raises(ExchangeUnreachableError, match="Timeout"):
            engine.fetch_klines()

    def test_fetch_klines_network_error_raises_exchange_unreachable(self) -> None:
        mock_session = MagicMock()
        mock_session.get.side_effect = requests.exceptions.ConnectionError("Connection refused")

        engine = PaperTradingEngine(session=mock_session)
        with pytest.raises(ExchangeUnreachableError, match="Error de red"):
            engine.fetch_klines()

    def test_fetch_klines_empty_response_raises_exchange_unreachable(self) -> None:
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response

        engine = PaperTradingEngine(session=mock_session)
        with pytest.raises(ExchangeUnreachableError, match="Respuesta inválida o vacía"):
            engine.fetch_klines()


class TestPaperTradingEngineStepAndEvaluation:
    """Verificación de la ejecución de ciclos step() en PaperTradingEngine."""

    def test_step_insufficient_candles_raises_value_error(self) -> None:
        raw_klines = _build_raw_binance_klines(count=1)
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = raw_klines
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response

        engine = PaperTradingEngine(session=mock_session)
        with pytest.raises(ValueError, match="Datos insuficientes"):
            engine.step()

    def test_step_first_run_no_signal_stays_flat(self) -> None:
        raw_klines = _build_raw_binance_klines(count=210)
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = raw_klines
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response

        alert_mgr = MagicMock(spec=AlertManager)
        engine = PaperTradingEngine(session=mock_session, alert_manager=alert_mgr)

        result = engine.step()

        assert result.symbol == "SOLUSDT"
        assert result.is_new_candle is True
        assert result.active_position is None
        assert result.trades_closed == []
        assert result.cash == Decimal("25.00")
        assert result.equity == Decimal("25.00")
        assert "Flat" in result.status_message

    def test_step_executes_buy_signal_and_alerts(self) -> None:
        raw_klines = _build_raw_binance_klines(count=210)
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = raw_klines
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response

        alert_mgr = MagicMock(spec=AlertManager)
        mock_strategy = MagicMock(spec=RSIDivergenceStrategy)
        mock_strategy.name = "MockStrategy"
        mock_strategy.calculate_position_size.return_value = Decimal("0.1")

        # Configurar señal de compra
        buy_signal = TradeSignal(
            timestamp=datetime(2024, 1, 1, 10, 0),
            symbol="SOLUSDT",
            signal_type=SignalType.BUY,
            price=Decimal("120.00"),
            stop_loss=Decimal("115.00"),
            take_profit=Decimal("132.50"),
            reason="Bullish Divergence",
            suggested_qty=Decimal("0.1"),
        )
        mock_strategy.evaluate_candle.return_value = buy_signal

        engine = PaperTradingEngine(
            session=mock_session,
            strategy=mock_strategy,
            alert_manager=alert_mgr,
        )

        result = engine.step()

        assert result.active_position is not None
        assert result.active_position.symbol == "SOLUSDT"
        assert result.active_position.stop_loss == Decimal("115.00")
        assert result.active_position.take_profit == Decimal("132.50")
        assert result.signal == buy_signal

        # Verificar que AlertManager recibió la alerta de entrada
        alert_events = [call.kwargs.get("event") for call in alert_mgr.trigger_alert.call_args_list]
        assert "PAPER_TRADE_ENTRY" in alert_events

    def test_step_intrabar_stop_loss_on_active_candle(self) -> None:
        """Verifica que si la vela en formación toca el SL, la posición se cierra inmediatamente."""
        raw_klines = _build_raw_binance_klines(count=210)
        # La vela en formación (última) tiene un low muy bajo que toca el SL
        raw_klines[-1][3] = "80.0000"  # Low = 80.0
        raw_klines[-1][4] = "85.0000"  # Close = 85.0

        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = raw_klines
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response

        alert_mgr = MagicMock(spec=AlertManager)
        broker = VirtualBroker(
            initial_balance=Decimal("25.00"),
            alert_manager=alert_mgr,
        )
        # Abrir posición previa manualmente
        broker.open_position(
            symbol="SOLUSDT",
            side=SignalType.BUY,
            entry_price=Decimal("100.00"),
            qty=Decimal("0.1"),
            stop_loss=Decimal("90.00"),
            take_profit=Decimal("125.00"),
        )

        engine = PaperTradingEngine(
            session=mock_session,
            broker=broker,
            alert_manager=alert_mgr,
        )

        result = engine.step()

        assert result.active_position is None
        assert len(result.trades_closed) == 1
        closed_trade = result.trades_closed[0]
        assert closed_trade.exit_reason == "STOP_LOSS"
        assert closed_trade.net_pnl < Decimal("0")

        # Verificar alerta de Stop Loss
        alert_events = [call.kwargs.get("event") for call in alert_mgr.trigger_alert.call_args_list]
        assert "PAPER_TRADE_STOP_LOSS" in alert_events

    def test_step_intrabar_take_profit_on_active_candle(self) -> None:
        """Verifica que si la vela en formación toca el TP, la posición se cierra inmediatamente."""
        raw_klines = _build_raw_binance_klines(count=210)
        # La vela en formación (última) tiene un high muy alto que toca el TP
        raw_klines[-1][2] = "130.0000"  # High = 130.0
        raw_klines[-1][4] = "128.0000"  # Close = 128.0

        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = raw_klines
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response

        alert_mgr = MagicMock(spec=AlertManager)
        broker = VirtualBroker(
            initial_balance=Decimal("25.00"),
            alert_manager=alert_mgr,
        )
        broker.open_position(
            symbol="SOLUSDT",
            side=SignalType.BUY,
            entry_price=Decimal("100.00"),
            qty=Decimal("0.1"),
            stop_loss=Decimal("90.00"),
            take_profit=Decimal("120.00"),
        )

        engine = PaperTradingEngine(
            session=mock_session,
            broker=broker,
            alert_manager=alert_mgr,
        )

        result = engine.step()

        assert result.active_position is None
        assert len(result.trades_closed) == 1
        closed_trade = result.trades_closed[0]
        assert closed_trade.exit_reason == "TAKE_PROFIT"
        assert closed_trade.net_pnl > Decimal("0")

        # Verificar alerta de Take Profit
        alert_events = [call.kwargs.get("event") for call in alert_mgr.trigger_alert.call_args_list]
        assert "PAPER_TRADE_TAKE_PROFIT" in alert_events

    def test_send_portfolio_summary_alert(self) -> None:
        alert_mgr = MagicMock(spec=AlertManager)
        broker = VirtualBroker(initial_balance=Decimal("25.00"), alert_manager=alert_mgr)
        engine = PaperTradingEngine(broker=broker, alert_manager=alert_mgr)

        engine.send_portfolio_summary(current_price=Decimal("120.00"))

        alert_events = [call.kwargs.get("event") for call in alert_mgr.trigger_alert.call_args_list]
        assert "PAPER_TRADE_PORTFOLIO_SUMMARY" in alert_events


class TestPaperTradingEngineStartAndLifecycle:
    """Verificación del bucle start(), control de errores y detención."""

    def test_start_finite_iterations(self) -> None:
        raw_klines = _build_raw_binance_klines(count=210)
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = raw_klines
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response

        alert_mgr = MagicMock(spec=AlertManager)
        cfg = PaperTradingConfig(poll_interval_seconds=0.01)
        engine = PaperTradingEngine(config=cfg, session=mock_session, alert_manager=alert_mgr)

        engine.start(max_iterations=3)

        assert engine.iteration_count == 3
        assert engine.is_running is False

        alert_events = [call.kwargs.get("event") for call in alert_mgr.trigger_alert.call_args_list]
        assert "PAPER_TRADE_STARTED" in alert_events
        assert "PAPER_TRADE_STOPPED" in alert_events

    def test_start_recovers_from_network_errors(self) -> None:
        raw_klines = _build_raw_binance_klines(count=210)
        mock_session = MagicMock()
        ok_response = MagicMock()
        ok_response.json.return_value = raw_klines
        ok_response.raise_for_status.return_value = None

        # Falla en 1ª llamada con Timeout, tiene éxito en 2ª llamada
        mock_session.get.side_effect = [
            requests.exceptions.Timeout("Timeout"),
            ok_response,
        ]

        alert_mgr = MagicMock(spec=AlertManager)
        cfg = PaperTradingConfig(poll_interval_seconds=0.01)
        engine = PaperTradingEngine(config=cfg, session=mock_session, alert_manager=alert_mgr)

        with patch("time.sleep", return_value=None):
            engine.start(max_iterations=1)

        assert engine.iteration_count == 1
        assert engine.is_running is False

    def test_consecutive_network_errors_triggers_network_alert(self) -> None:
        mock_session = MagicMock()
        mock_session.get.side_effect = requests.exceptions.ConnectionError("Offline")

        alert_mgr = MagicMock(spec=AlertManager)
        cfg = PaperTradingConfig(poll_interval_seconds=0.01)
        engine = PaperTradingEngine(config=cfg, session=mock_session, alert_manager=alert_mgr)

        with patch("time.sleep", return_value=None):
            with patch.object(engine, "stop") as mock_stop:
                # Simular bucle que se detiene tras 3 errores
                def side_effect_stop(*args: Any, **kwargs: Any) -> None:
                    if engine._consecutive_errors >= 3:
                        engine._is_running = False

                with patch("chimuelo_prime.paper_trading.engine.time.sleep", side_effect=side_effect_stop):
                    engine.start()

        alert_events = [call.kwargs.get("event") for call in alert_mgr.trigger_alert.call_args_list]
        assert "PAPER_TRADE_NETWORK_ERROR" in alert_events


class TestRunPaperTradingCli:
    """Verificación de las funciones CLI de run_paper_trading.py."""

    def test_print_banner(self, capsys: pytest.CaptureFixture[str]) -> None:
        cfg = PaperTradingConfig()
        print_banner(cfg, max_iterations=5)
        captured = capsys.readouterr().out
        assert "MOTOR DE PAPER TRADING EN VIVO" in captured
        assert "SOLUSDT" in captured
        assert "25.00 USDT" in captured

    def test_run_paper_trading_service_success(self) -> None:
        raw_klines = _build_raw_binance_klines(count=210)
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = raw_klines
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response

        mock_alert_mgr = MagicMock(spec=AlertManager)

        with patch("chimuelo_prime.paper_trading.engine.requests.Session", return_value=mock_session):
            with patch("time.sleep", return_value=None):
                exit_code = run_paper_trading_service(
                    symbol="SOLUSDT",
                    interval="15m",
                    initial_cash=Decimal("25.00"),
                    poll_interval=0.01,
                    max_iterations=1,
                    alert_manager=mock_alert_mgr,
                )

        assert exit_code == 0

    def test_main_cli_with_args(self) -> None:
        raw_klines = _build_raw_binance_klines(count=210)
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = raw_klines
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response

        test_args = [
            "--symbol",
            "SOLUSDT",
            "--interval",
            "15m",
            "--initial-cash",
            "25.00",
            "--poll-interval",
            "0.01",
            "--once",
        ]

        with patch("chimuelo_prime.paper_trading.engine.requests.Session", return_value=mock_session):
            with patch("time.sleep", return_value=None):
                with pytest.raises(SystemExit) as exc_info:
                    main(test_args)
                assert exc_info.value.code == 0
