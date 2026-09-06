"""Tests unitarios y de causabilidad matemática para el Feature Engine (Fase 1).

Verifica:
- Política de calentamiento dinámico (FeatureWarmupPolicy).
- Pureza matemática de las features (Efficiency Ratio, Slope, Trend Spread, RV, Z-Score).
- Demostración de cero data leakage en percentiles rodantes causales.
- Sincronización temporal estricta 1h/4h (Invariante: la vela 4h de las 08:00 es invisible a las 10:00).
- Causalidad en el feed de derivados.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.regime_engine.feature_engine import (
    DerivativeObservation,
    FeatureWarmupPolicy,
    InsufficientWarmupError,
    QuantitativeFeatureEngine,
    calculate_causal_rolling_percentile,
    calculate_delta_oi_4h,
    calculate_efficiency_ratio,
    calculate_funding_zscore,
    get_last_causal_derivative_observation,
    get_last_closed_4h_context,
)


def _generate_synthetic_candles(count: int, start_time: datetime, step_hours: int = 1) -> list[HistoricalCandle]:
    """Genera una serie temporal determinista de velas sintéticas en UTC."""
    candles = []
    base_price = Decimal("100.00")
    for i in range(count):
        t = start_time + timedelta(hours=i * step_hours)
        c = base_price + Decimal(str(i % 10))
        h = c + Decimal("2.00")
        low_val = c - Decimal("2.00")
        vol = Decimal("1000.0") + Decimal(str((i * 17) % 500))
        candles.append(HistoricalCandle(timestamp=t, open=c, high=h, low=low_val, close=c, volume=vol))
    return candles


def test_feature_warmup_policy_dynamic_calculation() -> None:
    """Verifica que el warmup se calcule dinámicamente: max(W_i) + safety_margin."""
    policy = FeatureWarmupPolicy(
        window_atr_percentile=500,
        window_rv_percentile=500,
        window_volume_percentile=200,
        window_funding_zscore=720,
        window_trend_ema=50,
        safety_margin=50,
    )
    # max(500, 500, 200, 720, 50) + 50 = 720 + 50 = 770
    assert policy.required_bars_1h == 770

    # Rechaza búferes menores
    with pytest.raises(InsufficientWarmupError, match="Búfer histórico insuficiente"):
        policy.validate_buffer_size(769)

    # Acepta búferes iguales o mayores
    policy.validate_buffer_size(770)
    policy.validate_buffer_size(1000)


def test_efficiency_ratio_properties() -> None:
    """Verifica que el Kaufman Efficiency Ratio sea 1.0 en tendencia pura y tienda a 0 en rango/ruido."""
    # Caso 1: Tendencia estrictamente alcista monotónica (100, 101, 102, ..., 120)
    monotonic_closes = [Decimal(str(100 + i)) for i in range(25)]
    er_trend = calculate_efficiency_ratio(monotonic_closes, current_idx=20, window=20)
    assert er_trend == Decimal("1.0")

    # Caso 2: Rango perfecto oscilante (100, 105, 100, 105, 100...)
    oscillating_closes = [Decimal("100.00") if i % 2 == 0 else Decimal("105.00") for i in range(25)]
    er_chop = calculate_efficiency_ratio(oscillating_closes, current_idx=20, window=20)
    # Desplazamiento neto entre i=0 y i=20 es |100 - 100| = 0
    assert er_chop == Decimal("0.0")


def test_causal_rolling_percentile_zero_lookahead() -> None:
    """Prueba formal de Cero Data Leakage: modificar datos futuros no altera el percentil en t."""
    series_original = [Decimal(str(10 + (i % 20))) for i in range(600)]
    t_idx = 520

    pct_before = calculate_causal_rolling_percentile(series_original, current_idx=t_idx, window=500)

    # Mutar violentamente el futuro (después de t_idx)
    series_mutated = list(series_original)
    for j in range(t_idx + 1, len(series_mutated)):
        series_mutated[j] = Decimal("999999.00")

    pct_after = calculate_causal_rolling_percentile(series_mutated, current_idx=t_idx, window=500)

    # Invariante: Cero fugas de información futura
    assert pct_before == pct_after


def test_strict_1h_4h_causal_temporal_alignment() -> None:
    """Invariante Crítica de Look-Ahead: a las 10:00 1h, la vela 4h de las 08:00 (que cierra a las 12:00) es INVISIBLE.

    La única vela 4h visible es la de las 04:00 (que cerró a las 08:00).
    A las 12:00 1h, la vela 4h de las 08:00 finalmente cierra y se vuelve visible.
    """
    t_base = datetime(2026, 9, 6, 0, 0, 0, tzinfo=UTC)

    # Crear serie de velas 4h que inician a las 00:00, 04:00, 08:00, 12:00
    c_00 = HistoricalCandle(timestamp=t_base, open=Decimal("100"), high=Decimal("102"), low=Decimal("99"), close=Decimal("101"), volume=Decimal("5000"))
    c_04 = HistoricalCandle(timestamp=t_base + timedelta(hours=4), open=Decimal("101"), high=Decimal("103"), low=Decimal("100"), close=Decimal("102"), volume=Decimal("5000"))
    c_08 = HistoricalCandle(timestamp=t_base + timedelta(hours=8), open=Decimal("102"), high=Decimal("105"), low=Decimal("101"), close=Decimal("104"), volume=Decimal("5000"))
    c_12 = HistoricalCandle(timestamp=t_base + timedelta(hours=12), open=Decimal("104"), high=Decimal("106"), low=Decimal("103"), close=Decimal("105"), volume=Decimal("5000"))

    candles_4h = [c_00, c_04, c_08, c_12]

    # 1. Evaluación a las 10:00 1h (en medio de la vela 4h de las 08:00-12:00)
    t_10_1h = t_base + timedelta(hours=10)  # 10:00 UTC
    last_closed_at_10 = get_last_closed_4h_context(t_10_1h, candles_4h)

    assert last_closed_at_10 is not None
    # La vela de las 08:00 NO ha cerrado -> debe retornar la de las 04:00
    assert last_closed_at_10.timestamp == t_base + timedelta(hours=4)
    assert last_closed_at_10.close == Decimal("102")

    # 2. Evaluación a las 12:00 1h (la vela 4h de las 08:00 ya cerró formalmente a las 12:00)
    t_12_1h = t_base + timedelta(hours=12)  # 12:00 UTC
    last_closed_at_12 = get_last_closed_4h_context(t_12_1h, candles_4h)

    assert last_closed_at_12 is not None
    # Ahora sí es visible la vela de las 08:00
    assert last_closed_at_12.timestamp == t_base + timedelta(hours=8)
    assert last_closed_at_12.close == Decimal("104")


def test_derivative_timestamp_causal_filtering() -> None:
    """Verifica que las observaciones de derivados posteriores a la vela 1h sean estrictamente filtradas."""
    t_base = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)

    obs1 = DerivativeObservation(timestamp=t_base - timedelta(minutes=30), funding_rate_8h=Decimal("0.0001"), open_interest=Decimal("50000"))
    obs2 = DerivativeObservation(timestamp=t_base, funding_rate_8h=Decimal("0.0002"), open_interest=Decimal("51000"))
    obs_future = DerivativeObservation(timestamp=t_base + timedelta(minutes=15), funding_rate_8h=Decimal("0.0009"), open_interest=Decimal("99999"))

    feed = [obs1, obs2, obs_future]

    selected = get_last_causal_derivative_observation(t_base, feed)
    assert selected is not None
    assert selected.timestamp == t_base
    assert selected.open_interest == Decimal("51000")
    # El dato futuro nunca fue seleccionado
    assert selected.open_interest != Decimal("99999")


def test_funding_zscore_and_delta_oi() -> None:
    """Verifica el cálculo estadístico de Z-score de fondeo y variación delta OI."""
    # Crear serie con media 0.0001 y varianza constante
    fundings = [Decimal("0.0001") for _ in range(720)]
    fundings[-1] = Decimal("0.0005")  # Desviación extrema al final
    z = calculate_funding_zscore(fundings, current_idx=719, window=720)
    assert z > Decimal("2.0")  # Z-score extremo positivo

    # Delta OI
    ois = [Decimal("100000"), Decimal("100000"), Decimal("100000"), Decimal("100000"), Decimal("92000")]
    delta_oi = calculate_delta_oi_4h(ois, current_idx=4, lookback_bars=4)
    # (92000 - 100000) / 100000 = -0.08 (-8%)
    assert delta_oi == Decimal("-0.0800")


def test_quantitative_feature_engine_integration() -> None:
    """Test de integración del FeatureEngine procesando velas sintéticas que superan el warmup."""
    policy = FeatureWarmupPolicy(
        window_atr_percentile=500,
        window_rv_percentile=500,
        window_volume_percentile=200,
        window_funding_zscore=720,
        safety_margin=50,
    )
    engine = QuantitativeFeatureEngine(warmup_policy=policy)

    start_time = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
    candles_1h = _generate_synthetic_candles(count=800, start_time=start_time, step_hours=1)
    candles_4h = _generate_synthetic_candles(count=200, start_time=start_time, step_hours=4)

    features = engine.compute_candle_features(
        candles_1h=candles_1h,
        current_idx=790,
        candles_4h=candles_4h,
    )

    assert "slope_50" in features
    assert "trend_spread" in features
    assert "efficiency_ratio" in features
    assert "atr_percentile" in features
    assert "rv_percentile" in features
    assert "volume_percentile" in features
    assert "tr_percentile" in features
    assert features["context_4h_closed_timestamp"] is not None
    assert features["context_4h_closed_timestamp"] < features["timestamp"]
