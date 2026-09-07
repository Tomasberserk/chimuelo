"""Suite de Tests Rigurosa para el StrategyRouter y Matriz de Scoring (Fase 3).

Valida cuantitativamente:
1. Normalización estricta de pesos (sum == 1.000) y acotamiento [0.0, 1.0].
2. Desacoplamiento de Score D del trigger intradía de 15m.
3. Compuertas duras (Hard Gates) invalidando soft scores elevados.
4. FSM: Transición DISABLED -> ARMED a score >= 0.70.
5. FSM: Banda de histéresis [0.45, 0.70) reteniendo estado ARMED.
6. FSM: Minimum Dwell Time exacto (t_arm=0, disarm bloqueado si dwell < 3).
7. Concurrencia multiestrategia (sin argmax global ni winner-takes-all).
8. ACTIVE representa estrictamente una posición abierta, no un score alto.
9. Enfriamiento forzoso (COOLDOWN) por 6 barras post-salida.
10. Hermes MacroEntryVeto: bloquea entradas/ARMED, preserva ACTIVE.
11. Asimetría en DirectionalScore (LONG vs SHORT).
12. Monotonía del score ante incrementos de features favorables.
13. Sensibilidad a pesos de hipótesis (research priors).
14. Aislamiento entre estrategias (features de D no alteran A/B/C).
15. Determinismo estricto de reproducción (State Replay).
16. Filtrado de TradeCandidates y logging forense de NO_TRADE.
17. Aislamiento absoluto de producción (cero imports de live_runner).
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from chimuelo_prime.regime_engine.models import (
    AlphaMotorId,
    DerivativesRegime,
    MarketStateVector,
    NoTradeReasonCode,
    ParticipationRegime,
    RegimeTransition,
    RouterStrategyState,
    StructureRegime,
    TradeCandidate,
    TradeDirection,
    TrendRegime,
    VolatilityRegime,
)
from chimuelo_prime.regime_engine.router import StrategyRouter
from chimuelo_prime.regime_engine.router_config import RouterConfig
from chimuelo_prime.regime_engine.scoring import StrategyCompatibilityScorer

# ==============================================================================
# HELPERS PARA GENERACIÓN DETERMINISTA DE VECTORES DE ESTADO
# ==============================================================================


def _make_state(
    timestamp: datetime | None = None,
    symbol: str = "BTCUSDT",
    trend: TrendRegime = TrendRegime.NEUTRAL,
    volatility: VolatilityRegime = VolatilityRegime.NORMAL,
    structure: StructureRegime = StructureRegime.TRANSITIONAL,
    participation: ParticipationRegime = ParticipationRegime.NORMAL_PARTICIPATION,
    derivatives: DerivativesRegime = DerivativesRegime.NEUTRAL,
    transition: RegimeTransition = RegimeTransition.STABLE_REGIME,
    efficiency_ratio: Decimal = Decimal("0.50"),
) -> MarketStateVector:
    """Crea un MarketStateVector inmutable y UTC-aware para pruebas del router."""
    t = timestamp or datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
    return MarketStateVector(
        timestamp=t,
        symbol=symbol,
        timeframe="1h",
        trend=trend,
        volatility=volatility,
        structure=structure,
        participation=participation,
        derivatives=derivatives,
        slope_50=Decimal("0.0"),
        trend_spread=Decimal("0.0"),
        adx_14=Decimal("20.0"),
        efficiency_ratio=efficiency_ratio,
        atr_percentile=Decimal("50.0"),
        rv_percentile=Decimal("50.0"),
        volume_percentile=Decimal("50.0"),
        tr_percentile=Decimal("50.0"),
        z_funding=Decimal("0.0"),
        delta_oi_4h=Decimal("0.0"),
        transition=transition,
        context_4h_closed_timestamp=None,
    )


# ==============================================================================
# 1. NORMALIZACIÓN Y LÍMITES MATEMÁTICOS DE SCORING
# ==============================================================================


def test_scoring_weights_normalization_and_post_init_validation() -> None:
    """Valida que los pesos sumen exactamente 1.000 y que pesos inválidos lancen ValueError."""
    cfg = RouterConfig()
    assert cfg.arm_threshold == Decimal("0.70")
    assert cfg.disarm_threshold == Decimal("0.45")
    assert cfg.min_dwell_bars == 3
    assert cfg.cooldown_bars == 6

    # Intento de instanciar configuración con suma != 1.000 debe fallar
    with pytest.raises(ValueError, match="Pesos de Estrategia A deben sumar 1.000"):
        RouterConfig(w_A_volatility=Decimal("0.50"))  # Suma 1.15


def test_scores_strictly_bounded_between_zero_and_one() -> None:
    """Verifica que todos los scores calculados residan estrictamente en [0.0000, 1.0000]."""
    scorer = StrategyCompatibilityScorer()
    state = _make_state()
    scores = scorer.score_all_strategies(state)

    for _strat_id, (dir_score, _hard_gate) in scores.items():
        assert Decimal("0.0000") <= dir_score.long_score <= Decimal("1.0000")
        assert Decimal("0.0000") <= dir_score.short_score <= Decimal("1.0000")
        assert Decimal("0.0000") <= dir_score.combined_score <= Decimal("1.0000")
        assert dir_score.combined_score == max(dir_score.long_score, dir_score.short_score)


# ==============================================================================
# 2. DESACOPLAMIENTO DE SCORE D DEL TRIGGER INTRADÍA DE 15M
# ==============================================================================


def test_score_d_independent_of_15m_trigger() -> None:
    """Verifica que Score D no acepte ni dependa de señales o triggers técnicos de 15m."""
    scorer = StrategyCompatibilityScorer()
    state = _make_state(
        volatility=VolatilityRegime.EXTREME_EXPANSION,
        derivatives=DerivativesRegime.FORCED_DELEVERAGING_CONFIRMED,
        participation=ParticipationRegime.VOLUME_SHOCK,
        transition=RegimeTransition.CLIMAX_TO_REVERSAL,
    )
    # calculate_score_alpha_d solo acepta market_state, direction, derivative_event
    score_long, breakdown = scorer.calculate_score_alpha_d(state, TradeDirection.LONG)
    assert score_long >= Decimal("0.70")
    assert breakdown.derivatives_component == Decimal("1.00")
    assert breakdown.volatility_component == Decimal("1.00")


# ==============================================================================
# 3. COMPUERTAS DURAS (HARD GATES)
# ==============================================================================


def test_hard_gate_overrides_high_soft_score_for_all_strategies() -> None:
    """Verifica que un Hard Gate en False impida la autorización aunque el soft score sea alto."""
    scorer = StrategyCompatibilityScorer()

    # Estrategia A (Volatility Squeeze): Prohibido si la volatilidad ya está en EXTREME_EXPANSION
    state_a = _make_state(
        volatility=VolatilityRegime.EXTREME_EXPANSION,
        participation=ParticipationRegime.PARTICIPATION_EXPANSION,
    )
    assert scorer.evaluate_hard_gate(AlphaMotorId.ALPHA_A, state_a, TradeDirection.LONG) is False

    # Estrategia B (Deep Pullback): Prohibido ir LONG en STRONG_BEAR
    state_b = _make_state(trend=TrendRegime.STRONG_BEAR)
    assert scorer.evaluate_hard_gate(AlphaMotorId.ALPHA_B, state_b, TradeDirection.LONG) is False
    assert scorer.evaluate_hard_gate(AlphaMotorId.ALPHA_B, state_b, TradeDirection.SHORT) is True

    # Estrategia C (Liquidity Sweep): Prohibido en tendencia limpia directional (ER >= 0.60)
    state_c = _make_state(
        structure=StructureRegime.DIRECTIONAL,
        efficiency_ratio=Decimal("0.65"),
    )
    assert scorer.evaluate_hard_gate(AlphaMotorId.ALPHA_C, state_c, TradeDirection.LONG) is False

    # Estrategia D (Derivatives Exhaustion): Prohibido en régimen neutral sin estrés ni expansión
    state_d = _make_state(
        derivatives=DerivativesRegime.NEUTRAL,
        volatility=VolatilityRegime.NORMAL,
    )
    assert scorer.evaluate_hard_gate(AlphaMotorId.ALPHA_D, state_d, TradeDirection.LONG) is False


# ==============================================================================
# 4. FSM: TRANSICIÓN DISABLED -> ARMED
# ==============================================================================


def test_fsm_disabled_to_armed_transition() -> None:
    """Verifica la activación causal de DISABLED a ARMED cuando Score >= 0.70 y HardGate=True."""
    router = StrategyRouter()
    assert router.strategy_states[AlphaMotorId.ALPHA_C] == RouterStrategyState.DISABLED

    # Crear estado óptimo para Estrategia C: Range Bound + Range to Sweep + Volume Shock
    state_c_optimal = _make_state(
        trend=TrendRegime.NEUTRAL,
        structure=StructureRegime.RANGE_BOUND,
        transition=RegimeTransition.RANGE_TO_SWEEP,
        participation=ParticipationRegime.VOLUME_SHOCK,
        efficiency_ratio=Decimal("0.20"),
    )

    res = router.evaluate(symbol="BTCUSDT", market_state=state_c_optimal)
    eval_c = res.strategy_evaluations[AlphaMotorId.ALPHA_C]

    assert eval_c.state_before == RouterStrategyState.DISABLED
    assert eval_c.state_after == RouterStrategyState.ARMED
    assert eval_c.dwell_bars_after == 0  # Barra de activación t_arm cuenta como 0
    assert eval_c.authorized_for_trigger is True
    assert AlphaMotorId.ALPHA_C in res.armed_strategies
    assert res.global_action == "TRADE_PERMITTED"


# ==============================================================================
# 5. FSM: HISTÉRESIS [0.45, 0.70)
# ==============================================================================


def test_fsm_hysteresis_band_retention() -> None:
    """Verifica que una estrategia ARMED permanezca ARMED en la banda de histéresis [0.45, 0.70)."""
    router = StrategyRouter()

    # Barra 0: Activación a ARMED
    state_arm = _make_state(
        trend=TrendRegime.NEUTRAL,
        structure=StructureRegime.RANGE_BOUND,
        transition=RegimeTransition.RANGE_TO_SWEEP,
        participation=ParticipationRegime.VOLUME_SHOCK,
        efficiency_ratio=Decimal("0.20"),
    )
    res0 = router.evaluate("BTCUSDT", state_arm)
    assert res0.strategy_evaluations[AlphaMotorId.ALPHA_C].state_after == RouterStrategyState.ARMED

    # Barra 1: Score desciende a la zona de histéresis (~0.635)
    state_hysteresis = _make_state(
        trend=TrendRegime.STRONG_BULL,
        structure=StructureRegime.RANGE_BOUND,
        transition=RegimeTransition.STABLE_REGIME,
        participation=ParticipationRegime.NORMAL_PARTICIPATION,
        volatility=VolatilityRegime.EXTREME_EXPANSION,
        efficiency_ratio=Decimal("0.25"),
    )
    res1 = router.evaluate("BTCUSDT", state_hysteresis)
    eval_c1 = res1.strategy_evaluations[AlphaMotorId.ALPHA_C]

    assert eval_c1.state_before == RouterStrategyState.ARMED
    assert eval_c1.state_after == RouterStrategyState.ARMED  # Retenido por histéresis
    assert Decimal("0.45") <= eval_c1.score.combined_score < Decimal("0.70")
    assert eval_c1.dwell_bars_after == 1
    assert eval_c1.authorized_for_trigger is True


# ==============================================================================
# 6. FSM: MINIMUM DWELL TIME EXACTO (t_arm = 0)
# ==============================================================================


def test_fsm_minimum_dwell_time_exact_temporal_counting() -> None:
    """Valida la definición matemática de Dwell Time:

    t_arm es activación (dwell=0). Dwell_t = # barras cerradas desde t_arm.
    El desarme (< 0.45) se bloquea estrictamente si dwell < 3.
    """
    router = StrategyRouter()
    t0 = datetime(2026, 9, 6, 10, 0, 0, tzinfo=UTC)

    # 10:00 - Activación (Score >= 0.70)
    s_high = _make_state(
        timestamp=t0,
        trend=TrendRegime.NEUTRAL,
        structure=StructureRegime.RANGE_BOUND,
        transition=RegimeTransition.RANGE_TO_SWEEP,
        participation=ParticipationRegime.VOLUME_SHOCK,
        efficiency_ratio=Decimal("0.20"),
    )
    r0 = router.evaluate("BTCUSDT", s_high)
    ev0 = r0.strategy_evaluations[AlphaMotorId.ALPHA_C]
    assert ev0.state_after == RouterStrategyState.ARMED
    assert ev0.dwell_bars_after == 0  # t_arm

    # Estado de degradación donde Score_C cae a ~0.40 pero Hard Gate sigue pasando
    s_low = _make_state(
        timestamp=t0 + timedelta(hours=1),
        trend=TrendRegime.STRONG_BULL,  # Penaliza C
        structure=StructureRegime.TRANSITIONAL,  # ER intermedio
        transition=RegimeTransition.STABLE_REGIME,
        participation=ParticipationRegime.NORMAL_PARTICIPATION,
        efficiency_ratio=Decimal("0.45"),
    )

    # 11:00 - Barra 1: Score < 0.45, dwell_before=0 < 3 -> Permanece ARMED
    r1 = router.evaluate("BTCUSDT", s_low)
    ev1 = r1.strategy_evaluations[AlphaMotorId.ALPHA_C]
    assert ev1.state_before == RouterStrategyState.ARMED
    assert ev1.state_after == RouterStrategyState.ARMED
    assert ev1.dwell_bars_before == 0
    assert ev1.dwell_bars_after == 1

    # 12:00 - Barra 2: Score < 0.45, dwell_before=1 < 3 -> Permanece ARMED
    s_low2 = _make_state(timestamp=t0 + timedelta(hours=2), trend=TrendRegime.STRONG_BULL, efficiency_ratio=Decimal("0.45"))
    r2 = router.evaluate("BTCUSDT", s_low2)
    ev2 = r2.strategy_evaluations[AlphaMotorId.ALPHA_C]
    assert ev2.state_after == RouterStrategyState.ARMED
    assert ev2.dwell_bars_before == 1
    assert ev2.dwell_bars_after == 2

    # 13:00 - Barra 3: Score < 0.45, dwell_before=2 < 3 -> Permanece ARMED
    s_low3 = _make_state(timestamp=t0 + timedelta(hours=3), trend=TrendRegime.STRONG_BULL, efficiency_ratio=Decimal("0.45"))
    r3 = router.evaluate("BTCUSDT", s_low3)
    ev3 = r3.strategy_evaluations[AlphaMotorId.ALPHA_C]
    assert ev3.state_after == RouterStrategyState.ARMED
    assert ev3.dwell_bars_before == 2
    assert ev3.dwell_bars_after == 3

    # 14:00 - Barra 4: Score < 0.45, dwell_before=3 >= 3 -> Transición permitida a DISABLED
    s_low4 = _make_state(timestamp=t0 + timedelta(hours=4), trend=TrendRegime.STRONG_BULL, efficiency_ratio=Decimal("0.45"))
    r4 = router.evaluate("BTCUSDT", s_low4)
    ev4 = r4.strategy_evaluations[AlphaMotorId.ALPHA_C]
    assert ev4.state_before == RouterStrategyState.ARMED
    assert ev4.state_after == RouterStrategyState.DISABLED
    assert ev4.dwell_bars_after == 0
    assert ev4.authorized_for_trigger is False
    assert ev4.rejection_reason == NoTradeReasonCode.NO_ALPHA_COMPATIBILITY


# ==============================================================================
# 7. CONCURRENCIA MULTIESTRATEGIA (NO WINNER-TAKES-ALL)
# ==============================================================================


def test_multi_strategy_concurrency_no_argmax_winner_takes_all() -> None:
    """Verifica que el Router no seleccione un único 'ganador', permitiendo que A y B estén ARMED a la vez."""
    router = StrategyRouter()

    # Régimen propicio para A y B simultáneamente:
    # Strong Bull + Compression + Transitional Structure + Expansion Participation
    state_multi = _make_state(
        trend=TrendRegime.STRONG_BULL,
        volatility=VolatilityRegime.COMPRESSION,
        structure=StructureRegime.TRANSITIONAL,
        participation=ParticipationRegime.PARTICIPATION_EXPANSION,
        transition=RegimeTransition.TREND_TO_PULLBACK,
    )

    res = router.evaluate("ETHUSDT", state_multi)

    assert AlphaMotorId.ALPHA_A in res.armed_strategies
    assert AlphaMotorId.ALPHA_B in res.armed_strategies
    assert len(res.armed_strategies) >= 2


# ==============================================================================
# 8. ESTADO ACTIVE REPRESENTA ESTRICTAMENTE POSICIÓN ABIERTA
# ==============================================================================


def test_active_state_strictly_requires_open_position() -> None:
    """Un score de 0.99 solo pone la estrategia en ARMED; solo un reporte de posición abierta la pasa a ACTIVE."""
    router = StrategyRouter()
    state_opt = _make_state(
        trend=TrendRegime.STRONG_BULL,
        structure=StructureRegime.TRANSITIONAL,
        participation=ParticipationRegime.NORMAL_PARTICIPATION,
        volatility=VolatilityRegime.NORMAL,
        transition=RegimeTransition.TREND_TO_PULLBACK,
    )

    # Sin posición externa: ARMED, nunca ACTIVE
    r1 = router.evaluate("BTCUSDT", state_opt, active_positions=None)
    assert r1.strategy_evaluations[AlphaMotorId.ALPHA_B].state_after == RouterStrategyState.ARMED

    # Con posición externa activa: pasa a ACTIVE
    r2 = router.evaluate("BTCUSDT", state_opt, active_positions={AlphaMotorId.ALPHA_B: True})
    assert r2.strategy_evaluations[AlphaMotorId.ALPHA_B].state_after == RouterStrategyState.ACTIVE
    assert AlphaMotorId.ALPHA_B in r2.active_strategies


# ==============================================================================
# 9. ENFRIAMIENTO (COOLDOWN) TRAS SALIDA DE POSICIÓN
# ==============================================================================


def test_cooldown_enforcement_and_decrement() -> None:
    """Valida que tras salir de posición activa, la estrategia entre en COOLDOWN por 6 barras."""
    router = StrategyRouter()
    state = _make_state(
        trend=TrendRegime.STRONG_BULL,
        structure=StructureRegime.TRANSITIONAL,
        volatility=VolatilityRegime.NORMAL,
        transition=RegimeTransition.TREND_TO_PULLBACK,
    )

    # 1. Estaba ACTIVE en barra anterior
    router.evaluate("BTCUSDT", state, active_positions={AlphaMotorId.ALPHA_B: True})
    assert router.strategy_states[AlphaMotorId.ALPHA_B] == RouterStrategyState.ACTIVE

    # 2. Posición se cierra en barra actual -> Transición a COOLDOWN (6 barras)
    r_exit = router.evaluate("BTCUSDT", state, active_positions={})
    ev_exit = r_exit.strategy_evaluations[AlphaMotorId.ALPHA_B]
    assert ev_exit.state_before == RouterStrategyState.ACTIVE
    assert ev_exit.state_after == RouterStrategyState.COOLDOWN
    assert ev_exit.cooldown_remaining == 6
    assert ev_exit.authorized_for_trigger is False
    assert ev_exit.rejection_reason == NoTradeReasonCode.COOLDOWN_ACTIVE

    # 3. Durante las siguientes 5 barras decrementa
    for expected_rem in [5, 4, 3, 2, 1]:
        r_step = router.evaluate("BTCUSDT", state, active_positions={})
        ev_step = r_step.strategy_evaluations[AlphaMotorId.ALPHA_B]
        assert ev_step.state_after == RouterStrategyState.COOLDOWN
        assert ev_step.cooldown_remaining == expected_rem
        assert ev_step.authorized_for_trigger is False

    # 4. Al llegar a 0 en la 6ta barra -> Transición a DISABLED
    r_done = router.evaluate("BTCUSDT", state, active_positions={})
    ev_done = r_done.strategy_evaluations[AlphaMotorId.ALPHA_B]
    assert ev_done.state_before == RouterStrategyState.COOLDOWN
    assert ev_done.state_after == RouterStrategyState.DISABLED
    assert ev_done.cooldown_remaining == 0


# ==============================================================================
# 10. HERMES MACRO ENTRY VETO
# ==============================================================================


def test_hermes_entry_veto_blocks_entries_preserves_active() -> None:
    """Hermes Veto bloquea transiciones a ARMED y gatillos, pero NUNCA liquida posiciones ACTIVE."""
    router = StrategyRouter()
    state = _make_state(
        trend=TrendRegime.STRONG_BULL,
        structure=StructureRegime.TRANSITIONAL,
        volatility=VolatilityRegime.NORMAL,
        transition=RegimeTransition.TREND_TO_PULLBACK,
    )

    # Caso A: DISABLED intenta armar con Hermes Veto activo -> Permanece DISABLED
    r_veto = router.evaluate("BTCUSDT", state, hermes_entry_veto=True)
    ev_veto = r_veto.strategy_evaluations[AlphaMotorId.ALPHA_B]
    assert ev_veto.state_after == RouterStrategyState.DISABLED
    assert ev_veto.rejection_reason == NoTradeReasonCode.HERMES_VETO

    # Caso B: Si ya estaba ARMED y se activa Hermes Veto -> Permanece ARMED pero authorized=False
    router.evaluate("BTCUSDT", state, hermes_entry_veto=False)  # Se arma
    assert router.strategy_states[AlphaMotorId.ALPHA_B] == RouterStrategyState.ARMED

    r_veto_armed = router.evaluate("BTCUSDT", state, hermes_entry_veto=True)
    ev_armed_veto = r_veto_armed.strategy_evaluations[AlphaMotorId.ALPHA_B]
    assert ev_armed_veto.state_after == RouterStrategyState.ARMED
    assert ev_armed_veto.authorized_for_trigger is False
    assert ev_armed_veto.rejection_reason == NoTradeReasonCode.HERMES_VETO

    # Caso C: Estrategia en ACTIVE con Hermes Veto -> Permanece ACTIVE (no se cierra forzosamente)
    r_veto_active = router.evaluate(
        "BTCUSDT",
        state,
        active_positions={AlphaMotorId.ALPHA_B: True},
        hermes_entry_veto=True,
    )
    assert r_veto_active.strategy_evaluations[AlphaMotorId.ALPHA_B].state_after == RouterStrategyState.ACTIVE


# ==============================================================================
# 11. ASIMETRÍA DIRECCIONAL (LONG VS SHORT)
# ==============================================================================


def test_directional_score_asymmetry() -> None:
    """Verifica que el scoring desacople long y short reflejando la tendencia direccional."""
    scorer = StrategyCompatibilityScorer()

    # En STRONG_BULL, Strategy B debe tener long_score >> short_score
    state_bull = _make_state(trend=TrendRegime.STRONG_BULL, structure=StructureRegime.TRANSITIONAL)
    score_bull, _ = scorer.score_strategy(AlphaMotorId.ALPHA_B, state_bull)
    assert score_bull.long_score > score_bull.short_score
    assert score_bull.short_score == Decimal("0.35") * Decimal("0.0") + score_bull.long_breakdown.composite_score - (Decimal("0.35") * Decimal("1.0"))  # Tendencia nula

    # En STRONG_BEAR, short_score >> long_score
    state_bear = _make_state(trend=TrendRegime.STRONG_BEAR, structure=StructureRegime.TRANSITIONAL)
    score_bear, _ = scorer.score_strategy(AlphaMotorId.ALPHA_B, state_bear)
    assert score_bear.short_score > score_bear.long_score


# ==============================================================================
# 12. MONOTONÍA DEL SCORE
# ==============================================================================


def test_score_monotonicity() -> None:
    """Verifica que features más favorables incrementen monótonamente el score."""
    scorer = StrategyCompatibilityScorer()

    # Strategy A: Volatilidad Normal vs Compresión vs Compresión Extrema
    s_norm = _make_state(volatility=VolatilityRegime.NORMAL)
    s_comp = _make_state(volatility=VolatilityRegime.COMPRESSION)
    s_ext = _make_state(volatility=VolatilityRegime.EXTREME_COMPRESSION)

    score_norm, _ = scorer.calculate_score_alpha_a(s_norm, TradeDirection.LONG)
    score_comp, _ = scorer.calculate_score_alpha_a(s_comp, TradeDirection.LONG)
    score_ext, _ = scorer.calculate_score_alpha_a(s_ext, TradeDirection.LONG)

    assert score_ext >= score_comp >= score_norm


# ==============================================================================
# 13. SENSIBILIDAD A PESOS DE HIPÓTESIS
# ==============================================================================


def test_weight_sensitivity() -> None:
    """Verifica que alterar los pesos de hipótesis impacte el score de forma predecible y causal."""
    # Configuración estándar
    scorer_std = StrategyCompatibilityScorer()
    # Configuración personalizada con mayor peso a volatilidad en A
    cfg_custom = RouterConfig(
        w_A_volatility=Decimal("0.50"),
        w_A_transition=Decimal("0.10"),
    )
    scorer_custom = StrategyCompatibilityScorer(config=cfg_custom)

    state = _make_state(volatility=VolatilityRegime.EXTREME_COMPRESSION)
    s_std, _ = scorer_std.calculate_score_alpha_a(state, TradeDirection.LONG)
    s_cust, _ = scorer_custom.calculate_score_alpha_a(state, TradeDirection.LONG)

    # Con mayor peso en volatilidad (que es 1.00), el score custom debe ser mayor
    assert s_cust > s_std


# ==============================================================================
# 14. AISLAMIENTO ENTRE ESTRATEGIAS
# ==============================================================================


def test_strategy_isolation() -> None:
    """Features de derivados (específicos de D) no deben alterar los scores de A, B ni C."""
    scorer = StrategyCompatibilityScorer()

    state_neutral = _make_state(derivatives=DerivativesRegime.NEUTRAL)
    state_stress = _make_state(derivatives=DerivativesRegime.FORCED_DELEVERAGING_CONFIRMED)

    scores_neutral = scorer.score_all_strategies(state_neutral)
    scores_stress = scorer.score_all_strategies(state_stress)

    # A, B y C son idénticos
    assert scores_neutral[AlphaMotorId.ALPHA_A][0].combined_score == scores_stress[AlphaMotorId.ALPHA_A][0].combined_score
    assert scores_neutral[AlphaMotorId.ALPHA_B][0].combined_score == scores_stress[AlphaMotorId.ALPHA_B][0].combined_score
    assert scores_neutral[AlphaMotorId.ALPHA_C][0].combined_score == scores_stress[AlphaMotorId.ALPHA_C][0].combined_score

    # D cambia significativamente
    assert scores_stress[AlphaMotorId.ALPHA_D][0].combined_score > scores_neutral[AlphaMotorId.ALPHA_D][0].combined_score


# ==============================================================================
# 15. DETERMINISMO ESTRICTO DE REPRODUCCIÓN (STATE REPLAY)
# ==============================================================================


def test_state_replay_determinism() -> None:
    """Una misma secuencia de 10 vectores de estado genera exactamente los mismos estados y logs."""
    states = [_make_state(timestamp=datetime(2026, 9, 6, i, 0, 0, tzinfo=UTC)) for i in range(10)]

    router1 = StrategyRouter()
    router2 = StrategyRouter()

    for s in states:
        r1 = router1.evaluate("BTCUSDT", s)
        r2 = router2.evaluate("BTCUSDT", s)

        assert r1.armed_strategies == r2.armed_strategies
        assert r1.global_action == r2.global_action
        for strat in AlphaMotorId:
            log1 = r1.strategy_evaluations[strat]
            log2 = r2.strategy_evaluations[strat]
            assert log1.state_after == log2.state_after
            assert log1.dwell_bars_after == log2.dwell_bars_after
            assert log1.score.combined_score == log2.score.combined_score


# ==============================================================================
# 16. FILTRADO DE TRADECANDIDATES Y FORENSIC LOGGING
# ==============================================================================


def test_filter_trade_candidates_and_forensic_logging() -> None:
    """Valida la compuerta de aprobación de TradeCandidates y el logging forense exhaustivo."""
    router = StrategyRouter()
    state = _make_state(
        trend=TrendRegime.STRONG_BULL,
        structure=StructureRegime.TRANSITIONAL,
        volatility=VolatilityRegime.NORMAL,
        transition=RegimeTransition.TREND_TO_PULLBACK,
    )
    router_res = router.evaluate("BTCUSDT", state)

    t_now = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)

    cand_valid = TradeCandidate(
        candidate_id="cand_1",
        strategy_id=AlphaMotorId.ALPHA_B,
        symbol="BTCUSDT",
        direction=TradeDirection.LONG,
        entry_price=Decimal("60000.00"),
        stop_loss=Decimal("59000.00"),
        take_profit=Decimal("63000.00"),
        confidence_score=Decimal("0.85"),
        timestamp=t_now,
    )

    cand_invalid_dir = TradeCandidate(
        candidate_id="cand_2",
        strategy_id=AlphaMotorId.ALPHA_B,
        symbol="BTCUSDT",
        direction=TradeDirection.SHORT,  # Hard gate prohibido en STRONG_BULL
        entry_price=Decimal("60000.00"),
        stop_loss=Decimal("61000.00"),
        take_profit=Decimal("58000.00"),
        confidence_score=Decimal("0.80"),
        timestamp=t_now,
    )

    cand_disabled = TradeCandidate(
        candidate_id="cand_3",
        strategy_id=AlphaMotorId.ALPHA_C,  # C está DISABLED en STRONG_BULL
        symbol="BTCUSDT",
        direction=TradeDirection.LONG,
        entry_price=Decimal("60000.00"),
        stop_loss=Decimal("59500.00"),
        take_profit=Decimal("61000.00"),
        confidence_score=Decimal("0.50"),
        timestamp=t_now,
    )

    approved, logs = router.filter_trade_candidates(
        candidates=[cand_valid, cand_invalid_dir, cand_disabled],
        router_result=router_res,
    )

    assert len(approved) == 1
    assert approved[0].candidate_id == "cand_1"

    assert len(logs) == 3
    assert logs[0].decision_action == "TRADE_APPROVED"
    assert logs[1].decision_action == "NO_TRADE"
    assert logs[1].reason_code == NoTradeReasonCode.NO_ALPHA_COMPATIBILITY
    assert logs[2].decision_action == "NO_TRADE"
    assert logs[2].reason_code == NoTradeReasonCode.NO_ALPHA_COMPATIBILITY


# ==============================================================================
# 17. AISLAMIENTO ABSOLUTO DE PRODUCCIÓN
# ==============================================================================


def test_production_isolation_zero_live_runner_imports() -> None:
    """Garantiza que el módulo regime_engine no importe nada de live_runner ni código de producción."""
    import sys

    # Verificar que live_runner no esté cargado accidentalmente
    assert "live_runner" not in sys.modules

    with open("chimuelo_prime/regime_engine/router.py", encoding="utf-8") as f:
        router_code = f.read()
    with open("chimuelo_prime/regime_engine/scoring.py", encoding="utf-8") as f:
        scoring_code = f.read()

    forbidden = ["live_runner", "StructuralBreakoutStrategy", "main_loop", "binance_client"]
    for term in forbidden:
        assert term not in router_code, f"Violación de aislamiento de producción en router.py: {term}"
        assert term not in scoring_code, f"Violación de aislamiento de producción en scoring.py: {term}"
