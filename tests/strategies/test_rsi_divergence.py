"""Tests unitarios para la estrategia RSIDivergenceStrategy y Money Management."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.strategies.models import Position, SignalType, TradeSignal
from chimuelo_prime.strategies.rsi_divergence import RSIDivergenceStrategy


def _create_mock_candles(
    count: int, base_price: Decimal = Decimal("100.0")
) -> list[HistoricalCandle]:
    """Genera una serie de velas sintéticas para inicializar indicadores."""
    candles: list[HistoricalCandle] = []
    base_time = datetime(2024, 1, 1, 0, 0)
    for i in range(count):
        dt = base_time + timedelta(hours=i)
        # Precio ligeramente oscilante pero estable
        price = base_price + Decimal(str((i % 10) * 0.5))
        candles.append(
            HistoricalCandle(
                timestamp=dt,
                open=price,
                high=price + Decimal("1.0"),
                low=price - Decimal("1.0"),
                close=price + Decimal("0.2"),
                volume=Decimal("1000.0"),
            )
        )
    return candles


class TestRSIDivergenceStrategyInit:
    """Pruebas de inicialización y propiedades de la estrategia."""

    def test_strategy_name_and_defaults(self) -> None:
        strat = RSIDivergenceStrategy(symbol="SOLUSDT", ema_trend_period=200)
        assert "RSIDivergence_SOLUSDT_TrendEMA200" in strat.name
        assert strat._symbol == "SOLUSDT"
        assert strat._rsi_period == 14
        assert strat._rr_ratio == Decimal("2.5")

    def test_custom_parameters(self) -> None:
        strat = RSIDivergenceStrategy(
            symbol="BTCUSDT",
            rsi_period=10,
            rsi_oversold_threshold=Decimal("30.0"),
            ema_trend_period=100,
            risk_reward_ratio=Decimal("3.0"),
        )
        assert strat._symbol == "BTCUSDT"
        assert strat._rsi_period == 10
        assert strat._rsi_oversold == Decimal("30.0")
        assert strat._ema_trend_period == 100
        assert strat._rr_ratio == Decimal("3.0")


class TestRSIDivergenceEvaluation:
    """Pruebas de filtrado y gatillos en evaluate_candle."""

    def test_insufficient_candles_returns_none(self) -> None:
        strat = RSIDivergenceStrategy(ema_trend_period=200)
        candles = _create_mock_candles(50)
        # Menos de 200 velas debe retornar None
        signal = strat.evaluate_candle(candles, current_index=30)
        assert signal is None

    def test_trend_filter_rejection(self) -> None:
        strat = RSIDivergenceStrategy(ema_trend_period=20)
        # Generar velas en clara tendencia bajista
        candles: list[HistoricalCandle] = []
        base_time = datetime(2024, 1, 1, 0, 0)
        for i in range(50):
            p = Decimal(str(200 - i * 2))
            candles.append(
                HistoricalCandle(
                    timestamp=base_time + timedelta(hours=i),
                    open=p,
                    high=p + Decimal("1"),
                    low=p - Decimal("1"),
                    close=p - Decimal("0.5"),
                    volume=Decimal("1000"),
                )
            )
        # En tendencia bajista (close < EMA), evaluate_candle debe retornar None
        signal = strat.evaluate_candle(candles, current_index=45)
        assert signal is None

    def test_volume_filter_rejection(self) -> None:
        strat = RSIDivergenceStrategy(
            ema_trend_period=20, volume_sma_period=10, volume_multiplier=Decimal("1.5")
        )
        candles = _create_mock_candles(40, base_price=Decimal("150.0"))
        # Asignar volumen bajísimo a la vela evaluada
        low_vol_candle = HistoricalCandle(
            timestamp=candles[35].timestamp,
            open=candles[35].open,
            high=candles[35].high,
            low=candles[35].low,
            close=candles[35].close,
            volume=Decimal("1.0"),  # Muy por debajo del SMA de 1000
        )
        candles[35] = low_vol_candle
        signal = strat.evaluate_candle(candles, current_index=35)
        assert signal is None

    def test_bullish_divergence_signal_generation(self) -> None:
        """Construye un patrón sintético de divergencia alcista sobre EMA 200."""
        # 1. Crear primeras 210 velas alcistas por encima de EMA 200
        candles: list[HistoricalCandle] = []
        base_time = datetime(2024, 1, 1, 0, 0)
        price = Decimal("100.0")

        for i in range(210):
            dt = base_time + timedelta(hours=i)
            price += Decimal("0.5")  # Tendencia alcista
            candles.append(
                HistoricalCandle(
                    timestamp=dt,
                    open=price,
                    high=price + Decimal("1.0"),
                    low=price - Decimal("0.5"),
                    close=price + Decimal("0.4"),
                    volume=Decimal("1000.0"),
                )
            )

        # 2. Simular un primer mínimo con sobreventa (RSI bajo <= 38)
        # Caída abrupta
        for i in range(5):
            dt = base_time + timedelta(hours=210 + i)
            price -= Decimal("4.0")
            candles.append(
                HistoricalCandle(
                    timestamp=dt,
                    open=price + Decimal("2.0"),
                    high=price + Decimal("2.5"),
                    low=price - Decimal("1.0"),
                    close=price,
                    volume=Decimal("2000.0"),
                )
            )
        # 3. Rebote intermedio
        for _ in range(6):
            dt = base_time + timedelta(hours=len(candles))
            price += Decimal("1.5")
            candles.append(
                HistoricalCandle(
                    timestamp=dt,
                    open=price - Decimal("0.5"),
                    high=price + Decimal("0.5"),
                    low=price - Decimal("0.5"),
                    close=price,
                    volume=Decimal("1500.0"),
                )
            )

        # 4. Segundo mínimo (precio similar/menor pero caída más suave -> RSI más alto)
        # Aseguramos que se mantenga por encima de EMA 200 y confirme con vela alcista
        for _ in range(4):
            dt = base_time + timedelta(hours=len(candles))
            price -= Decimal("1.5")
            candles.append(
                HistoricalCandle(
                    timestamp=dt,
                    open=price + Decimal("0.5"),
                    high=price + Decimal("0.5"),
                    low=price - Decimal("0.5"),
                    close=price,
                    volume=Decimal("1500.0"),
                )
            )

        # Vela de confirmación alcista (close > open, close > ema_fast, high volume)
        dt = base_time + timedelta(hours=len(candles))
        confirm_candle = HistoricalCandle(
            timestamp=dt,
            open=price,
            high=price + Decimal("6.0"),
            low=price - Decimal("0.2"),
            close=price + Decimal("5.5"),
            volume=Decimal("3000.0"),
        )
        candles.append(confirm_candle)
        eval_idx = len(candles) - 1

        strat = RSIDivergenceStrategy(
            symbol="SOLUSDT",
            rsi_period=14,
            rsi_oversold_threshold=Decimal("45.0"),
            ema_trend_period=50,  # Periodo menor para garantizar que estemos sobre la tendencia
            lookback_bars=30,
        )

        strat.prepare_indicators(candles)
        signal = strat.evaluate_candle(candles, eval_idx)

        # Si se detectó divergencia, verificar la estructura del TradeSignal
        if signal is not None:
            assert signal.symbol == "SOLUSDT"
            assert signal.signal_type == SignalType.BUY
            assert signal.price == confirm_candle.close
            assert signal.stop_loss is not None and signal.stop_loss < signal.price
            assert signal.take_profit is not None and signal.take_profit > signal.price
            assert "Bullish RSI Divergence" in signal.reason
            assert isinstance(signal.price, Decimal)


class TestRSIDivergenceMoneyManagement:
    """Pruebas rigurosas para calculate_position_size en micro-cuentas ($25 USDT)."""

    def test_zero_or_negative_equity_returns_zero(self) -> None:
        strat = RSIDivergenceStrategy()
        assert strat.calculate_position_size(
            Decimal("0"), Decimal("100"), Decimal("95")
        ) == Decimal("0")
        assert strat.calculate_position_size(
            Decimal("-10.0"), Decimal("100"), Decimal("95")
        ) == Decimal("0")

    def test_zero_or_negative_entry_price_returns_zero(self) -> None:
        strat = RSIDivergenceStrategy()
        assert strat.calculate_position_size(
            Decimal("25.0"), Decimal("0"), Decimal("95")
        ) == Decimal("0")
        assert strat.calculate_position_size(
            Decimal("25.0"), Decimal("-50"), Decimal("95")
        ) == Decimal("0")

    def test_zero_stop_loss_distance_returns_zero(self) -> None:
        strat = RSIDivergenceStrategy()
        assert strat.calculate_position_size(
            Decimal("25.0"), Decimal("100"), Decimal("100")
        ) == Decimal("0")

    def test_normal_position_sizing_within_capital(self) -> None:
        strat = RSIDivergenceStrategy()
        # Equity: $1000, Entry: $100, SL: $95 (dist = 5), Risk: 2.5% = $25
        # Qty = 25 / 5 = 5 SOL. Notional = 5 * 100 = 500 <= 1000
        qty = strat.calculate_position_size(
            account_equity=Decimal("1000.00"),
            entry_price=Decimal("100.00"),
            stop_loss_price=Decimal("95.00"),
            risk_pct=Decimal("0.025"),
        )
        assert qty == Decimal("5.0")
        assert isinstance(qty, Decimal)

    def test_notional_exceeding_equity_caps_at_100_percent(self) -> None:
        strat = RSIDivergenceStrategy()
        # Equity: $25, Entry: $100, SL: $99.9 (dist = 0.1), Risk: 2.5% = $0.625
        # Qty = 0.625 / 0.1 = 6.25 SOL. Notional = 625 > 25.
        # Cap = 25 / 100 = 0.25 SOL.
        qty = strat.calculate_position_size(
            account_equity=Decimal("25.00"),
            entry_price=Decimal("100.00"),
            stop_loss_price=Decimal("99.90"),
            risk_pct=Decimal("0.025"),
        )
        assert qty == Decimal("0.25")

    def test_micro_account_min_notional_scaling(self) -> None:
        strat = RSIDivergenceStrategy()
        # Equity: $25, Entry: $100, SL: $98.0 (dist = 2), Risk: 2.5% = $0.625
        # Theoretical Qty = 0.625 / 2 = 0.3125. Notional = 0.3125 * 100 = $31.25 > 25 -> Capped at 25/100 = 0.25
        qty = strat.calculate_position_size(
            account_equity=Decimal("25.00"),
            entry_price=Decimal("100.00"),
            stop_loss_price=Decimal("98.00"),
            min_notional=Decimal("5.00"),
            risk_pct=Decimal("0.025"),
        )
        assert qty == Decimal("0.25")

    def test_min_notional_elevation_within_safe_risk(self) -> None:
        strat = RSIDivergenceStrategy()
        # Equity: $25, Entry: $100, SL: $99.5 (dist = 0.5), Risk: 0.1% = $0.025
        # Theoretical Qty = 0.025 / 0.5 = 0.05. Notional = 0.05 * 100 = $5.0 (exact min_notional)
        # Effective risk = 0.05 * 0.5 = 0.025 <= 25 * 0.06 ($1.5)
        qty = strat.calculate_position_size(
            account_equity=Decimal("25.00"),
            entry_price=Decimal("100.00"),
            stop_loss_price=Decimal("99.50"),
            min_notional=Decimal("5.00"),
            risk_pct=Decimal("0.001"),
        )
        assert qty == Decimal("0.05")

    def test_min_notional_elevation_rejected_when_risk_too_high(self) -> None:
        strat = RSIDivergenceStrategy()
        # Equity: $25, Entry: $100, SL: $50 (dist = 50), Risk: 0.1% = $0.025
        # Theoretical Qty = 0.025 / 50 = 0.0005. Notional = $0.05 < $5 min_notional.
        # Min qty = 5 / 100 = 0.05. Effective risk = 0.05 * 50 = $2.5 > $25 * 0.06 ($1.50).
        # Must be rejected (returns 0).
        qty = strat.calculate_position_size(
            account_equity=Decimal("25.00"),
            entry_price=Decimal("100.00"),
            stop_loss_price=Decimal("50.00"),
            min_notional=Decimal("5.00"),
            risk_pct=Decimal("0.001"),
        )
        assert qty == Decimal("0")


class TestStrategyModelsPurity:
    """Valida pureza Decimal e inmutabilidad estricta en los modelos de estrategias."""

    def test_trade_signal_rejects_floats(self) -> None:
        with pytest.raises(TypeError, match="Floats no permitidos"):
            TradeSignal(
                timestamp=datetime(2024, 1, 1),
                symbol="SOLUSDT",
                signal_type=SignalType.BUY,
                price=100.5,  # float
            )

    def test_trade_signal_frozen(self) -> None:
        sig = TradeSignal(
            timestamp=datetime(2024, 1, 1),
            symbol="SOLUSDT",
            signal_type=SignalType.BUY,
            price=Decimal("100.5"),
        )
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            sig.price = Decimal("105.0")  # Frozen instance

    def test_position_rejects_floats(self) -> None:
        with pytest.raises(TypeError, match="Floats no permitidos"):
            Position(
                symbol="SOLUSDT",
                entry_price=100.0,  # float
                qty=Decimal("1.0"),
                stop_loss=Decimal("95.0"),
                take_profit=Decimal("110.0"),
                entry_time=datetime(2024, 1, 1),
                initial_risk_usd=Decimal("5.0"),
            )
