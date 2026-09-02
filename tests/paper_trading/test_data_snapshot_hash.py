"""Tests de integridad, completitud e inmutabilidad del Data Snapshot Hash."""

from datetime import UTC, datetime
from decimal import Decimal
import pytest

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.paper_trading.decision_engine import SingleDecisionEngine
from chimuelo_prime.paper_trading.decision_models import FilterEvaluationSnapshot
from chimuelo_prime.strategies.structural_breakout import StructuralBreakoutStrategy


def test_data_snapshot_hash_completeness_and_mutation():
    """Verifica que data_snapshot_hash sea determinista y reaccione ante cualquier mutación de input."""
    candle = HistoricalCandle(
        timestamp=datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC),
        open=Decimal("100.0"),
        high=Decimal("110.0"),
        low=Decimal("95.0"),
        close=Decimal("108.0"),
        volume=Decimal("1500.0"),
    )

    filters = FilterEvaluationSnapshot(
        price_above_ema100=True,
        ema100_val=Decimal("90.0"),
        breakout_20_high=True,
        resistance_val=Decimal("105.0"),
        close_position_ratio=Decimal("0.85"),
        close_position_passed=True,
        volume_sma20_val=Decimal("1000.0"),
        volume_sma20_passed=True,
        btc_daily_date_prev="2026-08-31",
        btc_daily_close_prev=Decimal("62000.0"),
        btc_daily_ema50_prev=Decimal("58000.0"),
        btc_macro_bullish=True,
        volume_p70_threshold=Decimal("1200.0"),
        volume_p70_passed=True,
        range_span_val=Decimal("15.0"),
        atr14_val=Decimal("3.0"),
        range_atr_ratio=Decimal("5.0"),
        range_filter_passed=True,
        all_gates_passed=True,
    )

    vols = [Decimal(str(1000 + i)) for i in range(100)]
    config_hash = StructuralBreakoutStrategy.get_config_hash()

    base_hash = SingleDecisionEngine.compute_data_snapshot_hash(
        candle=candle,
        filters_snapshot=filters,
        past_100_vols=vols,
        strategy_version="v1.0.0-frozen",
        config_hash=config_hash,
    )

    assert len(base_hash) == 64

    # 1. Mutar el cierre de la vela
    mut_candle = HistoricalCandle(
        timestamp=candle.timestamp,
        open=candle.open,
        high=candle.high,
        low=candle.low,
        close=Decimal("108.01"),  # 1 centavo de diferencia
        volume=candle.volume,
    )
    mut_hash_1 = SingleDecisionEngine.compute_data_snapshot_hash(
        candle=mut_candle,
        filters_snapshot=filters,
        past_100_vols=vols,
        strategy_version="v1.0.0-frozen",
        config_hash=config_hash,
    )
    assert mut_hash_1 != base_hash

    # 2. Mutar el BTC D-1 close
    mut_filters = filters.model_copy(update={"btc_daily_close_prev": Decimal("62000.50")})
    mut_hash_2 = SingleDecisionEngine.compute_data_snapshot_hash(
        candle=candle,
        filters_snapshot=mut_filters,
        past_100_vols=vols,
        strategy_version="v1.0.0-frozen",
        config_hash=config_hash,
    )
    assert mut_hash_2 != base_hash

    # 3. Mutar uno de los 100 volúmenes históricos
    mut_vols = list(vols)
    mut_vols[42] = Decimal("9999.0")
    mut_hash_3 = SingleDecisionEngine.compute_data_snapshot_hash(
        candle=candle,
        filters_snapshot=filters,
        past_100_vols=mut_vols,
        strategy_version="v1.0.0-frozen",
        config_hash=config_hash,
    )
    assert mut_hash_3 != base_hash
