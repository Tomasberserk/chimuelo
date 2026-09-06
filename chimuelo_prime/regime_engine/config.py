"""Configuración Centralizada y Versionada de Umbrales del Regime Engine.

Define todos los umbrales matemáticos para la clasificación discreta de los
estados de mercado en sus 5 dimensiones, garantizando trazabilidad y reproducibilidad.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class RegimeEngineConfig:
    """Parámetros y umbrales cuantitativos congelados para el Regime Engine."""

    VERSION: str = "v0.1.0-frozen"

    # ==========================================================================
    # DIMENSIÓN 1: TENDENCIA (TREND REGIME)
    # ==========================================================================
    # Slope_50 = (EMA50[t] - EMA50[t-20]) / ATR20[t]
    # TrendSpread = (EMA20[t] - EMA50[t]) / ATR20[t]
    trend_spread_strong_bull_min: Decimal = Decimal("1.0")
    trend_slope_strong_bull_min: Decimal = Decimal("0.0")
    adx_strong_trend_min: Decimal = Decimal("25.0")

    trend_spread_bull_min: Decimal = Decimal("0.0")
    adx_trend_min: Decimal = Decimal("20.0")

    adx_neutral_max: Decimal = Decimal("20.0")

    trend_spread_bear_max: Decimal = Decimal("0.0")

    trend_spread_strong_bear_max: Decimal = Decimal("-1.0")
    trend_slope_strong_bear_max: Decimal = Decimal("0.0")

    # ==========================================================================
    # DIMENSIÓN 2: VOLATILIDAD (VOLATILITY REGIME)
    # ==========================================================================
    # Basado en percentiles rodantes causales W=500 barras de ATR20 y RV20
    volatility_extreme_compression_pct_max: Decimal = Decimal("10.0")
    volatility_compression_pct_max: Decimal = Decimal("25.0")
    volatility_normal_pct_max: Decimal = Decimal("75.0")
    volatility_expansion_pct_max: Decimal = Decimal("90.0")
    # >= 90.0 se clasifica como EXTREME_EXPANSION

    # ==========================================================================
    # DIMENSIÓN 3: ESTRUCTURA DE MERCADO (STRUCTURE REGIME)
    # ==========================================================================
    # Kaufman Efficiency Ratio ER_20 en [0.0, 1.0]
    efficiency_ratio_directional_min: Decimal = Decimal("0.60")
    efficiency_ratio_range_bound_max: Decimal = Decimal("0.35")
    # Entre 0.35 y 0.60 se clasifica como TRANSITIONAL

    # ==========================================================================
    # DIMENSIÓN 4: PARTICIPACIÓN DE VOLUMEN (PARTICIPATION REGIME)
    # ==========================================================================
    # Percentiles rodantes causales W=200 barras de Volumen y True Range
    participation_expansion_vol_pct_min: Decimal = Decimal("70.0")
    volume_shock_vol_pct_min: Decimal = Decimal("90.0")
    volume_shock_tr_pct_min: Decimal = Decimal("90.0")

    # ==========================================================================
    # DIMENSIÓN 5: DERIVADOS (DERIVATIVES REGIME)
    # ==========================================================================
    # Z-Score de Funding acumulado 8h (W=720) y Delta OI en 4h
    funding_zscore_extreme_long_min: Decimal = Decimal("2.0")
    funding_zscore_extreme_short_max: Decimal = Decimal("-2.0")
    delta_oi_expansion_min: Decimal = Decimal("0.05")    # +5.0%
    delta_oi_contraction_max: Decimal = Decimal("-0.05")  # -5.0%
    derivatives_stress_vol_pct_min: Decimal = Decimal("90.0")
    funding_zscore_neutral_max: Decimal = Decimal("1.0")

    # ==========================================================================
    # UMBRALES DE CONFIANZA Y TRANSICIÓN
    # ==========================================================================
    regime_confidence_threshold_min: Decimal = Decimal("0.15")
