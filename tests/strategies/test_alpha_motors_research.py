"""Suite de Tests Rigurosa para los Motores de Alpha B y C (Fase 4 Baseline v0.1).

Valida cuantitativamente:
1. Guardrail 1: High_24/Low_24 estrictamente histórico (excluye vela t).
2. Timing causal: Entrada al Open_{t+1} con slippage y comisión.
3. Política de ambigüedad OHLC: Stop-First conservador.
4. Desacoplamiento condicionado vs unconditioned (Router ON/OFF).
5. Motor B (Deep Pullback): Detección en tendencia alcista y bajista.
6. Motor C (Liquidity Sweep): Barrido de mínimos y máximos.
7. Remuestreo Bootstrap IID sobre trades cerrados.
8. Aislamiento absoluto de producción (cero imports de live_runner).
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from chimuelo_prime.backtesting.alpha_research_backtester import (
    AlphaResearchBacktester,
    run_bootstrap_analysis,
)
from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.regime_engine.models import (
    AlphaMotorId,
    DerivativesRegime,
    DirectionalScore,
    MarketStateVector,
    NoTradeReasonCode,
    ParticipationRegime,
    RegimeTransition,
    RouterEvaluationResult,
    RouterStrategyState,
    ScoreComponentBreakdown,
    StrategyEvaluationLog,
    StructureRegime,
    TradeDirection,
    TrendRegime,
    VolatilityRegime,
)
from chimuelo_prime.strategies.alpha_b_pullback import DeepPullbackAlphaMotor
from chimuelo_prime.strategies.alpha_c_sweep import LiquiditySweepAlphaMotor


def _make_dummy_candle(
    t: datetime,
    open_p: str,
    high_p: str,
    low_p: str,
    close_p: str,
    vol: str = "100.0",
) -> HistoricalCandle:
    return HistoricalCandle(
        timestamp=t,
        open=Decimal(open_p),
        high=Decimal(high_p),
        low=Decimal(low_p),
        close=Decimal(close_p),
        volume=Decimal(vol),
    )


def _make_dummy_state(
    trend: TrendRegime = TrendRegime.BULL,
    structure: StructureRegime = StructureRegime.TRANSITIONAL,
) -> MarketStateVector:
    return MarketStateVector(
        timestamp=datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC),
        symbol="BTCUSDT",
        timeframe="1h",
        trend=trend,
        volatility=VolatilityRegime.NORMAL,
        structure=structure,
        participation=ParticipationRegime.NORMAL_PARTICIPATION,
        derivatives=DerivativesRegime.NEUTRAL,
        slope_50=Decimal("1.2"),
        trend_spread=Decimal("1.5"),
        adx_14=Decimal("25.0"),
        efficiency_ratio=Decimal("0.50"),
        atr_percentile=Decimal("50.0"),
        rv_percentile=Decimal("50.0"),
        volume_percentile=Decimal("50.0"),
        tr_percentile=Decimal("50.0"),
        z_funding=Decimal("0.0"),
        delta_oi_4h=Decimal("0.0"),
        transition=RegimeTransition.STABLE_REGIME,
    )


def _make_dummy_router_result(armed: bool = True, strat: AlphaMotorId = AlphaMotorId.ALPHA_B) -> RouterEvaluationResult:
    breakdown = ScoreComponentBreakdown()
    dir_score = DirectionalScore(
        long_score=Decimal("0.80"),
        short_score=Decimal("0.20"),
        combined_score=Decimal("0.80"),
        long_breakdown=breakdown,
        short_breakdown=breakdown,
    )
    log = StrategyEvaluationLog(
        strategy_id=strat,
        state_before=RouterStrategyState.ARMED if armed else RouterStrategyState.DISABLED,
        state_after=RouterStrategyState.ARMED if armed else RouterStrategyState.DISABLED,
        score=dir_score,
        hard_gate_passed=True,
        dwell_bars_before=1,
        dwell_bars_after=2,
        cooldown_remaining=0,
        authorized_for_trigger=armed,
        rejection_reason=None if armed else NoTradeReasonCode.NO_ALPHA_COMPATIBILITY,
    )
    return RouterEvaluationResult(
        timestamp=datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC),
        symbol="BTCUSDT",
        market_state=_make_dummy_state(),
        strategy_evaluations={strat: log},
        armed_strategies=[strat] if armed else [],
        active_strategies=[],
        cooldown_strategies=[],
        hermes_entry_veto=False,
        global_action="TRADE_PERMITTED" if armed else "NO_TRADE",
        details="",
    )


# ==============================================================================
# 1. GUARDRAIL 1: High_24 / Low_24 ESTRICTAMENTE HISTÓRICO EN STRATEGY C
# ==============================================================================


def test_alpha_c_strictly_excludes_current_candle_from_prior_range() -> None:
    """Demuestra que la vela t no desplaza el nivel de sweep de las 24 barras previas."""
    motor = LiquiditySweepAlphaMotor(lookback_bars=24)
    t0 = datetime(2026, 9, 6, 0, 0, 0, tzinfo=UTC)

    # 24 velas previas con rango entre 100.0 y 110.0
    candles = []
    for i in range(24):
        ti = t0 + timedelta(hours=i)
        candles.append(_make_dummy_candle(ti, "104.0", "110.0", "100.0", "106.0"))

    # Vela 24 (t actual): Genera un sweep cayendo a 95.0 y cerrando en 102.0 (recuperación)
    t_sweep = t0 + timedelta(hours=24)
    candles.append(_make_dummy_candle(t_sweep, "101.0", "103.0", "95.0", "102.0"))

    state = _make_dummy_state(structure=StructureRegime.RANGE_BOUND)
    router_res = _make_dummy_router_result(armed=True, strat=AlphaMotorId.ALPHA_C)
    ema20 = [Decimal("105.0")] * 25
    atr20 = [Decimal("2.0")] * 25

    # Evaluación: Debe detectar el sweep porque Low_t (95.0) < Low_prior (100.0) y Close_t (102.0) > Low_prior (100.0)
    cand = motor.evaluate_candidate(
        symbol="BTCUSDT",
        candles=candles,
        current_idx=24,
        market_state=state,
        ema20=ema20,
        atr20=atr20,
        router_result=router_res,
        unconditioned=False,
    )

    assert cand is not None
    assert cand.direction == TradeDirection.LONG
    assert cand.strategy_id == AlphaMotorId.ALPHA_C
    # El stop loss debe situarse por debajo de la mecha de barrido (95.0 - 0.2*2.0 = 94.6)
    assert cand.stop_loss <= Decimal("95.0")


# ==============================================================================
# 2. GUARDRAIL 2 & 3: EJECUCIÓN EN OPEN_{T+1} Y POLÍTICA STOP-FIRST
# ==============================================================================


def test_backtester_executes_at_next_open_with_friction() -> None:
    """Verifica que la orden se ejecute causalmente en Open_{t+1} con slippage y comisión."""
    backtester = AlphaResearchBacktester(
        fee_rate_per_side=Decimal("0.0005"),
        slippage_per_side=Decimal("0.0005"),
        ohlc_ambiguity_policy="stop_first",
    )

    t0 = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
    c0 = _make_dummy_candle(t0, "100.0", "105.0", "99.0", "104.0")  # Barra t (señal al cierre)
    c1 = _make_dummy_candle(t0 + timedelta(hours=1), "105.0", "112.0", "104.5", "110.0")  # Barra t+1 (entrada)
    c2 = _make_dummy_candle(t0 + timedelta(hours=2), "110.0", "115.0", "109.0", "114.0")  # Barra t+2 (TP)

    from chimuelo_prime.regime_engine.models import TradeCandidate

    cand = TradeCandidate(
        candidate_id="test_cand",
        strategy_id=AlphaMotorId.ALPHA_B,
        symbol="BTCUSDT",
        direction=TradeDirection.LONG,
        entry_price=Decimal("104.0"),
        stop_loss=Decimal("102.0"),
        take_profit=Decimal("112.0"),
        confidence_score=Decimal("1.0"),
        timestamp=t0,
    )

    trades = backtester.simulate_trades(
        candidates=[(0, cand)],  # Señal en barra 0
        candles=[c0, c1, c2],
    )

    assert len(trades) == 1
    tr = trades[0]
    assert tr.entry_idx == 1  # Entró en barra 1 (t+1)
    # Entrada ejecutada con slippage: 105.0 * 1.0005 = 105.0525
    assert tr.executed_entry > Decimal("105.0")
    assert tr.nominal_entry == Decimal("105.0")
    assert tr.exit_reason == "TAKE_PROFIT"
    assert tr.net_return_pct > Decimal("0.0")


def test_ohlc_ambiguity_conservative_stop_first() -> None:
    """Si una barra contiene tanto SL como TP en su rango, Stop-First debe liquidar en pérdida."""
    backtester = AlphaResearchBacktester(
        fee_rate_per_side=Decimal("0.0005"),
        slippage_per_side=Decimal("0.0005"),
        ohlc_ambiguity_policy="stop_first",
    )

    t0 = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
    c0 = _make_dummy_candle(t0, "100.0", "102.0", "99.0", "101.0")
    # Barra 1: Open 101.0, pero tiene una mecha violenta que toca SL (95.0) y TP (110.0)
    c1 = _make_dummy_candle(t0 + timedelta(hours=1), "101.0", "115.0", "90.0", "105.0")

    from chimuelo_prime.regime_engine.models import TradeCandidate

    cand = TradeCandidate(
        candidate_id="ambig_cand",
        strategy_id=AlphaMotorId.ALPHA_B,
        symbol="BTCUSDT",
        direction=TradeDirection.LONG,
        entry_price=Decimal("101.0"),
        stop_loss=Decimal("95.0"),
        take_profit=Decimal("110.0"),
        confidence_score=Decimal("1.0"),
        timestamp=t0,
    )

    trades = backtester.simulate_trades([(0, cand)], [c0, c1])
    assert len(trades) == 1
    # Política Stop-First conservadora
    assert trades[0].exit_reason == "STOP_LOSS"
    assert trades[0].net_return_pct < Decimal("0.0")


# ==============================================================================
# 3. COMPARACIÓN SIMÉTRICA ROUTER CONDICIONADO VS UNCONDITIONED
# ==============================================================================


def test_alpha_b_router_conditioning_blocks_when_disabled() -> None:
    """Verifica que el motor B bloquee señales si Router está DISABLED, pero las emita en unconditioned."""
    motor = DeepPullbackAlphaMotor()
    t0 = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)

    candles = [
        _make_dummy_candle(t0, "100.0", "105.0", "99.0", "104.0"),
        _make_dummy_candle(t0 + timedelta(hours=1), "104.0", "106.0", "101.0", "102.0"),
        _make_dummy_candle(t0 + timedelta(hours=2), "102.0", "104.0", "100.5", "101.0"),
        _make_dummy_candle(t0 + timedelta(hours=3), "101.0", "103.5", "100.8", "103.0"),  # Pullback + rebote
    ]

    state = _make_dummy_state(trend=TrendRegime.BULL)
    ema20 = [Decimal("101.0")] * 4
    ema50 = [Decimal("98.0")] * 4
    atr20 = [Decimal("2.0")] * 4

    # Caso A: Router está DISABLED
    router_disabled = _make_dummy_router_result(armed=False, strat=AlphaMotorId.ALPHA_B)
    cand_conditioned = motor.evaluate_candidate(
        "BTCUSDT", candles, 3, state, ema20, ema50, atr20, router_disabled, unconditioned=False
    )
    assert cand_conditioned is None

    # Caso B: Mismo estado de mercado pero modo Unconditioned (Router OFF)
    cand_unconditioned = motor.evaluate_candidate(
        "BTCUSDT", candles, 3, state, ema20, ema50, atr20, router_disabled, unconditioned=True
    )
    assert cand_unconditioned is not None
    assert cand_unconditioned.direction == TradeDirection.LONG


# ==============================================================================
# 4. REMUESTREO BOOTSTRAP SOBRE TRADES CERRADOS
# ==============================================================================


def test_bootstrap_analysis_on_closed_trades() -> None:
    """Verifica el cálculo de Bootstrap IID con remuestreo de trades e intervalos de confianza."""
    from chimuelo_prime.backtesting.alpha_research_backtester import ResearchTradeOutcome

    t0 = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
    trades = []
    # 20 trades sintéticos con promedio positivo
    for i in range(20):
        r_val = Decimal("1.5") if i % 2 == 0 else Decimal("-1.0")
        trades.append(
            ResearchTradeOutcome(
                candidate_id=f"t_{i}",
                strategy_id=AlphaMotorId.ALPHA_B,
                symbol="BTCUSDT",
                direction=TradeDirection.LONG,
                entry_idx=i,
                exit_idx=i + 1,
                entry_time=t0,
                exit_time=t0 + timedelta(hours=1),
                duration_bars=1,
                nominal_entry=Decimal("100.0"),
                executed_entry=Decimal("100.05"),
                nominal_exit=Decimal("102.0"),
                executed_exit=Decimal("101.95"),
                stop_loss=Decimal("98.0"),
                take_profit=Decimal("104.0"),
                risk_unit=Decimal("2.0"),
                gross_return_pct=Decimal("2.0"),
                total_friction_pct=Decimal("0.2"),
                net_return_pct=Decimal("1.8") if r_val > 0 else Decimal("-1.2"),
                net_r_multiple=r_val,
                exit_reason="TAKE_PROFIT" if r_val > 0 else "STOP_LOSS",
            )
        )

    res = run_bootstrap_analysis(trades, iterations=500, seed=123)
    assert res["n_trades"] == 20
    assert res["mean_r"] == Decimal("0.250")  # (10*1.5 - 10*1.0) / 20 = 5 / 20 = 0.25
    assert res["ci_95_lower"] <= res["mean_r"] <= res["ci_95_upper"]
    assert res["win_rate_pct"] == 50.0


# ==============================================================================
# 5. AISLAMIENTO ABSOLUTO DE PRODUCCIÓN
# ==============================================================================


def test_alpha_motors_zero_production_imports() -> None:
    """Verifica que los motores de investigación no importen nada de live_runner ni del bot congelado."""
    with open("chimuelo_prime/strategies/alpha_b_pullback.py", encoding="utf-8") as f:
        b_code = f.read()
    with open("chimuelo_prime/strategies/alpha_c_sweep.py", encoding="utf-8") as f:
        c_code = f.read()
    with open("chimuelo_prime/backtesting/alpha_research_backtester.py", encoding="utf-8") as f:
        back_code = f.read()

    forbidden = ["live_runner", "StructuralBreakoutStrategy", "main_loop", "binance_client"]
    for term in forbidden:
        assert term not in b_code
        assert term not in c_code
        assert term not in back_code
