"""Regime Engine: Clasificación de Estado de Mercado y Detección de Transiciones.

Implementa la transformación determinista y causal Features_t -> S_t,
clasificando las 5 dimensiones discretas y evaluando las transiciones
entre estados consecutivos sin look-ahead y con pureza Decimal.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.regime_engine.config import RegimeEngineConfig
from chimuelo_prime.regime_engine.feature_engine import (
    DerivativeObservation,
    FeatureWarmupPolicy,
    QuantitativeFeatureEngine,
)
from chimuelo_prime.regime_engine.models import (
    DerivativesRegime,
    MarketStateVector,
    ParticipationRegime,
    RegimeTransition,
    StructureRegime,
    TrendRegime,
    VolatilityRegime,
)


class QuantitativeRegimeEngine:
    """Motor central para la clasificación del Vector de Estado de Mercado (S_t)."""

    def __init__(
        self,
        config: RegimeEngineConfig | None = None,
        warmup_policy: FeatureWarmupPolicy | None = None,
    ) -> None:
        self.config = config or RegimeEngineConfig()
        self.warmup_policy = warmup_policy or FeatureWarmupPolicy()
        self.feature_engine = QuantitativeFeatureEngine(warmup_policy=self.warmup_policy)

    # ==========================================================================
    # CLASIFICADORES DE LAS 5 DIMENSIONES
    # ==========================================================================

    def classify_trend(
        self,
        slope_50: Decimal,
        trend_spread: Decimal,
        adx_14: Decimal,
    ) -> TrendRegime:
        """Clasifica la dimensión de tendencia de forma determinista."""
        cfg = self.config

        # 1. Strong Bull
        if (
            trend_spread >= cfg.trend_spread_strong_bull_min
            and adx_14 >= cfg.adx_strong_trend_min
            and slope_50 > cfg.trend_slope_strong_bull_min
        ):
            return TrendRegime.STRONG_BULL

        # 2. Strong Bear
        if (
            trend_spread <= cfg.trend_spread_strong_bear_max
            and adx_14 >= cfg.adx_strong_trend_min
            and slope_50 < cfg.trend_slope_strong_bear_max
        ):
            return TrendRegime.STRONG_BEAR

        # 3. Neutral / Chop
        if adx_14 <= cfg.adx_neutral_max:
            return TrendRegime.NEUTRAL

        # 4. Moderated Bull
        if trend_spread > cfg.trend_spread_bull_min and adx_14 > cfg.adx_trend_min:
            return TrendRegime.BULL

        # 5. Moderated Bear
        if trend_spread < cfg.trend_spread_bear_max and adx_14 > cfg.adx_trend_min:
            return TrendRegime.BEAR

        return TrendRegime.NEUTRAL

    def classify_volatility(
        self,
        atr_percentile: Decimal,
        rv_percentile: Decimal,
    ) -> VolatilityRegime:
        """Clasifica la dimensión de volatilidad mediante percentil combinado causal."""
        cfg = self.config
        vol_metric = (atr_percentile + rv_percentile) / Decimal("2.0")

        if vol_metric < cfg.volatility_extreme_compression_pct_max:
            return VolatilityRegime.EXTREME_COMPRESSION
        if vol_metric < cfg.volatility_compression_pct_max:
            return VolatilityRegime.COMPRESSION
        if vol_metric <= cfg.volatility_normal_pct_max:
            return VolatilityRegime.NORMAL
        if vol_metric <= cfg.volatility_expansion_pct_max:
            return VolatilityRegime.EXPANSION
        return VolatilityRegime.EXTREME_EXPANSION

    def classify_structure(self, efficiency_ratio: Decimal) -> StructureRegime:
        """Clasifica la dimensión de estructura de rango vs tendencia mediante ER de Kaufman."""
        cfg = self.config
        if efficiency_ratio >= cfg.efficiency_ratio_directional_min:
            return StructureRegime.DIRECTIONAL
        if efficiency_ratio <= cfg.efficiency_ratio_range_bound_max:
            return StructureRegime.RANGE_BOUND
        return StructureRegime.TRANSITIONAL

    def classify_participation(
        self,
        volume_percentile: Decimal,
        tr_percentile: Decimal,
    ) -> ParticipationRegime:
        """Clasifica la dimensión de participación según percentiles de volumen y rango."""
        cfg = self.config
        if (
            volume_percentile >= cfg.volume_shock_vol_pct_min
            and tr_percentile >= cfg.volume_shock_tr_pct_min
        ):
            return ParticipationRegime.VOLUME_SHOCK
        if volume_percentile >= cfg.participation_expansion_vol_pct_min:
            return ParticipationRegime.PARTICIPATION_EXPANSION
        return ParticipationRegime.NORMAL_PARTICIPATION

    def classify_derivatives(
        self,
        z_funding: Decimal | None,
        delta_oi_4h: Decimal | None,
        volume_percentile: Decimal,
        liquidations_confirmed: bool = False,
    ) -> DerivativesRegime:
        """Clasifica la dimensión de derivados separando estrés de desapalancamiento confirmado."""
        if z_funding is None or delta_oi_4h is None:
            return DerivativesRegime.NEUTRAL

        cfg = self.config

        # Condición de Estrés / Liquidación: Funding extremo + Caída de OI + Shock de Volumen
        is_stress = (
            abs(z_funding) >= abs(cfg.funding_zscore_extreme_long_min)
            and delta_oi_4h <= cfg.delta_oi_contraction_max
            and volume_percentile >= cfg.derivatives_stress_vol_pct_min
        )
        if is_stress:
            if liquidations_confirmed:
                return DerivativesRegime.FORCED_DELEVERAGING_CONFIRMED
            return DerivativesRegime.DERIVATIVES_STRESS

        # Crowded Long (Apalancamiento excesivo acumulándose en compras)
        if (
            z_funding >= cfg.funding_zscore_extreme_long_min
            and delta_oi_4h >= cfg.delta_oi_expansion_min
        ):
            return DerivativesRegime.EXTREME_CROWDED_LONG

        # Crowded Short (Apalancamiento excesivo acumulándose en ventas)
        if (
            z_funding <= cfg.funding_zscore_extreme_short_max
            and delta_oi_4h >= cfg.delta_oi_expansion_min
        ):
            return DerivativesRegime.EXTREME_CROWDED_SHORT

        return DerivativesRegime.NEUTRAL

    # ==========================================================================
    # DETECCIÓN CAUSAL DE TRANSICIÓN: f(S_{t-1}, S_t)
    # ==========================================================================

    def detect_transition(
        self,
        current_trend: TrendRegime,
        current_volatility: VolatilityRegime,
        current_structure: StructureRegime,
        current_participation: ParticipationRegime,
        current_derivatives: DerivativesRegime,
        previous_state: MarketStateVector | None,
    ) -> RegimeTransition:
        """Determina la transición de régimen causalmente comparando con el estado anterior."""
        if previous_state is None:
            return RegimeTransition.STABLE_REGIME

        # 1. Compresión a Expansión
        prev_was_compressed = previous_state.volatility in (
            VolatilityRegime.EXTREME_COMPRESSION,
            VolatilityRegime.COMPRESSION,
        )
        curr_is_expansion = current_volatility in (
            VolatilityRegime.EXPANSION,
            VolatilityRegime.EXTREME_EXPANSION,
        )
        if prev_was_compressed and curr_is_expansion:
            return RegimeTransition.COMPRESSION_TO_EXPANSION

        # 2. Tendencia a Clímax
        prev_was_strong = previous_state.trend in (
            TrendRegime.STRONG_BULL,
            TrendRegime.STRONG_BEAR,
        )
        curr_is_climax = (
            current_volatility == VolatilityRegime.EXTREME_EXPANSION
            and current_derivatives in (
                DerivativesRegime.DERIVATIVES_STRESS,
                DerivativesRegime.FORCED_DELEVERAGING_CONFIRMED,
            )
        )
        if prev_was_strong and curr_is_climax:
            return RegimeTransition.TREND_TO_CLIMAX

        # 3. Clímax a Reversión
        prev_was_climax = previous_state.derivatives in (
            DerivativesRegime.DERIVATIVES_STRESS,
            DerivativesRegime.FORCED_DELEVERAGING_CONFIRMED,
        )
        if prev_was_climax and current_structure == StructureRegime.DIRECTIONAL:
            return RegimeTransition.CLIMAX_TO_REVERSAL

        # 4. Tendencia a Pullback
        prev_was_bull = previous_state.trend in (TrendRegime.BULL, TrendRegime.STRONG_BULL)
        if (
            prev_was_bull
            and current_trend in (TrendRegime.BULL, TrendRegime.STRONG_BULL)
            and current_structure == StructureRegime.TRANSITIONAL
        ):
            return RegimeTransition.TREND_TO_PULLBACK

        # 5. Rango a Barrido de Liquidez (Sweep)
        if (
            previous_state.structure == StructureRegime.RANGE_BOUND
            and current_structure == StructureRegime.RANGE_BOUND
            and current_participation in (
                ParticipationRegime.PARTICIPATION_EXPANSION,
                ParticipationRegime.VOLUME_SHOCK,
            )
        ):
            return RegimeTransition.RANGE_TO_SWEEP

        return RegimeTransition.STABLE_REGIME

    # ==========================================================================
    # EVALUACIÓN INTEGRAL Y GENERACIÓN DE S_t
    # ==========================================================================

    def evaluate_market_state(
        self,
        symbol: str,
        candles_1h: Sequence[HistoricalCandle],
        current_idx: int,
        candles_4h: Sequence[HistoricalCandle] | None = None,
        derivatives_feed: Sequence[DerivativeObservation] | None = None,
        previous_state: MarketStateVector | None = None,
        liquidations_confirmed: bool = False,
    ) -> MarketStateVector:
        """Transformación canónica y determinista Features_t -> MarketStateVector (S_t)."""
        # 1. Calcular features cuantitativas causales (valida warmup)
        feats = self.feature_engine.compute_candle_features(
            candles_1h=candles_1h,
            current_idx=current_idx,
            candles_4h=candles_4h,
            derivatives_feed=derivatives_feed,
        )

        t_now = feats["timestamp"]

        # 2. Clasificar cada una de las 5 dimensiones
        trend_regime = self.classify_trend(
            slope_50=feats["slope_50"],
            trend_spread=feats["trend_spread"],
            adx_14=feats["adx_14"],
        )

        volatility_regime = self.classify_volatility(
            atr_percentile=feats["atr_percentile"],
            rv_percentile=feats["rv_percentile"],
        )

        structure_regime = self.classify_structure(
            efficiency_ratio=feats["efficiency_ratio"],
        )

        participation_regime = self.classify_participation(
            volume_percentile=feats["volume_percentile"],
            tr_percentile=feats["tr_percentile"],
        )

        derivatives_regime = self.classify_derivatives(
            z_funding=feats["z_funding"],
            delta_oi_4h=feats["delta_oi_4h"],
            volume_percentile=feats["volume_percentile"],
            liquidations_confirmed=liquidations_confirmed,
        )

        # 3. Detectar transición respecto al estado previo
        transition = self.detect_transition(
            current_trend=trend_regime,
            current_volatility=volatility_regime,
            current_structure=structure_regime,
            current_participation=participation_regime,
            current_derivatives=derivatives_regime,
            previous_state=previous_state,
        )

        # 4. Construir MarketStateVector inmutable
        return MarketStateVector(
            timestamp=t_now,
            symbol=symbol,
            timeframe="1h",
            trend=trend_regime,
            volatility=volatility_regime,
            structure=structure_regime,
            participation=participation_regime,
            derivatives=derivatives_regime,
            slope_50=feats["slope_50"],
            trend_spread=feats["trend_spread"],
            adx_14=feats["adx_14"],
            efficiency_ratio=feats["efficiency_ratio"],
            atr_percentile=feats["atr_percentile"],
            rv_percentile=feats["rv_percentile"],
            volume_percentile=feats["volume_percentile"],
            tr_percentile=feats["tr_percentile"],
            z_funding=feats["z_funding"],
            delta_oi_4h=feats["delta_oi_4h"],
            transition=transition,
            context_4h_closed_timestamp=feats["context_4h_closed_timestamp"],
        )
