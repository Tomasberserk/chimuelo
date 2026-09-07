"""Tests unitarios para el módulo forense chimuelo_prime.research.alpha_forensics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.regime_engine.models import (
    AlphaMotorId,
    TradeCandidate,
    TradeDirection,
)
from chimuelo_prime.research.alpha_forensics import (
    AlphaForensicsAnalyzer,
    aggregate_forensic_metrics,
    calculate_moving_block_bootstrap_diff,
)


def _make_dummy_candles(n: int, start_price: Decimal = Decimal("100.0")) -> list[HistoricalCandle]:
    base_time = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
    candles: list[HistoricalCandle] = []
    p = start_price
    for i in range(n):
        c = HistoricalCandle(
            timestamp=base_time + timedelta(hours=i),
            open=p,
            high=p + Decimal("2.0"),
            low=p - Decimal("1.0"),
            close=p + Decimal("0.5"),
            volume=Decimal("1000.0"),
        )
        candles.append(c)
        p += Decimal("0.5")
    return candles


def test_forensic_metrics_causality_and_lookback() -> None:
    candles = _make_dummy_candles(30)
    atr = [Decimal("1.0")] * 30

    analyzer = AlphaForensicsAnalyzer(
        slippage=Decimal("0.0"),
        fee_rate=Decimal("0.0"),
    )

    candidate = TradeCandidate(
        candidate_id="TEST_B_LONG_1",
        strategy_id=AlphaMotorId.ALPHA_B,
        symbol="BTCUSDT",
        direction=TradeDirection.LONG,
        entry_price=candles[5].close,
        stop_loss=Decimal("99.0"),
        take_profit=Decimal("106.0"),
        confidence_score=Decimal("0.8"),
        timestamp=candles[5].timestamp,
    )

    record = analyzer.evaluate_candidate_forensics(
        candidate=candidate,
        trigger_idx=5,
        candles=candles,
        atr20=atr,
    )

    assert record is not None
    assert record.trigger_idx == 5
    assert record.entry_idx == 6
    assert record.executed_entry == float(candles[6].open)
    assert record.time_to_mfe_24h_bars >= 1
    assert record.time_to_mae_24h_bars >= 1


def test_mfe_mae_r_multiples_consistency() -> None:
    # Synthetic scenario: Entry at 100, SL at 90 (risk = 10), High reaches 120 (MFE = +20 = +2R), Low drops to 95 (MAE = -5 = -0.5R)
    base_time = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
    candles = [
        HistoricalCandle(
            timestamp=base_time,
            open=Decimal("100.0"),
            high=Decimal("101.0"),
            low=Decimal("99.0"),
            close=Decimal("100.0"),
            volume=Decimal("100.0"),
        ),
        HistoricalCandle(
            timestamp=base_time + timedelta(hours=1),
            open=Decimal("100.0"),
            high=Decimal("120.0"),
            low=Decimal("95.0"),
            close=Decimal("115.0"),
            volume=Decimal("100.0"),
        ),
    ]
    # Add dummy forward bars
    for i in range(2, 26):
        candles.append(
            HistoricalCandle(
                timestamp=base_time + timedelta(hours=i),
                open=Decimal("115.0"),
                high=Decimal("116.0"),
                low=Decimal("114.0"),
                close=Decimal("115.0"),
                volume=Decimal("100.0"),
            )
        )

    atr = [Decimal("5.0")] * len(candles)
    analyzer = AlphaForensicsAnalyzer(slippage=Decimal("0.0"), fee_rate=Decimal("0.0"))

    cand = TradeCandidate(
        candidate_id="TEST_LONG_R",
        strategy_id=AlphaMotorId.ALPHA_B,
        symbol="BTCUSDT",
        direction=TradeDirection.LONG,
        entry_price=Decimal("100.0"),
        stop_loss=Decimal("90.0"),
        take_profit=Decimal("120.0"),
        confidence_score=Decimal("0.8"),
        timestamp=base_time,
    )

    record = analyzer.evaluate_candidate_forensics(
        candidate=cand,
        trigger_idx=0,
        candles=candles,
        atr20=atr,
    )

    assert record is not None
    assert record.risk_unit == 10.0
    assert record.risk_pct == 10.0
    # Entry at 100, High 120 -> MFE = +20% -> +2.0R
    assert pytest.approx(record.mfe_1h_r, 0.01) == 2.0
    # Entry at 100, Low 95 -> MAE = -5% -> -0.5R
    assert pytest.approx(record.mae_1h_r, 0.01) == -0.5
    assert record.would_hit_tp_before_sl is True
    assert record.would_hit_sl_before_tp is False


def test_moving_block_bootstrap_diff() -> None:
    series_a = [1.0, 1.2, 0.8, 1.1, 0.9, 1.5, 1.0, 1.3] * 10
    series_b = [0.0, -0.2, 0.1, -0.1, 0.0, 0.2, -0.1, 0.0] * 10

    res = calculate_moving_block_bootstrap_diff(
        series_trigger=series_a,
        series_non_trigger=series_b,
        block_length=4,
        iterations=200,
        seed=42,
    )

    assert res["mean_trigger"] > res["mean_non_trigger"]
    assert res["delta_mean"] > 0.0
    assert res["ci_95_lower"] > 0.0
    assert res["p_value_permutation"] < 0.05


def test_sweep_microstructure_attributes() -> None:
    base_time = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
    # Lookback 24 bars: Low is 95.0
    candles: list[HistoricalCandle] = []
    for i in range(24):
        candles.append(
            HistoricalCandle(
                timestamp=base_time + timedelta(hours=i),
                open=Decimal("100.0"),
                high=Decimal("105.0"),
                low=Decimal("95.0"),
                close=Decimal("100.0"),
                volume=Decimal("100.0"),
            )
        )
    # Bar 24: Sweeps to 92.0 (depth = 3.0), closes at 97.0 (reclaim)
    candles.append(
        HistoricalCandle(
            timestamp=base_time + timedelta(hours=24),
            open=Decimal("96.0"),
            high=Decimal("98.0"),
            low=Decimal("92.0"),
            close=Decimal("97.0"),
            volume=Decimal("300.0"),  # 3x volume
        )
    )
    # Next 10 forward bars: 2 bars re-test <= 95.0
    for i in range(25, 35):
        l_val = Decimal("94.0") if i in (26, 27) else Decimal("98.0")
        candles.append(
            HistoricalCandle(
                timestamp=base_time + timedelta(hours=i),
                open=Decimal("97.0"),
                high=Decimal("102.0"),
                low=l_val,
                close=Decimal("100.0"),
                volume=Decimal("100.0"),
            )
        )

    atr = [Decimal("2.0")] * len(candles)
    analyzer = AlphaForensicsAnalyzer(slippage=Decimal("0.0"), fee_rate=Decimal("0.0"))

    cand = TradeCandidate(
        candidate_id="TEST_SWEEP_C",
        strategy_id=AlphaMotorId.ALPHA_C,
        symbol="BTCUSDT",
        direction=TradeDirection.LONG,
        entry_price=Decimal("97.0"),
        stop_loss=Decimal("90.0"),
        take_profit=Decimal("105.0"),
        confidence_score=Decimal("0.7"),
        timestamp=candles[24].timestamp,
    )

    record = analyzer.evaluate_candidate_forensics(
        candidate=cand,
        trigger_idx=24,
        candles=candles,
        atr20=atr,
        lookback_c=24,
    )

    assert record is not None
    # Sweep depth: 95.0 - 92.0 = 3.0. In ATR (2.0): 3.0 / 2.0 = 1.5
    assert record.sweep_depth_atr == 1.5
    # Wick: 97.0 - 92.0 = 5.0. Range: 98.0 - 92.0 = 6.0. Wick ratio: 5/6 ~= 0.833
    assert pytest.approx(record.wick_rejection_ratio or 0, 0.01) == 0.83
    # Relative volume: 300 / 100 = 3.0
    assert pytest.approx(record.relative_volume or 0, 0.1) == 3.0
    # Re-tests within 4h: bar 26 and 27 have Low 94.0 <= 95.0 -> 2 re-tests
    assert record.second_tests_4h == 2


def test_aggregate_forensic_metrics_empty() -> None:
    res = aggregate_forensic_metrics([])
    assert res["n_signals"] == 0


def test_zero_production_imports() -> None:
    import inspect

    import chimuelo_prime.research.alpha_forensics as af

    src = inspect.getsource(af)
    assert "live_runner" not in src
    assert "StructuralBreakoutStrategy" not in src
    assert "grid_engine" not in src
