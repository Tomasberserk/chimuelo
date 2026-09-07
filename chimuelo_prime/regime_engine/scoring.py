"""Matriz de Scoring Cuantitativo de Compatibilidad de Régimen (Fase 3).

Implementa la evaluación desacoplada de compatibilidad (RegimeCompatibilityScore)
para los 4 Alpha Motors bajo la arquitectura Soft Scores + Hard Gates,
soporte direccional (LONG / SHORT) y desglose granular para registro forense.
"""

from __future__ import annotations

from decimal import Decimal

from chimuelo_prime.regime_engine.models import (
    AlphaMotorId,
    DerivativesRegime,
    DirectionalScore,
    MarketStateVector,
    ParticipationRegime,
    RegimeTransition,
    ScoreComponentBreakdown,
    StructureRegime,
    TradeDirection,
    TrendRegime,
    VolatilityRegime,
)
from chimuelo_prime.regime_engine.router_config import RouterConfig


class StrategyCompatibilityScorer:
    """Motor matemático determinista para el cálculo de RegimeCompatibilityScore."""

    def __init__(self, config: RouterConfig | None = None) -> None:
        self.config = config or RouterConfig()

    # ==========================================================================
    # 1. HARD GATES (FILTROS BOOLEANOS DE INVALIDACIÓN ESTRUCTURAL)
    # ==========================================================================

    def evaluate_hard_gate(
        self,
        strategy_id: AlphaMotorId,
        market_state: MarketStateVector,
        direction: TradeDirection = TradeDirection.LONG,
    ) -> bool:
        """Evalúa las compuertas duras de invalidación (1=Permitido, 0=Bloqueado)."""
        # A. Volatility Squeeze
        if strategy_id == AlphaMotorId.ALPHA_A:
            # No se puede hacer squeeze si la volatilidad ya está en expansión extrema
            if market_state.volatility == VolatilityRegime.EXTREME_EXPANSION:
                return False
            # Filtro direccional básico
            if direction == TradeDirection.LONG and market_state.trend == TrendRegime.STRONG_BEAR:
                return False
            return not (direction == TradeDirection.SHORT and market_state.trend == TrendRegime.STRONG_BULL)

        # B. Deep Pullback
        elif strategy_id == AlphaMotorId.ALPHA_B:
            # Pullback requiere tendencia macro a favor; prohibido contratendencia fuerte
            if direction == TradeDirection.LONG and market_state.trend in (TrendRegime.BEAR, TrendRegime.STRONG_BEAR):
                return False
            return not (
                direction == TradeDirection.SHORT
                and market_state.trend in (TrendRegime.BULL, TrendRegime.STRONG_BULL)
            )

        # C. Liquidity Sweep (Motor Central)
        elif strategy_id == AlphaMotorId.ALPHA_C:
            # Barrido de liquidez prohibido en tendencias directas limpias (ER >= 0.60)
            if market_state.structure == StructureRegime.DIRECTIONAL:
                return False
            return market_state.efficiency_ratio < Decimal("0.60")

        # D. Derivatives Exhaustion
        elif strategy_id == AlphaMotorId.ALPHA_D:
            # Requiere contexto de derivados o expansión extrema de volatilidad
            has_deriv_context = market_state.derivatives in (
                DerivativesRegime.DERIVATIVES_STRESS,
                DerivativesRegime.FORCED_DELEVERAGING_CONFIRMED,
                DerivativesRegime.EXTREME_CROWDED_LONG,
                DerivativesRegime.EXTREME_CROWDED_SHORT,
            )
            has_vol_context = market_state.volatility == VolatilityRegime.EXTREME_EXPANSION
            if not (has_deriv_context or has_vol_context):
                return False

            # Subregímenes direccionales de agotamiento:
            # LONG Exhaustion: rebote tras capitulación vendedora (crowded short o estrés)
            if direction == TradeDirection.LONG and market_state.derivatives == DerivativesRegime.EXTREME_CROWDED_LONG:
                return False
            # SHORT Exhaustion: techo tras capitulación compradora (crowded long o estrés)
            return not (
                direction == TradeDirection.SHORT
                and market_state.derivatives == DerivativesRegime.EXTREME_CROWDED_SHORT
            )

        return False

    # ==========================================================================
    # 2. EVALUACIÓN DETALLADA POR ESTRATEGIA (SOFT SCORES)
    # ==========================================================================

    def calculate_score_alpha_a(
        self,
        market_state: MarketStateVector,
        direction: TradeDirection,
    ) -> tuple[Decimal, ScoreComponentBreakdown]:
        """Calcula el score de compatibilidad para Strategy A (Volatility Squeeze)."""
        cfg = self.config

        # 1. Volatilidad (Peso 0.35)
        vol_scores = {
            VolatilityRegime.EXTREME_COMPRESSION: Decimal("1.00"),
            VolatilityRegime.COMPRESSION: Decimal("0.85"),
            VolatilityRegime.NORMAL: Decimal("0.40"),
            VolatilityRegime.EXPANSION: Decimal("0.20"),
            VolatilityRegime.EXTREME_EXPANSION: Decimal("0.00"),
        }
        phi_v = vol_scores.get(market_state.volatility, Decimal("0.40"))

        # 2. Transición (Peso 0.25)
        if market_state.transition == RegimeTransition.COMPRESSION_TO_EXPANSION:
            phi_tau = Decimal("1.00")
        elif market_state.volatility in (VolatilityRegime.COMPRESSION, VolatilityRegime.EXTREME_COMPRESSION):
            phi_tau = Decimal("0.70")
        else:
            phi_tau = Decimal("0.20")

        # 3. Participación (Peso 0.20)
        part_scores = {
            ParticipationRegime.PARTICIPATION_EXPANSION: Decimal("1.00"),
            ParticipationRegime.VOLUME_SHOCK: Decimal("0.85"),
            ParticipationRegime.NORMAL_PARTICIPATION: Decimal("0.50"),
        }
        phi_p = part_scores.get(market_state.participation, Decimal("0.50"))

        # 4. Estructura (Peso 0.10)
        struct_scores = {
            StructureRegime.DIRECTIONAL: Decimal("1.00"),
            StructureRegime.TRANSITIONAL: Decimal("0.60"),
            StructureRegime.RANGE_BOUND: Decimal("0.30"),
        }
        phi_s = struct_scores.get(market_state.structure, Decimal("0.50"))

        # 5. Tendencia (Peso 0.10)
        if direction == TradeDirection.LONG:
            trend_scores = {
                TrendRegime.STRONG_BULL: Decimal("1.00"),
                TrendRegime.BULL: Decimal("0.80"),
                TrendRegime.NEUTRAL: Decimal("0.50"),
                TrendRegime.BEAR: Decimal("0.20"),
                TrendRegime.STRONG_BEAR: Decimal("0.00"),
            }
        else:
            trend_scores = {
                TrendRegime.STRONG_BEAR: Decimal("1.00"),
                TrendRegime.BEAR: Decimal("0.80"),
                TrendRegime.NEUTRAL: Decimal("0.50"),
                TrendRegime.BULL: Decimal("0.20"),
                TrendRegime.STRONG_BULL: Decimal("0.00"),
            }
        phi_t = trend_scores.get(market_state.trend, Decimal("0.50"))

        phi_d = Decimal("0.50")  # Peso 0.00

        composite = (
            cfg.w_A_volatility * phi_v
            + cfg.w_A_transition * phi_tau
            + cfg.w_A_participation * phi_p
            + cfg.w_A_structure * phi_s
            + cfg.w_A_trend * phi_t
            + cfg.w_A_derivatives * phi_d
        )
        composite = min(Decimal("1.00"), max(Decimal("0.00"), composite))

        breakdown = ScoreComponentBreakdown(
            trend_component=phi_t,
            volatility_component=phi_v,
            structure_component=phi_s,
            participation_component=phi_p,
            derivatives_component=phi_d,
            transition_component=phi_tau,
            composite_score=round(composite, 4),
        )
        return round(composite, 4), breakdown

    def calculate_score_alpha_b(
        self,
        market_state: MarketStateVector,
        direction: TradeDirection,
    ) -> tuple[Decimal, ScoreComponentBreakdown]:
        """Calcula el score de compatibilidad para Strategy B (Deep Pullback)."""
        cfg = self.config

        # 1. Tendencia (Peso 0.35)
        if direction == TradeDirection.LONG:
            trend_scores = {
                TrendRegime.STRONG_BULL: Decimal("1.00"),
                TrendRegime.BULL: Decimal("0.85"),
                TrendRegime.NEUTRAL: Decimal("0.20"),
                TrendRegime.BEAR: Decimal("0.00"),
                TrendRegime.STRONG_BEAR: Decimal("0.00"),
            }
        else:
            trend_scores = {
                TrendRegime.STRONG_BEAR: Decimal("1.00"),
                TrendRegime.BEAR: Decimal("0.85"),
                TrendRegime.NEUTRAL: Decimal("0.20"),
                TrendRegime.BULL: Decimal("0.00"),
                TrendRegime.STRONG_BULL: Decimal("0.00"),
            }
        phi_t = trend_scores.get(market_state.trend, Decimal("0.20"))

        # 2. Estructura (Peso 0.25)
        struct_scores = {
            StructureRegime.TRANSITIONAL: Decimal("1.00"),  # Retroceso saludable
            StructureRegime.DIRECTIONAL: Decimal("0.60"),
            StructureRegime.RANGE_BOUND: Decimal("0.15"),
        }
        phi_s = struct_scores.get(market_state.structure, Decimal("0.50"))

        # 3. Participación (Peso 0.20)
        part_scores = {
            ParticipationRegime.NORMAL_PARTICIPATION: Decimal("0.90"),  # Volumen secándose en retroceso
            ParticipationRegime.PARTICIPATION_EXPANSION: Decimal("0.50"),
            ParticipationRegime.VOLUME_SHOCK: Decimal("0.20"),  # Liquidación violenta
        }
        phi_p = part_scores.get(market_state.participation, Decimal("0.50"))

        # 4. Volatilidad (Peso 0.15)
        vol_scores = {
            VolatilityRegime.NORMAL: Decimal("0.90"),
            VolatilityRegime.COMPRESSION: Decimal("0.70"),
            VolatilityRegime.EXPANSION: Decimal("0.50"),
            VolatilityRegime.EXTREME_COMPRESSION: Decimal("0.40"),
            VolatilityRegime.EXTREME_EXPANSION: Decimal("0.10"),
        }
        phi_v = vol_scores.get(market_state.volatility, Decimal("0.50"))

        # 5. Transición (Peso 0.05)
        if market_state.transition == RegimeTransition.TREND_TO_PULLBACK:
            phi_tau = Decimal("1.00")
        elif market_state.transition == RegimeTransition.STABLE_REGIME:
            phi_tau = Decimal("0.60")
        else:
            phi_tau = Decimal("0.20")

        phi_d = Decimal("0.50")

        composite = (
            cfg.w_B_trend * phi_t
            + cfg.w_B_structure * phi_s
            + cfg.w_B_participation * phi_p
            + cfg.w_B_volatility * phi_v
            + cfg.w_B_transition * phi_tau
            + cfg.w_B_derivatives * phi_d
        )
        composite = min(Decimal("1.00"), max(Decimal("0.00"), composite))

        breakdown = ScoreComponentBreakdown(
            trend_component=phi_t,
            volatility_component=phi_v,
            structure_component=phi_s,
            participation_component=phi_p,
            derivatives_component=phi_d,
            transition_component=phi_tau,
            composite_score=round(composite, 4),
        )
        return round(composite, 4), breakdown

    def calculate_score_alpha_c(
        self,
        market_state: MarketStateVector,
        direction: TradeDirection,
    ) -> tuple[Decimal, ScoreComponentBreakdown]:
        """Calcula el score de compatibilidad para Strategy C (Liquidity Sweep - Core Engine)."""
        cfg = self.config

        # 1. Estructura (Peso 0.35) - Core: 76.5% del mercado
        struct_scores = {
            StructureRegime.RANGE_BOUND: Decimal("1.00"),
            StructureRegime.TRANSITIONAL: Decimal("0.40"),
            StructureRegime.DIRECTIONAL: Decimal("0.00"),
        }
        phi_s = struct_scores.get(market_state.structure, Decimal("0.50"))

        # 2. Transición (Peso 0.25)
        if market_state.transition == RegimeTransition.RANGE_TO_SWEEP:
            phi_tau = Decimal("1.00")
        elif market_state.structure == StructureRegime.RANGE_BOUND:
            phi_tau = Decimal("0.70")
        else:
            phi_tau = Decimal("0.20")

        # 3. Participación (Peso 0.20)
        part_scores = {
            ParticipationRegime.VOLUME_SHOCK: Decimal("1.00"),  # Vela de barrido
            ParticipationRegime.PARTICIPATION_EXPANSION: Decimal("0.85"),
            ParticipationRegime.NORMAL_PARTICIPATION: Decimal("0.40"),
        }
        phi_p = part_scores.get(market_state.participation, Decimal("0.40"))

        # 4. Tendencia (Peso 0.15)
        trend_scores = {
            TrendRegime.NEUTRAL: Decimal("1.00"),
            TrendRegime.BULL: Decimal("0.60"),
            TrendRegime.BEAR: Decimal("0.60"),
            TrendRegime.STRONG_BULL: Decimal("0.10"),
            TrendRegime.STRONG_BEAR: Decimal("0.10"),
        }
        phi_t = trend_scores.get(market_state.trend, Decimal("0.50"))

        # 5. Volatilidad (Peso 0.05)
        vol_scores = {
            VolatilityRegime.NORMAL: Decimal("0.80"),
            VolatilityRegime.COMPRESSION: Decimal("0.70"),
            VolatilityRegime.EXPANSION: Decimal("0.60"),
            VolatilityRegime.EXTREME_COMPRESSION: Decimal("0.50"),
            VolatilityRegime.EXTREME_EXPANSION: Decimal("0.30"),
        }
        phi_v = vol_scores.get(market_state.volatility, Decimal("0.50"))

        phi_d = Decimal("0.50")

        composite = (
            cfg.w_C_structure * phi_s
            + cfg.w_C_transition * phi_tau
            + cfg.w_C_participation * phi_p
            + cfg.w_C_trend * phi_t
            + cfg.w_C_volatility * phi_v
            + cfg.w_C_derivatives * phi_d
        )
        composite = min(Decimal("1.00"), max(Decimal("0.00"), composite))

        breakdown = ScoreComponentBreakdown(
            trend_component=phi_t,
            volatility_component=phi_v,
            structure_component=phi_s,
            participation_component=phi_p,
            derivatives_component=phi_d,
            transition_component=phi_tau,
            composite_score=round(composite, 4),
        )
        return round(composite, 4), breakdown

    def calculate_score_alpha_d(
        self,
        market_state: MarketStateVector,
        direction: TradeDirection,
        derivative_event: bool = False,
    ) -> tuple[Decimal, ScoreComponentBreakdown]:
        """Calcula el score de compatibilidad para Strategy D (Derivatives Exhaustion).

        Desacoplamiento Estricto: NO depende de trigger_15m ni de gatillos técnicos intradiarios.
        """
        cfg = self.config

        # 1. Derivados (Peso 0.40)
        if direction == TradeDirection.LONG:
            # Agotamiento de ventas / liquidación de shorts
            deriv_scores = {
                DerivativesRegime.FORCED_DELEVERAGING_CONFIRMED: Decimal("1.00"),
                DerivativesRegime.DERIVATIVES_STRESS: Decimal("0.90"),
                DerivativesRegime.EXTREME_CROWDED_SHORT: Decimal("0.80"),
                DerivativesRegime.EXTREME_CROWDED_LONG: Decimal("0.10"),
                DerivativesRegime.NEUTRAL: Decimal("0.10"),
            }
        else:
            # Agotamiento de compras / liquidación de longs
            deriv_scores = {
                DerivativesRegime.FORCED_DELEVERAGING_CONFIRMED: Decimal("1.00"),
                DerivativesRegime.DERIVATIVES_STRESS: Decimal("0.90"),
                DerivativesRegime.EXTREME_CROWDED_LONG: Decimal("0.80"),
                DerivativesRegime.EXTREME_CROWDED_SHORT: Decimal("0.10"),
                DerivativesRegime.NEUTRAL: Decimal("0.10"),
            }
        phi_d = deriv_scores.get(market_state.derivatives, Decimal("0.10"))
        if derivative_event:
            phi_d = max(phi_d, Decimal("0.85"))

        # 2. Volatilidad (Peso 0.25)
        vol_scores = {
            VolatilityRegime.EXTREME_EXPANSION: Decimal("1.00"),
            VolatilityRegime.EXPANSION: Decimal("0.70"),
            VolatilityRegime.NORMAL: Decimal("0.30"),
            VolatilityRegime.COMPRESSION: Decimal("0.10"),
            VolatilityRegime.EXTREME_COMPRESSION: Decimal("0.00"),
        }
        phi_v = vol_scores.get(market_state.volatility, Decimal("0.30"))

        # 3. Participación (Peso 0.20)
        part_scores = {
            ParticipationRegime.VOLUME_SHOCK: Decimal("1.00"),
            ParticipationRegime.PARTICIPATION_EXPANSION: Decimal("0.70"),
            ParticipationRegime.NORMAL_PARTICIPATION: Decimal("0.20"),
        }
        phi_p = part_scores.get(market_state.participation, Decimal("0.20"))

        # 4. Transición (Peso 0.10)
        trans_scores = {
            RegimeTransition.CLIMAX_TO_REVERSAL: Decimal("1.00"),
            RegimeTransition.TREND_TO_CLIMAX: Decimal("0.90"),
            RegimeTransition.STABLE_REGIME: Decimal("0.30"),
        }
        phi_tau = trans_scores.get(market_state.transition, Decimal("0.20"))

        # 5. Tendencia (Peso 0.05)
        if direction == TradeDirection.LONG:
            trend_scores = {
                TrendRegime.STRONG_BEAR: Decimal("1.00"),
                TrendRegime.BEAR: Decimal("0.70"),
                TrendRegime.NEUTRAL: Decimal("0.40"),
                TrendRegime.BULL: Decimal("0.20"),
                TrendRegime.STRONG_BULL: Decimal("0.10"),
            }
        else:
            trend_scores = {
                TrendRegime.STRONG_BULL: Decimal("1.00"),
                TrendRegime.BULL: Decimal("0.70"),
                TrendRegime.NEUTRAL: Decimal("0.40"),
                TrendRegime.BEAR: Decimal("0.20"),
                TrendRegime.STRONG_BEAR: Decimal("0.10"),
            }
        phi_t = trend_scores.get(market_state.trend, Decimal("0.30"))

        phi_s = Decimal("0.50")

        composite = (
            cfg.w_D_derivatives * phi_d
            + cfg.w_D_volatility * phi_v
            + cfg.w_D_participation * phi_p
            + cfg.w_D_transition * phi_tau
            + cfg.w_D_trend * phi_t
            + cfg.w_D_structure * phi_s
        )
        composite = min(Decimal("1.00"), max(Decimal("0.00"), composite))

        breakdown = ScoreComponentBreakdown(
            trend_component=phi_t,
            volatility_component=phi_v,
            structure_component=phi_s,
            participation_component=phi_p,
            derivatives_component=phi_d,
            transition_component=phi_tau,
            composite_score=round(composite, 4),
        )
        return round(composite, 4), breakdown

    # ==========================================================================
    # 3. EVALUACIÓN DIRECCIONAL INTEGRAL (DIRECTIONAL SCORE)
    # ==========================================================================

    def score_strategy(
        self,
        strategy_id: AlphaMotorId,
        market_state: MarketStateVector,
        derivative_event: bool = False,
    ) -> tuple[DirectionalScore, bool]:
        """Calcula el DirectionalScore y el estado del Hard Gate para una estrategia."""
        gate_long = self.evaluate_hard_gate(strategy_id, market_state, TradeDirection.LONG)
        gate_short = self.evaluate_hard_gate(strategy_id, market_state, TradeDirection.SHORT)

        if strategy_id == AlphaMotorId.ALPHA_A:
            s_long, bd_long = self.calculate_score_alpha_a(market_state, TradeDirection.LONG)
            s_short, bd_short = self.calculate_score_alpha_a(market_state, TradeDirection.SHORT)
        elif strategy_id == AlphaMotorId.ALPHA_B:
            s_long, bd_long = self.calculate_score_alpha_b(market_state, TradeDirection.LONG)
            s_short, bd_short = self.calculate_score_alpha_b(market_state, TradeDirection.SHORT)
        elif strategy_id == AlphaMotorId.ALPHA_C:
            s_long, bd_long = self.calculate_score_alpha_c(market_state, TradeDirection.LONG)
            s_short, bd_short = self.calculate_score_alpha_c(market_state, TradeDirection.SHORT)
        elif strategy_id == AlphaMotorId.ALPHA_D:
            s_long, bd_long = self.calculate_score_alpha_d(market_state, TradeDirection.LONG, derivative_event)
            s_short, bd_short = self.calculate_score_alpha_d(market_state, TradeDirection.SHORT, derivative_event)
        else:
            raise ValueError(f"Motor no reconocido: {strategy_id}")

        combined = max(s_long, s_short)
        hard_gate_passed = gate_long or gate_short

        dir_score = DirectionalScore(
            long_score=s_long,
            short_score=s_short,
            combined_score=combined,
            long_breakdown=bd_long,
            short_breakdown=bd_short,
        )
        return dir_score, hard_gate_passed

    def score_all_strategies(
        self,
        market_state: MarketStateVector,
        derivative_event: bool = False,
    ) -> dict[AlphaMotorId, tuple[DirectionalScore, bool]]:
        """Evalúa todas las 4 estrategias devolviendo su DirectionalScore y Hard Gate."""
        results = {}
        for strat in [
            AlphaMotorId.ALPHA_A,
            AlphaMotorId.ALPHA_B,
            AlphaMotorId.ALPHA_C,
            AlphaMotorId.ALPHA_D,
        ]:
            results[strat] = self.score_strategy(strat, market_state, derivative_event)
        return results
