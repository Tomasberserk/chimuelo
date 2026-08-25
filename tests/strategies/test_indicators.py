"""Tests unitarios exhaustivos para el módulo de indicadores técnicos cuantitativos (indicators.py)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from chimuelo_prime.strategies.indicators import (
    calculate_atr,
    calculate_ema,
    calculate_rsi,
    calculate_sma,
    find_pivot_lows,
)


class TestCalculateSMA:
    """Pruebas para el cálculo de la Media Móvil Simple (SMA)."""

    def test_invalid_period_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="El periodo debe ser mayor a 0"):
            calculate_sma([Decimal("10"), Decimal("20")], period=0)
        with pytest.raises(ValueError, match="El periodo debe ser mayor a 0"):
            calculate_sma([Decimal("10"), Decimal("20")], period=-5)

    def test_series_shorter_than_period_returns_all_none(self) -> None:
        values = [Decimal("10"), Decimal("20"), Decimal("30")]
        result = calculate_sma(values, period=5)
        assert len(result) == 3
        assert result == [None, None, None]

    def test_exact_length_period(self) -> None:
        values = [Decimal("10"), Decimal("20"), Decimal("30")]
        result = calculate_sma(values, period=3)
        assert len(result) == 3
        assert result[0] is None
        assert result[1] is None
        assert result[2] == Decimal("20")
        assert isinstance(result[2], Decimal)

    def test_rolling_window_calculation(self) -> None:
        # Values: 10, 20, 30, 40, 50 with period 3
        # SMA[2] = (10 + 20 + 30) / 3 = 20
        # SMA[3] = (20 + 30 + 40) / 3 = 30
        # SMA[4] = (30 + 40 + 50) / 3 = 40
        values = [Decimal("10"), Decimal("20"), Decimal("30"), Decimal("40"), Decimal("50")]
        result = calculate_sma(values, period=3)
        assert result[0] is None
        assert result[1] is None
        assert result[2] == Decimal("20")
        assert result[3] == Decimal("30")
        assert result[4] == Decimal("40")

    def test_constant_series_preserves_constant_value(self) -> None:
        val = Decimal("142.50")
        values = [val] * 10
        result = calculate_sma(values, period=4)
        for i in range(3):
            assert result[i] is None
        for i in range(3, 10):
            assert result[i] == val


class TestCalculateEMA:
    """Pruebas para el cálculo de la Media Móvil Exponencial (EMA)."""

    def test_invalid_period_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="El periodo debe ser mayor a 0"):
            calculate_ema([Decimal("100")], period=0)
        with pytest.raises(ValueError, match="El periodo debe ser mayor a 0"):
            calculate_ema([Decimal("100")], period=-1)

    def test_series_shorter_than_period_returns_all_none(self) -> None:
        values = [Decimal("10"), Decimal("20")]
        result = calculate_ema(values, period=3)
        assert result == [None, None]

    def test_initial_value_is_sma(self) -> None:
        # Period 3: first EMA at index 2 is SMA of first 3 elements
        values = [Decimal("10"), Decimal("20"), Decimal("30"), Decimal("40")]
        result = calculate_ema(values, period=3)
        assert result[0] is None
        assert result[1] is None
        assert result[2] == Decimal("20")

    def test_subsequent_ema_formula(self) -> None:
        # period = 3 -> multiplier = 2 / (3 + 1) = 0.5
        # SMA_init (idx 2) = (10 + 20 + 30) / 3 = 20
        # EMA[3] = (40 * 0.5) + (20 * 0.5) = 20 + 10 = 30
        # EMA[4] = (60 * 0.5) + (30 * 0.5) = 30 + 15 = 45
        values = [Decimal("10"), Decimal("20"), Decimal("30"), Decimal("40"), Decimal("60")]
        result = calculate_ema(values, period=3)
        assert result[2] == Decimal("20")
        assert result[3] == Decimal("30")
        assert result[4] == Decimal("45")
        assert isinstance(result[4], Decimal)

    def test_constant_series(self) -> None:
        val = Decimal("50.0")
        values = [val] * 8
        result = calculate_ema(values, period=3)
        for i in range(2, 8):
            assert result[i] == val


class TestCalculateRSI:
    """Pruebas para el cálculo del Relative Strength Index (RSI)."""

    def test_invalid_period_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="El periodo del RSI debe ser mayor a 0"):
            calculate_rsi([Decimal("100")], period=0)

    def test_series_shorter_or_equal_to_period_returns_all_none(self) -> None:
        values = [Decimal("10"), Decimal("12"), Decimal("14")]
        result = calculate_rsi(values, period=3)
        assert result == [None, None, None]

    def test_pure_gains_yields_rsi_100(self) -> None:
        # Strictly increasing prices
        prices = [Decimal(str(100 + i * 5)) for i in range(20)]
        result = calculate_rsi(prices, period=14)
        assert result[14] == Decimal("100.0")
        assert result[19] == Decimal("100.0")
        assert isinstance(result[14], Decimal)

    def test_pure_losses_yields_rsi_near_zero(self) -> None:
        # Strictly decreasing prices
        prices = [Decimal(str(200 - i * 5)) for i in range(20)]
        result = calculate_rsi(prices, period=14)
        # With avg_gain = 0 and avg_loss > 0, rs = 0 -> 100 - (100 / 1) = 0
        assert result[14] == Decimal("0")
        assert result[19] == Decimal("0")

    def test_flat_prices_yields_rsi_50(self) -> None:
        # Zero gains and zero losses
        prices = [Decimal("150.00")] * 20
        result = calculate_rsi(prices, period=14)
        assert result[14] == Decimal("50.0")
        assert result[19] == Decimal("50.0")

    def test_mixed_prices_standard_range(self) -> None:
        # Oscillating prices
        prices = [
            Decimal("44.34"),
            Decimal("44.09"),
            Decimal("44.15"),
            Decimal("43.61"),
            Decimal("44.33"),
            Decimal("44.83"),
            Decimal("45.10"),
            Decimal("45.42"),
            Decimal("45.84"),
            Decimal("46.08"),
            Decimal("45.89"),
            Decimal("46.03"),
            Decimal("45.61"),
            Decimal("46.28"),
            Decimal("46.28"),
            Decimal("46.00"),
        ]
        result = calculate_rsi(prices, period=14)
        assert result[14] is not None
        assert Decimal("0") <= result[14] <= Decimal("100")
        assert result[15] is not None
        assert Decimal("0") <= result[15] <= Decimal("100")


class TestCalculateATR:
    """Pruebas para el cálculo del Average True Range (ATR)."""

    def test_mismatched_lengths_raises_value_error(self) -> None:
        highs = [Decimal("10"), Decimal("11")]
        lows = [Decimal("9")]
        closes = [Decimal("9.5"), Decimal("10.5")]
        with pytest.raises(ValueError, match="misma longitud"):
            calculate_atr(highs, lows, closes, period=14)

    def test_invalid_period_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="El periodo debe ser mayor a 0"):
            calculate_atr([Decimal("10")], [Decimal("9")], [Decimal("9.5")], period=0)

    def test_short_series_returns_all_none(self) -> None:
        highs = [Decimal("10"), Decimal("11")]
        lows = [Decimal("9"), Decimal("9.5")]
        closes = [Decimal("9.5"), Decimal("10.5")]
        result = calculate_atr(highs, lows, closes, period=3)
        assert result == [None, None]

    def test_constant_volatility_bars(self) -> None:
        # Every bar has High=105, Low=95, Close=100 (TR = 10 every bar)
        highs = [Decimal("105.0")] * 10
        lows = [Decimal("95.0")] * 10
        closes = [Decimal("100.0")] * 10
        result = calculate_atr(highs, lows, closes, period=5)
        for i in range(4):
            assert result[i] is None
        for i in range(4, 10):
            assert result[i] == Decimal("10.0")

    def test_gap_influences_true_range(self) -> None:
        # Bar 0: H=100, L=90, C=95
        # Bar 1: Gap up: H=120, L=110, C=115
        # TR for Bar 1: max(120 - 110 = 10, |120 - 95| = 25, |110 - 95| = 15) = 25
        # Period 2: ATR[1] = (TR0 + TR1) / 2 = (10 + 25) / 2 = 17.5
        highs = [Decimal("100"), Decimal("120")]
        lows = [Decimal("90"), Decimal("110")]
        closes = [Decimal("95"), Decimal("115")]
        result = calculate_atr(highs, lows, closes, period=2)
        assert result[0] is None
        assert result[1] == Decimal("17.5")


class TestFindPivotLows:
    """Pruebas para detección de pivotes mínimos (Swing Lows)."""

    def test_series_too_short_returns_empty(self) -> None:
        lows = [Decimal("10"), Decimal("5"), Decimal("10")]
        # Needs left(2) + right(2) + 1 = 5 bars
        pivots = find_pivot_lows(lows, left_bars=2, right_bars=2)
        assert pivots == []

    def test_clear_v_bottom_detected(self) -> None:
        # 5 bars: 10, 8, 4, 7, 9 -> Pivot at index 2 (val 4)
        lows = [Decimal("10"), Decimal("8"), Decimal("4"), Decimal("7"), Decimal("9")]
        pivots = find_pivot_lows(lows, left_bars=2, right_bars=2)
        assert len(pivots) == 1
        assert pivots[0] == (2, Decimal("4"))

    def test_monotonic_series_has_no_pivots(self) -> None:
        uptrend = [Decimal(str(10 + i)) for i in range(10)]
        assert find_pivot_lows(uptrend, left_bars=2, right_bars=2) == []

        downtrend = [Decimal(str(50 - i)) for i in range(10)]
        assert find_pivot_lows(downtrend, left_bars=2, right_bars=2) == []

    def test_multiple_pivots_detected(self) -> None:
        lows = [
            Decimal("15"),
            Decimal("12"),
            Decimal("5"),
            Decimal("10"),
            Decimal("14"),  # Pivot at idx 2
            Decimal("18"),
            Decimal("16"),
            Decimal("3"),
            Decimal("8"),
            Decimal("12"),  # Pivot at idx 7
        ]
        pivots = find_pivot_lows(lows, left_bars=2, right_bars=2)
        assert len(pivots) == 2
        assert pivots[0] == (2, Decimal("5"))
        assert pivots[1] == (7, Decimal("3"))
