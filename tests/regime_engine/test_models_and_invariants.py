"""Tests unitarios para los Modelos e Invariantes de Dominio del Regime Engine (Fase 0)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import pytest

from chimuelo_prime.regime_engine.models import (
    AlphaMotorId,
    DerivativesRegime,
    ForensicDecisionLog,
    MarketStateVector,
    NoTradeReasonCode,
    ParticipationRegime,
    RegimeTransition,
    RouterStrategyState,
    StructureRegime,
    TrendRegime,
    VolatilityRegime,
    ensure_utc_aware,
)


def test_ensure_utc_aware_rejects_naive_datetime():
    """Verifica que el contrato cuantitativo rechace estrictamente datetimes naive sin timezone."""
    naive_dt = datetime(2026, 9, 6, 12, 0, 0)
    with pytest.raises(ValueError, match="Timestamp naive rechazado"):
        ensure_utc_aware(naive_dt)

    aware_dt = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
    res = ensure_utc_aware(aware_dt)
    assert res.tzinfo == UTC


def test_market_state_vector_immutability_and_types():
    """Verifica que MarketStateVector sea inmutable (frozen) y preserve la pureza de sus 5 dimensiones."""
    now = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)

    msv = MarketStateVector(
        timestamp=now,
        symbol="BTCUSDT",
        timeframe="1h",
        trend=TrendRegime.STRONG_BULL,
        volatility=VolatilityRegime.EXPANSION,
        structure=StructureRegime.DIRECTIONAL,
        participation=ParticipationRegime.PARTICIPATION_EXPANSION,
        derivatives=DerivativesRegime.NEUTRAL,
        slope_50=Decimal("1.25"),
        trend_spread=Decimal("1.10"),
        adx_14=Decimal("28.5"),
        efficiency_ratio=Decimal("0.72"),
        atr_percentile=Decimal("82.5"),
        rv_percentile=Decimal("78.0"),
        volume_percentile=Decimal("75.4"),
        tr_percentile=Decimal("80.2"),
        z_funding=Decimal("0.45"),
        delta_oi_4h=Decimal("0.021"),
        transition=RegimeTransition.COMPRESSION_TO_EXPANSION,
    )

    # Inmutabilidad (frozen)
    with pytest.raises(Exception):
        msv.trend = TrendRegime.BEAR  # type: ignore

    assert msv.trend == TrendRegime.STRONG_BULL
    assert msv.participation == ParticipationRegime.PARTICIPATION_EXPANSION
    assert msv.efficiency_ratio == Decimal("0.72")


def test_forensic_decision_log_reason_codes():
    """Verifica que ForensicDecisionLog capture las razones explícitas de abstención (NO_TRADE)."""
    now = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)

    msv = MarketStateVector(
        timestamp=now,
        symbol="SOLUSDT",
        timeframe="1h",
        trend=TrendRegime.NEUTRAL,
        volatility=VolatilityRegime.COMPRESSION,
        structure=StructureRegime.RANGE_BOUND,
        participation=ParticipationRegime.NORMAL_PARTICIPATION,
        derivatives=DerivativesRegime.NEUTRAL,
        slope_50=Decimal("0.05"),
        trend_spread=Decimal("0.10"),
        adx_14=Decimal("16.0"),
        efficiency_ratio=Decimal("0.22"),
        atr_percentile=Decimal("18.0"),
        rv_percentile=Decimal("20.0"),
        volume_percentile=Decimal("35.0"),
        tr_percentile=Decimal("40.0"),
    )

    log_entry = ForensicDecisionLog(
        timestamp=now,
        symbol="SOLUSDT",
        decision_action="NO_TRADE",
        reason_code=NoTradeReasonCode.AMBIGUOUS_REGIME,
        market_state=msv,
        strategy_scores={"A": Decimal("0.38"), "B": Decimal("0.35")},
        fsm_states={"A": RouterStrategyState.DISABLED, "B": RouterStrategyState.DISABLED},
        regime_confidence=Decimal("0.03"),
        hermes_veto=False,
        details="Mercado sin direccionalidad clara ni volumen",
    )

    assert log_entry.decision_action == "NO_TRADE"
    assert log_entry.reason_code == NoTradeReasonCode.AMBIGUOUS_REGIME
    assert log_entry.regime_confidence == Decimal("0.03")
