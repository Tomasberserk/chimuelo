"""Suite de Tests Rigurosa para el QuantitativeRegimeEngine (Fase 2).

Valida:
1. Clasificación exacta de las 5 dimensiones (ExpectedState == ObservedState).
2. Detección causal de transiciones f(S_{t-1}, S_t).
3. Invariantes matemáticas fundamentales:
   - Rechazo estricto de Warmup (< 770 barras).
   - Determinismo estricto (mismo input -> exactamente mismo S_t).
   - Cero Look-Ahead (mutar velas futuras no altera S_t).
   - Invariancia de Escala de Precios (multiplicar precios por k=10 no altera las clasificaciones).
   - Estabilidad ante Perturbaciones (ruido |epsilon| < 0.0001 no altera un régimen estable).
4. Generación y evaluación de series sintéticas de mercado (Tendencia Alcista, Tendencia Bajista, Rango/Chop).
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.regime_engine.feature_engine import (
    InsufficientWarmupError,
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
from chimuelo_prime.regime_engine.regime_engine import QuantitativeRegimeEngine

# ==============================================================================
# HELPERS PARA GENERACIÓN DE SERIES SINTÉTICAS
# ==============================================================================


def _create_dummy_state_vector(
    trend: TrendRegime = TrendRegime.NEUTRAL,
    volatility: VolatilityRegime = VolatilityRegime.NORMAL,
    structure: StructureRegime = StructureRegime.TRANSITIONAL,
    participation: ParticipationRegime = ParticipationRegime.NORMAL_PARTICIPATION,
    derivatives: DerivativesRegime = DerivativesRegime.NEUTRAL,
    transition: RegimeTransition = RegimeTransition.STABLE_REGIME,
) -> MarketStateVector:
    """Crea un MarketStateVector mínimo para pruebas de transición."""
    return MarketStateVector(
        timestamp=datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC),
        symbol="BTCUSDT",
        timeframe="1h",
        trend=trend,
        volatility=volatility,
        structure=structure,
        participation=participation,
        derivatives=derivatives,
        slope_50=Decimal("0.0"),
        trend_spread=Decimal("0.0"),
        adx_14=Decimal("20.0"),
        efficiency_ratio=Decimal("0.50"),
        atr_percentile=Decimal("50.0"),
        rv_percentile=Decimal("50.0"),
        volume_percentile=Decimal("50.0"),
        tr_percentile=Decimal("50.0"),
        z_funding=Decimal("0.0"),
        delta_oi_4h=Decimal("0.0"),
        transition=transition,
        context_4h_closed_timestamp=None,
    )


def _generate_synthetic_candle_series(
    count: int,
    start_time: datetime,
    base_price: Decimal = Decimal("100.00"),
    step_price: Decimal = Decimal("0.0"),
    noise_range: Decimal = Decimal("1.0"),
    base_volume: Decimal = Decimal("1000.0"),
) -> list[HistoricalCandle]:
    """Genera una serie temporal controlada de velas sintéticas deterministas."""
    candles = []
    current_price = base_price
    for i in range(count):
        t = start_time + timedelta(hours=i)
        current_price = base_price + (Decimal(str(i)) * step_price)
        noise = (Decimal(str(i % 5)) - Decimal("2")) * (noise_range / Decimal("2"))
        c = max(Decimal("1.00"), current_price + noise)
        h = c + noise_range
        low_val = max(Decimal("0.50"), c - noise_range)
        open_val = c - (noise / Decimal("2"))
        vol = base_volume + Decimal(str((i * 13) % 200))
        candles.append(HistoricalCandle(timestamp=t, open=open_val, high=h, low=low_val, close=c, volume=vol))
    return candles


# ==============================================================================
# 1. CLASIFICACIÓN DE LAS 5 DIMENSIONES INDIVIDUALES
# ==============================================================================


class TestTrendRegimeClassification:
    """Valida la clasificación de la dimensión de Tendencia."""

    @pytest.fixture
    def engine(self) -> QuantitativeRegimeEngine:
        return QuantitativeRegimeEngine()

    def test_strong_bull_classification(self, engine: QuantitativeRegimeEngine) -> None:
        """TrendSpread >= 1.0, ADX >= 25.0, Slope > 0.0 -> STRONG_BULL."""
        res = engine.classify_trend(
            slope_50=Decimal("0.5"),
            trend_spread=Decimal("1.2"),
            adx_14=Decimal("30.0"),
        )
        assert res == TrendRegime.STRONG_BULL

    def test_strong_bear_classification(self, engine: QuantitativeRegimeEngine) -> None:
        """TrendSpread <= -1.0, ADX >= 25.0, Slope < 0.0 -> STRONG_BEAR."""
        res = engine.classify_trend(
            slope_50=Decimal("-0.5"),
            trend_spread=Decimal("-1.5"),
            adx_14=Decimal("28.0"),
        )
        assert res == TrendRegime.STRONG_BEAR

    def test_neutral_classification_when_adx_low(self, engine: QuantitativeRegimeEngine) -> None:
        """ADX <= 20.0 fuerza NEUTRAL independientemente del spread o pendiente."""
        res = engine.classify_trend(
            slope_50=Decimal("1.5"),
            trend_spread=Decimal("2.0"),
            adx_14=Decimal("18.5"),
        )
        assert res == TrendRegime.NEUTRAL

    def test_moderated_bull_classification(self, engine: QuantitativeRegimeEngine) -> None:
        """TrendSpread > 0.0 y ADX > 20.0 sin cumplir criterio de Strong Bull -> BULL."""
        res = engine.classify_trend(
            slope_50=Decimal("0.2"),
            trend_spread=Decimal("0.6"),
            adx_14=Decimal("22.0"),
        )
        assert res == TrendRegime.BULL

    def test_moderated_bear_classification(self, engine: QuantitativeRegimeEngine) -> None:
        """TrendSpread < 0.0 y ADX > 20.0 sin cumplir criterio de Strong Bear -> BEAR."""
        res = engine.classify_trend(
            slope_50=Decimal("-0.2"),
            trend_spread=Decimal("-0.6"),
            adx_14=Decimal("22.0"),
        )
        assert res == TrendRegime.BEAR


class TestVolatilityRegimeClassification:
    """Valida la clasificación de la dimensión de Volatilidad."""

    @pytest.fixture
    def engine(self) -> QuantitativeRegimeEngine:
        return QuantitativeRegimeEngine()

    def test_extreme_compression(self, engine: QuantitativeRegimeEngine) -> None:
        """Percentil combinado < 10.0 -> EXTREME_COMPRESSION."""
        res = engine.classify_volatility(
            atr_percentile=Decimal("5.0"),
            rv_percentile=Decimal("8.0"),
        )
        assert res == VolatilityRegime.EXTREME_COMPRESSION

    def test_compression(self, engine: QuantitativeRegimeEngine) -> None:
        """10.0 <= Percentil combinado < 25.0 -> COMPRESSION."""
        res = engine.classify_volatility(
            atr_percentile=Decimal("15.0"),
            rv_percentile=Decimal("20.0"),
        )
        assert res == VolatilityRegime.COMPRESSION

    def test_normal_volatility(self, engine: QuantitativeRegimeEngine) -> None:
        """25.0 <= Percentil combinado <= 75.0 -> NORMAL."""
        res = engine.classify_volatility(
            atr_percentile=Decimal("50.0"),
            rv_percentile=Decimal("60.0"),
        )
        assert res == VolatilityRegime.NORMAL

    def test_expansion(self, engine: QuantitativeRegimeEngine) -> None:
        """75.0 < Percentil combinado <= 90.0 -> EXPANSION."""
        res = engine.classify_volatility(
            atr_percentile=Decimal("80.0"),
            rv_percentile=Decimal("85.0"),
        )
        assert res == VolatilityRegime.EXPANSION

    def test_extreme_expansion(self, engine: QuantitativeRegimeEngine) -> None:
        """Percentil combinado > 90.0 -> EXTREME_EXPANSION."""
        res = engine.classify_volatility(
            atr_percentile=Decimal("92.0"),
            rv_percentile=Decimal("95.0"),
        )
        assert res == VolatilityRegime.EXTREME_EXPANSION


class TestStructureRegimeClassification:
    """Valida la clasificación de la dimensión de Estructura (Kaufman ER)."""

    @pytest.fixture
    def engine(self) -> QuantitativeRegimeEngine:
        return QuantitativeRegimeEngine()

    def test_directional_structure(self, engine: QuantitativeRegimeEngine) -> None:
        """ER >= 0.60 -> DIRECTIONAL."""
        assert engine.classify_structure(Decimal("0.60")) == StructureRegime.DIRECTIONAL
        assert engine.classify_structure(Decimal("0.85")) == StructureRegime.DIRECTIONAL

    def test_range_bound_structure(self, engine: QuantitativeRegimeEngine) -> None:
        """ER <= 0.35 -> RANGE_BOUND."""
        assert engine.classify_structure(Decimal("0.35")) == StructureRegime.RANGE_BOUND
        assert engine.classify_structure(Decimal("0.10")) == StructureRegime.RANGE_BOUND

    def test_transitional_structure(self, engine: QuantitativeRegimeEngine) -> None:
        """0.35 < ER < 0.60 -> TRANSITIONAL."""
        assert engine.classify_structure(Decimal("0.36")) == StructureRegime.TRANSITIONAL
        assert engine.classify_structure(Decimal("0.59")) == StructureRegime.TRANSITIONAL


class TestParticipationRegimeClassification:
    """Valida la clasificación de la dimensión de Participación."""

    @pytest.fixture
    def engine(self) -> QuantitativeRegimeEngine:
        return QuantitativeRegimeEngine()

    def test_volume_shock(self, engine: QuantitativeRegimeEngine) -> None:
        """Volumen >= 90% y True Range >= 90% -> VOLUME_SHOCK."""
        res = engine.classify_participation(
            volume_percentile=Decimal("91.0"),
            tr_percentile=Decimal("93.0"),
        )
        assert res == ParticipationRegime.VOLUME_SHOCK

    def test_participation_expansion(self, engine: QuantitativeRegimeEngine) -> None:
        """Volumen >= 70% sin llegar a shock simultáneo -> PARTICIPATION_EXPANSION."""
        res = engine.classify_participation(
            volume_percentile=Decimal("75.0"),
            tr_percentile=Decimal("50.0"),
        )
        assert res == ParticipationRegime.PARTICIPATION_EXPANSION

    def test_normal_participation(self, engine: QuantitativeRegimeEngine) -> None:
        """Volumen < 70% -> NORMAL_PARTICIPATION."""
        res = engine.classify_participation(
            volume_percentile=Decimal("65.0"),
            tr_percentile=Decimal("80.0"),
        )
        assert res == ParticipationRegime.NORMAL_PARTICIPATION


class TestDerivativesRegimeClassification:
    """Valida la clasificación de la dimensión de Derivados."""

    @pytest.fixture
    def engine(self) -> QuantitativeRegimeEngine:
        return QuantitativeRegimeEngine()

    def test_derivatives_stress_unconfirmed(self, engine: QuantitativeRegimeEngine) -> None:
        """|Z_funding| >= 2.0, Delta OI <= -5%, Vol >= 90% y liquidations_confirmed=False -> DERIVATIVES_STRESS."""
        res = engine.classify_derivatives(
            z_funding=Decimal("2.5"),
            delta_oi_4h=Decimal("-0.07"),
            volume_percentile=Decimal("92.0"),
            liquidations_confirmed=False,
        )
        assert res == DerivativesRegime.DERIVATIVES_STRESS

    def test_forced_deleveraging_confirmed(self, engine: QuantitativeRegimeEngine) -> None:
        """Condición de estrés con liquidations_confirmed=True -> FORCED_DELEVERAGING_CONFIRMED."""
        res = engine.classify_derivatives(
            z_funding=Decimal("-2.2"),
            delta_oi_4h=Decimal("-0.06"),
            volume_percentile=Decimal("95.0"),
            liquidations_confirmed=True,
        )
        assert res == DerivativesRegime.FORCED_DELEVERAGING_CONFIRMED

    def test_extreme_crowded_long(self, engine: QuantitativeRegimeEngine) -> None:
        """Z_funding >= 2.0, Delta OI >= +5% -> EXTREME_CROWDED_LONG."""
        res = engine.classify_derivatives(
            z_funding=Decimal("2.1"),
            delta_oi_4h=Decimal("0.08"),
            volume_percentile=Decimal("60.0"),
        )
        assert res == DerivativesRegime.EXTREME_CROWDED_LONG

    def test_extreme_crowded_short(self, engine: QuantitativeRegimeEngine) -> None:
        """Z_funding <= -2.0, Delta OI >= +5% -> EXTREME_CROWDED_SHORT."""
        res = engine.classify_derivatives(
            z_funding=Decimal("-2.4"),
            delta_oi_4h=Decimal("0.06"),
            volume_percentile=Decimal("60.0"),
        )
        assert res == DerivativesRegime.EXTREME_CROWDED_SHORT

    def test_neutral_when_feed_is_none_or_normal(self, engine: QuantitativeRegimeEngine) -> None:
        """Valores None o dentro de rangos normales -> NEUTRAL."""
        assert engine.classify_derivatives(None, None, Decimal("50.0")) == DerivativesRegime.NEUTRAL
        assert engine.classify_derivatives(Decimal("0.5"), Decimal("0.01"), Decimal("50.0")) == DerivativesRegime.NEUTRAL


# ==============================================================================
# 2. DETECCIÓN CAUSAL DE TRANSICIONES: f(S_{t-1}, S_t)
# ==============================================================================


class TestTransitionDetection:
    """Valida la máquina de estados de detección causal de transiciones."""

    @pytest.fixture
    def engine(self) -> QuantitativeRegimeEngine:
        return QuantitativeRegimeEngine()

    def test_transition_stable_when_previous_is_none(self, engine: QuantitativeRegimeEngine) -> None:
        """Sin estado anterior, la transición es STABLE_REGIME por defecto."""
        trans = engine.detect_transition(
            current_trend=TrendRegime.STRONG_BULL,
            current_volatility=VolatilityRegime.EXPANSION,
            current_structure=StructureRegime.DIRECTIONAL,
            current_participation=ParticipationRegime.NORMAL_PARTICIPATION,
            current_derivatives=DerivativesRegime.NEUTRAL,
            previous_state=None,
        )
        assert trans == RegimeTransition.STABLE_REGIME

    def test_transition_compression_to_expansion(self, engine: QuantitativeRegimeEngine) -> None:
        """Anterior en COMPRESSION y actual en EXPANSION -> COMPRESSION_TO_EXPANSION."""
        prev = _create_dummy_state_vector(volatility=VolatilityRegime.COMPRESSION)
        trans = engine.detect_transition(
            current_trend=TrendRegime.BULL,
            current_volatility=VolatilityRegime.EXPANSION,
            current_structure=StructureRegime.TRANSITIONAL,
            current_participation=ParticipationRegime.NORMAL_PARTICIPATION,
            current_derivatives=DerivativesRegime.NEUTRAL,
            previous_state=prev,
        )
        assert trans == RegimeTransition.COMPRESSION_TO_EXPANSION

    def test_transition_trend_to_climax(self, engine: QuantitativeRegimeEngine) -> None:
        """Anterior en STRONG_BULL, actual en EXTREME_EXPANSION + DERIVATIVES_STRESS -> TREND_TO_CLIMAX."""
        prev = _create_dummy_state_vector(trend=TrendRegime.STRONG_BULL)
        trans = engine.detect_transition(
            current_trend=TrendRegime.STRONG_BULL,
            current_volatility=VolatilityRegime.EXTREME_EXPANSION,
            current_structure=StructureRegime.DIRECTIONAL,
            current_participation=ParticipationRegime.VOLUME_SHOCK,
            current_derivatives=DerivativesRegime.DERIVATIVES_STRESS,
            previous_state=prev,
        )
        assert trans == RegimeTransition.TREND_TO_CLIMAX

    def test_transition_climax_to_reversal(self, engine: QuantitativeRegimeEngine) -> None:
        """Anterior en DERIVATIVES_STRESS y actual en DIRECTIONAL -> CLIMAX_TO_REVERSAL."""
        prev = _create_dummy_state_vector(derivatives=DerivativesRegime.DERIVATIVES_STRESS)
        trans = engine.detect_transition(
            current_trend=TrendRegime.BEAR,
            current_volatility=VolatilityRegime.NORMAL,
            current_structure=StructureRegime.DIRECTIONAL,
            current_participation=ParticipationRegime.NORMAL_PARTICIPATION,
            current_derivatives=DerivativesRegime.NEUTRAL,
            previous_state=prev,
        )
        assert trans == RegimeTransition.CLIMAX_TO_REVERSAL

    def test_transition_trend_to_pullback(self, engine: QuantitativeRegimeEngine) -> None:
        """Anterior en BULL y actual en BULL pero estructura TRANSITIONAL -> TREND_TO_PULLBACK."""
        prev = _create_dummy_state_vector(
            trend=TrendRegime.BULL,
            structure=StructureRegime.DIRECTIONAL,
        )
        trans = engine.detect_transition(
            current_trend=TrendRegime.BULL,
            current_volatility=VolatilityRegime.NORMAL,
            current_structure=StructureRegime.TRANSITIONAL,
            current_participation=ParticipationRegime.NORMAL_PARTICIPATION,
            current_derivatives=DerivativesRegime.NEUTRAL,
            previous_state=prev,
        )
        assert trans == RegimeTransition.TREND_TO_PULLBACK

    def test_transition_range_to_sweep(self, engine: QuantitativeRegimeEngine) -> None:
        """Anterior RANGE_BOUND, actual RANGE_BOUND pero con PARTICIPATION_EXPANSION -> RANGE_TO_SWEEP."""
        prev = _create_dummy_state_vector(
            structure=StructureRegime.RANGE_BOUND,
            participation=ParticipationRegime.NORMAL_PARTICIPATION,
        )
        trans = engine.detect_transition(
            current_trend=TrendRegime.NEUTRAL,
            current_volatility=VolatilityRegime.NORMAL,
            current_structure=StructureRegime.RANGE_BOUND,
            current_participation=ParticipationRegime.PARTICIPATION_EXPANSION,
            current_derivatives=DerivativesRegime.NEUTRAL,
            previous_state=prev,
        )
        assert trans == RegimeTransition.RANGE_TO_SWEEP


# ==============================================================================
# 3. INVARIANTES MATEMÁTICAS FUNDAMENTALES Y PRUEBAS DE INTEGRACIÓN
# ==============================================================================


class TestMarketStateVectorEvaluationAndInvariants:
    """Verifica las invariantes matemáticas críticas sobre series de datos sintéticos."""

    @pytest.fixture
    def engine(self) -> QuantitativeRegimeEngine:
        return QuantitativeRegimeEngine()

    def test_warmup_rejection_insufficient_bars(self, engine: QuantitativeRegimeEngine) -> None:
        """Debe lanzar InsufficientWarmupError si el número de barras es menor a 770."""
        start_time = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
        short_candles = _generate_synthetic_candle_series(count=700, start_time=start_time)

        with pytest.raises(InsufficientWarmupError, match="Búfer histórico insuficiente"):
            engine.evaluate_market_state(
                symbol="BTCUSDT",
                candles_1h=short_candles,
                current_idx=699,
            )

    def test_determinism_identical_input_identical_output(
        self, engine: QuantitativeRegimeEngine
    ) -> None:
        """Invariante de Determinismo: Mismo input evaluado repetidamente produce exactamente el mismo S_t."""
        start_time = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
        candles = _generate_synthetic_candle_series(count=800, start_time=start_time)

        eval_1 = engine.evaluate_market_state(
            symbol="BTCUSDT",
            candles_1h=candles,
            current_idx=780,
        )
        eval_2 = engine.evaluate_market_state(
            symbol="BTCUSDT",
            candles_1h=candles,
            current_idx=780,
        )

        assert eval_1 == eval_2
        assert eval_1.trend == eval_2.trend
        assert eval_1.volatility == eval_2.volatility
        assert eval_1.structure == eval_2.structure
        assert eval_1.participation == eval_2.participation
        assert eval_1.derivatives == eval_2.derivatives

    def test_zero_lookahead_mutating_future_does_not_affect_st(
        self, engine: QuantitativeRegimeEngine
    ) -> None:
        """Invariante Crítica: Mutar observaciones futuras (> current_idx) no altera S_t en t."""
        start_time = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
        candles_orig = _generate_synthetic_candle_series(count=850, start_time=start_time)
        t_eval = 780

        s_t_original = engine.evaluate_market_state(
            symbol="BTCUSDT",
            candles_1h=candles_orig,
            current_idx=t_eval,
        )

        # Clonar y alterar salvajemente las velas en el futuro (t_eval + 1 en adelante)
        candles_mutated = list(candles_orig)
        for i in range(t_eval + 1, len(candles_mutated)):
            c_old = candles_mutated[i]
            candles_mutated[i] = HistoricalCandle(
                timestamp=c_old.timestamp,
                open=Decimal("999999.00"),
                high=Decimal("1000000.00"),
                low=Decimal("999998.00"),
                close=Decimal("999999.00"),
                volume=Decimal("99999999.00"),
            )

        s_t_after_future_mutation = engine.evaluate_market_state(
            symbol="BTCUSDT",
            candles_1h=candles_mutated,
            current_idx=t_eval,
        )

        # S_t antes y después debe ser IDÉNTICO
        assert s_t_original == s_t_after_future_mutation

    def test_price_scale_invariance(self, engine: QuantitativeRegimeEngine) -> None:
        """Invariante de Escala: Multiplicar precios por escalar k=10 no altera las clasificaciones dimensionales."""
        start_time = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
        candles_base = _generate_synthetic_candle_series(
            count=800,
            start_time=start_time,
            base_price=Decimal("100.00"),
            step_price=Decimal("0.5"),
        )
        t_eval = 780

        state_base = engine.evaluate_market_state(
            symbol="BTCUSDT",
            candles_1h=candles_base,
            current_idx=t_eval,
        )

        # Multiplicar todos los precios por k = 10.0
        k = Decimal("10.0")
        candles_scaled = [
            HistoricalCandle(
                timestamp=c.timestamp,
                open=c.open * k,
                high=c.high * k,
                low=c.low * k,
                close=c.close * k,
                volume=c.volume,
            )
            for c in candles_base
        ]

        state_scaled = engine.evaluate_market_state(
            symbol="BTCUSDT",
            candles_1h=candles_scaled,
            current_idx=t_eval,
        )

        # Las clasificaciones discretas deben ser invariantes ante escala absoluta
        assert state_base.trend == state_scaled.trend
        assert state_base.volatility == state_scaled.volatility
        assert state_base.structure == state_scaled.structure
        assert state_base.participation == state_scaled.participation

    def test_perturbation_stability(self, engine: QuantitativeRegimeEngine) -> None:
        """Invariante de Estabilidad: Pequeño ruido numérico |epsilon| < 0.0001 no altera un régimen estable."""
        start_time = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
        candles = _generate_synthetic_candle_series(
            count=800,
            start_time=start_time,
            base_price=Decimal("100.00"),
            step_price=Decimal("1.0"),  # Fuerte tendencia alcista
            noise_range=Decimal("0.5"),
        )
        t_eval = 780

        state_stable = engine.evaluate_market_state(
            symbol="BTCUSDT",
            candles_1h=candles,
            current_idx=t_eval,
        )

        # Añadir micro-perturbación de 0.00005 a los precios
        epsilon = Decimal("0.00005")
        candles_perturbed = [
            HistoricalCandle(
                timestamp=c.timestamp,
                open=c.open + epsilon,
                high=c.high + epsilon,
                low=c.low - epsilon,
                close=c.close + epsilon,
                volume=c.volume,
            )
            for c in candles
        ]

        state_perturbed = engine.evaluate_market_state(
            symbol="BTCUSDT",
            candles_1h=candles_perturbed,
            current_idx=t_eval,
        )

        assert state_stable.trend == state_perturbed.trend
        assert state_stable.volatility == state_perturbed.volatility
        assert state_stable.structure == state_perturbed.structure

    def test_synthetic_monotonic_bull_regime(self, engine: QuantitativeRegimeEngine) -> None:
        """Serie fuertemente alcista debe clasificarse como STRONG_BULL y DIRECTIONAL."""
        start_time = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
        bull_candles = _generate_synthetic_candle_series(
            count=800,
            start_time=start_time,
            base_price=Decimal("100.00"),
            step_price=Decimal("2.0"),  # Fuerte pendiente constante
            noise_range=Decimal("0.1"),
        )

        state = engine.evaluate_market_state(
            symbol="BTCUSDT",
            candles_1h=bull_candles,
            current_idx=780,
        )

        assert state.trend == TrendRegime.STRONG_BULL
        assert state.structure == StructureRegime.DIRECTIONAL
        assert state.slope_50 > Decimal("0.0")
        assert state.trend_spread >= Decimal("1.0")
        assert state.adx_14 >= Decimal("25.0")
        assert state.efficiency_ratio >= Decimal("0.60")

    def test_synthetic_monotonic_bear_regime(self, engine: QuantitativeRegimeEngine) -> None:
        """Serie fuertemente bajista debe clasificarse como STRONG_BEAR y DIRECTIONAL."""
        start_time = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
        bear_candles = _generate_synthetic_candle_series(
            count=800,
            start_time=start_time,
            base_price=Decimal("5000.00"),
            step_price=Decimal("-3.0"),  # Fuerte caída constante
            noise_range=Decimal("0.1"),
        )

        state = engine.evaluate_market_state(
            symbol="BTCUSDT",
            candles_1h=bear_candles,
            current_idx=780,
        )

        assert state.trend == TrendRegime.STRONG_BEAR
        assert state.structure == StructureRegime.DIRECTIONAL
        assert state.slope_50 < Decimal("0.0")
        assert state.trend_spread <= Decimal("-1.0")
        assert state.adx_14 >= Decimal("25.0")
        assert state.efficiency_ratio >= Decimal("0.60")

    def test_synthetic_choppy_range_regime(self, engine: QuantitativeRegimeEngine) -> None:
        """Serie puramente oscilatoria sin desplazamiento debe clasificarse como RANGE_BOUND o NEUTRAL."""
        start_time = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
        # Generar oscilación pura entre 100 y 101
        range_candles = []
        for i in range(800):
            t = start_time + timedelta(hours=i)
            p = Decimal("100.00") if i % 2 == 0 else Decimal("101.00")
            range_candles.append(
                HistoricalCandle(
                    timestamp=t,
                    open=p,
                    high=p + Decimal("0.2"),
                    low=p - Decimal("0.2"),
                    close=p,
                    volume=Decimal("1000.0"),
                )
            )

        state = engine.evaluate_market_state(
            symbol="BTCUSDT",
            candles_1h=range_candles,
            current_idx=780,
        )

        assert state.structure == StructureRegime.RANGE_BOUND
        assert state.efficiency_ratio <= Decimal("0.35")
