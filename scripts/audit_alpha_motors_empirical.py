"""Auditoría Cuantitativa Empírica de los Alpha Motors B y C (Fase 4 Baseline v0.1).

Ejecuta el experimento sobre 50,178 barras reales (BTCUSDT, ETHUSDT, SOLUSDT):
1. Comparación simétrica estricta: Router (ARMED) vs Unconditioned (Router OFF) para B y C.
2. Entrada causal en Open_{t+1} con fricción (5 bps comisión taker + 5 bps slippage por lado = 20 bps round trip).
3. Sensibilidad adversa de costes (10 bps fee + 10 bps slippage = 40 bps round trip).
4. Política conservadora Stop-First ante ambigüedad OHLC.
5. Remuestreo Bootstrap IID (B=1,000 iteraciones) sobre trades cerrados para CI al 95%.
6. Desglose temporal (2024, 2025, 2026 YTD) y por activo (BTC, ETH, SOL).
7. Evaluación formal según los 5 Gates de decisión.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

# Asegurar encoding UTF-8 en stdout de Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from chimuelo_prime.backtesting.alpha_research_backtester import (
    AlphaResearchBacktester,
    ResearchTradeOutcome,
    run_bootstrap_analysis,
)
from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.regime_engine.config import RegimeEngineConfig
from chimuelo_prime.regime_engine.feature_engine import (
    calculate_adx,
    calculate_causal_rolling_percentile,
    calculate_efficiency_ratio,
    calculate_rolling_realized_volatility,
    calculate_slope_50,
    calculate_trend_spread,
)
from chimuelo_prime.regime_engine.models import (
    MarketStateVector,
    TradeCandidate,
)
from chimuelo_prime.regime_engine.regime_engine import QuantitativeRegimeEngine
from chimuelo_prime.regime_engine.router import StrategyRouter
from chimuelo_prime.regime_engine.router_config import RouterConfig
from chimuelo_prime.strategies.alpha_b_pullback import DeepPullbackAlphaMotor
from chimuelo_prime.strategies.alpha_c_sweep import LiquiditySweepAlphaMotor
from chimuelo_prime.strategies.indicators import calculate_atr, calculate_ema


def load_candles_from_cache(path: str) -> list[HistoricalCandle]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    candles = []
    for item in raw:
        t = datetime.fromtimestamp(item[0] / 1000, tz=UTC)
        candles.append(
            HistoricalCandle(
                timestamp=t,
                open=Decimal(str(item[1])),
                high=Decimal(str(item[2])),
                low=Decimal(str(item[3])),
                close=Decimal(str(item[4])),
                volume=Decimal(str(item[5])),
            )
        )
    candles.sort(key=lambda c: c.timestamp)
    return candles


def calculate_max_drawdown_pct(trades: list[ResearchTradeOutcome]) -> float:
    """Calcula el Maximum Drawdown sobre la curva de retornos porcentuales acumulados."""
    if not trades:
        return 0.0
    equity = 100.0
    peak = 100.0
    max_dd = 0.0
    for t in trades:
        ret = float(t.net_return_pct)
        equity *= 1.0 + (ret / 100.0)
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100.0
        if dd > max_dd:
            max_dd = dd
    return round(max_dd, 2)


def evaluate_run_statistics(
    trades: list[ResearchTradeOutcome],
    bootstrap_iterations: int = 1000,
    seed: int = 42,
) -> dict[str, Any]:
    """Genera las métricas cuantitativas completas para un conjunto de trades simulados."""
    n = len(trades)
    if n == 0:
        return {
            "n_trades": 0,
            "gross_return_pct": 0.0,
            "total_friction_pct": 0.0,
            "net_return_pct": 0.0,
            "mean_net_r": 0.0,
            "win_rate_pct": 0.0,
            "profit_factor": 0.0,
            "max_drawdown_pct": 0.0,
            "mean_duration_hours": 0.0,
            "ci_95_r_lower": 0.0,
            "ci_95_r_upper": 0.0,
            "ci_95_win_lower": 0.0,
            "ci_95_win_upper": 0.0,
            "autocorrelation_lag1": 0.0,
            "by_year": {},
        }

    gross_pct = sum(float(t.gross_return_pct) for t in trades)
    friction_pct = sum(float(t.total_friction_pct) for t in trades)
    net_pct = sum(float(t.net_return_pct) for t in trades)
    mean_dur = sum(t.duration_bars for t in trades) / n
    max_dd = calculate_max_drawdown_pct(trades)

    boot = run_bootstrap_analysis(trades, iterations=bootstrap_iterations, seed=seed)

    # Desglose por año
    trades_by_year: dict[str, list[ResearchTradeOutcome]] = defaultdict(list)
    for t in trades:
        yr = str(t.entry_time.year)
        trades_by_year[yr].append(t)

    by_year_stats = {}
    for yr, y_trades in sorted(trades_by_year.items()):
        y_n = len(y_trades)
        y_net = sum(float(x.net_return_pct) for x in y_trades)
        y_r = sum(float(x.net_r_multiple) for x in y_trades) / y_n
        y_win = (sum(1 for x in y_trades if float(x.net_r_multiple) > 0) / y_n) * 100.0
        by_year_stats[yr] = {
            "n_trades": y_n,
            "net_return_pct": round(y_net, 2),
            "mean_r": round(y_r, 3),
            "win_rate_pct": round(y_win, 1),
        }

    return {
        "n_trades": n,
        "gross_return_pct": round(gross_pct, 2),
        "total_friction_pct": round(friction_pct, 2),
        "net_return_pct": round(net_pct, 2),
        "mean_net_r": boot["mean_r"],
        "win_rate_pct": boot["win_rate_pct"],
        "profit_factor": boot["profit_factor"],
        "max_drawdown_pct": max_dd,
        "mean_duration_hours": round(mean_dur, 1),
        "ci_95_r_lower": boot["ci_95_lower"],
        "ci_95_r_upper": boot["ci_95_upper"],
        "ci_95_win_lower": boot["win_rate_ci_lower"],
        "ci_95_win_upper": boot["win_rate_ci_upper"],
        "autocorrelation_lag1": boot["autocorrelation_lag1"],
        "by_year": by_year_stats,
    }


def run_alpha_motors_audit() -> dict[str, Any]:
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    warmup_required = 770

    regime_cfg = RegimeEngineConfig()
    router_cfg = RouterConfig()

    regime_engine = QuantitativeRegimeEngine(config=regime_cfg)
    motor_b = DeepPullbackAlphaMotor(risk_reward_ratio=Decimal("2.0"))
    motor_c = LiquiditySweepAlphaMotor(lookback_bars=24)

    # Simuladores: Baseline (20 bps round trip) y Adverso (40 bps round trip)
    backtester_baseline = AlphaResearchBacktester(
        fee_rate_per_side=Decimal("0.0005"),
        slippage_per_side=Decimal("0.0005"),
        ohlc_ambiguity_policy="stop_first",
    )
    backtester_adverse = AlphaResearchBacktester(
        fee_rate_per_side=Decimal("0.0010"),
        slippage_per_side=Decimal("0.0010"),
        ohlc_ambiguity_policy="stop_first",
    )

    # Almacén de candidatos y velas por símbolo
    symbol_data: dict[str, Any] = {}

    print("=" * 80)
    print("CHIMUELO PRIME — FASE 4: AUDITORÍA DE ALPHA MOTORS B & C")
    print("Evaluando causalmente: Triggers en Open_{t+1}, SL/TP, Fricción y Bootstrap CI")
    print("=" * 80)

    for sym in symbols:
        cache_path = f"data/cache_extended/{sym}_1h.json"
        print(f"\n[+] Procesando {sym}...")
        candles_1h = load_candles_from_cache(cache_path)
        n_bars = len(candles_1h)

        closes = [c.close for c in candles_1h]
        highs = [c.high for c in candles_1h]
        lows = [c.low for c in candles_1h]
        volumes = [c.volume for c in candles_1h]

        ema20 = calculate_ema(closes, 20)
        ema50 = calculate_ema(closes, 50)
        atr20 = calculate_atr(highs, lows, closes, 20)
        adx = calculate_adx(highs, lows, closes, 14)
        rv = [calculate_rolling_realized_volatility(closes, i, 20) for i in range(n_bars)]
        tr = [abs(highs[i] - lows[i]) for i in range(n_bars)]

        router = StrategyRouter(config=router_cfg)
        prev_state: MarketStateVector | None = None

        candidates_b_router: list[tuple[int, TradeCandidate]] = []
        candidates_b_uncond: list[tuple[int, TradeCandidate]] = []

        candidates_c_router: list[tuple[int, TradeCandidate]] = []
        candidates_c_uncond: list[tuple[int, TradeCandidate]] = []

        for idx in range(warmup_required, n_bars - 1):
            s50 = calculate_slope_50(ema50, atr20, idx)
            ts = calculate_trend_spread(ema20, ema50, atr20, idx)
            adx_val = adx[idx] or Decimal("15.0")
            er_val = calculate_efficiency_ratio(closes, idx, 20)
            atr_p = calculate_causal_rolling_percentile(atr20, idx, 500)
            rv_p = calculate_causal_rolling_percentile(rv, idx, 500)
            vol_p = calculate_causal_rolling_percentile(volumes, idx, 200)
            tr_p = calculate_causal_rolling_percentile(tr, idx, 200)

            t_reg = regime_engine.classify_trend(s50, ts, adx_val)
            v_reg = regime_engine.classify_volatility(atr_p, rv_p)
            s_reg = regime_engine.classify_structure(er_val)
            p_reg = regime_engine.classify_participation(vol_p, tr_p)
            d_reg = regime_engine.classify_derivatives(None, None, vol_p)

            trans = regime_engine.detect_transition(
                current_trend=t_reg,
                current_volatility=v_reg,
                current_structure=s_reg,
                current_participation=p_reg,
                current_derivatives=d_reg,
                previous_state=prev_state,
            )

            c_now = candles_1h[idx]
            curr_state = MarketStateVector(
                timestamp=c_now.timestamp,
                symbol=sym,
                timeframe="1h",
                trend=t_reg,
                volatility=v_reg,
                structure=s_reg,
                participation=p_reg,
                derivatives=d_reg,
                slope_50=s50,
                trend_spread=ts,
                adx_14=adx_val,
                efficiency_ratio=er_val,
                atr_percentile=atr_p,
                rv_percentile=rv_p,
                volume_percentile=vol_p,
                tr_percentile=tr_p,
                z_funding=Decimal("0.0"),
                delta_oi_4h=Decimal("0.0"),
                transition=trans,
                context_4h_closed_timestamp=None,
            )

            router_res = router.evaluate(symbol=sym, market_state=curr_state)

            # 1. Evaluar Motor B: Con Router vs Sin Router (Unconditioned)
            cand_b_r = motor_b.evaluate_candidate(
                symbol=sym,
                candles=candles_1h,
                current_idx=idx,
                market_state=curr_state,
                ema20=ema20,
                ema50=ema50,
                atr20=atr20,
                router_result=router_res,
                unconditioned=False,
            )
            if cand_b_r:
                candidates_b_router.append((idx, cand_b_r))

            cand_b_u = motor_b.evaluate_candidate(
                symbol=sym,
                candles=candles_1h,
                current_idx=idx,
                market_state=curr_state,
                ema20=ema20,
                ema50=ema50,
                atr20=atr20,
                router_result=router_res,
                unconditioned=True,
            )
            if cand_b_u:
                candidates_b_uncond.append((idx, cand_b_u))

            # 2. Evaluar Motor C: Con Router vs Sin Router (Unconditioned)
            cand_c_r = motor_c.evaluate_candidate(
                symbol=sym,
                candles=candles_1h,
                current_idx=idx,
                market_state=curr_state,
                ema20=ema20,
                atr20=atr20,
                router_result=router_res,
                unconditioned=False,
            )
            if cand_c_r:
                candidates_c_router.append((idx, cand_c_r))

            cand_c_u = motor_c.evaluate_candidate(
                symbol=sym,
                candles=candles_1h,
                current_idx=idx,
                market_state=curr_state,
                ema20=ema20,
                atr20=atr20,
                router_result=router_res,
                unconditioned=True,
            )
            if cand_c_u:
                candidates_c_uncond.append((idx, cand_c_u))

            prev_state = curr_state

        symbol_data[sym] = {
            "candles": candles_1h,
            "candidates_b_router": candidates_b_router,
            "candidates_b_uncond": candidates_b_uncond,
            "candidates_c_router": candidates_c_router,
            "candidates_c_uncond": candidates_c_uncond,
        }
        print(f"    Candidatos B: {len(candidates_b_router)} (Router) vs {len(candidates_b_uncond)} (Uncond)")
        print(f"    Candidatos C: {len(candidates_c_router)} (Router) vs {len(candidates_c_uncond)} (Uncond)")

    # ==========================================================================
    # SIMULACIÓN Y ANÁLISIS ESTADÍSTICO COMPLETO
    # ==========================================================================
    audit_results: dict[str, Any] = {
        "metadata": {
            "version": "AlphaMotors_v0.1.0-research",
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "friction_baseline_roundtrip_bps": 20,
            "friction_adverse_roundtrip_bps": 40,
            "ohlc_policy": "conservative_stop_first",
            "bootstrap_iterations": 1000,
        },
        "by_symbol": {},
        "portfolio": {},
    }

    portfolio_trades_b_router: list[ResearchTradeOutcome] = []
    portfolio_trades_b_uncond: list[ResearchTradeOutcome] = []
    portfolio_trades_c_router: list[ResearchTradeOutcome] = []
    portfolio_trades_c_uncond: list[ResearchTradeOutcome] = []
    portfolio_trades_b_router_adverse: list[ResearchTradeOutcome] = []
    portfolio_trades_c_router_adverse: list[ResearchTradeOutcome] = []

    for sym in symbols:
        cands = symbol_data[sym]
        cdls = cands["candles"]

        # 1. Motor B
        tr_b_r = backtester_baseline.simulate_trades(cands["candidates_b_router"], cdls)
        tr_b_u = backtester_baseline.simulate_trades(cands["candidates_b_uncond"], cdls)
        tr_b_r_adv = backtester_adverse.simulate_trades(cands["candidates_b_router"], cdls)

        # 2. Motor C
        tr_c_r = backtester_baseline.simulate_trades(cands["candidates_c_router"], cdls)
        tr_c_u = backtester_baseline.simulate_trades(cands["candidates_c_uncond"], cdls)
        tr_c_r_adv = backtester_adverse.simulate_trades(cands["candidates_c_router"], cdls)

        portfolio_trades_b_router.extend(tr_b_r)
        portfolio_trades_b_uncond.extend(tr_b_u)
        portfolio_trades_c_router.extend(tr_c_r)
        portfolio_trades_c_uncond.extend(tr_c_u)
        portfolio_trades_b_router_adverse.extend(tr_b_r_adv)
        portfolio_trades_c_router_adverse.extend(tr_c_r_adv)

        stat_b_r = evaluate_run_statistics(tr_b_r)
        stat_b_u = evaluate_run_statistics(tr_b_u)
        stat_b_r_adv = evaluate_run_statistics(tr_b_r_adv)

        stat_c_r = evaluate_run_statistics(tr_c_r)
        stat_c_u = evaluate_run_statistics(tr_c_u)
        stat_c_r_adv = evaluate_run_statistics(tr_c_r_adv)

        audit_results["by_symbol"][sym] = {
            "strategy_b": {
                "router_conditioned": stat_b_r,
                "unconditioned": stat_b_u,
                "delta_expectancy_r": round(stat_b_r["mean_net_r"] - stat_b_u["mean_net_r"], 3),
                "router_adverse_friction": stat_b_r_adv,
            },
            "strategy_c": {
                "router_conditioned": stat_c_r,
                "unconditioned": stat_c_u,
                "delta_expectancy_r": round(stat_c_r["mean_net_r"] - stat_c_u["mean_net_r"], 3),
                "router_adverse_friction": stat_c_r_adv,
            },
        }

    # Estadísticas Agregadas de Cartera
    stat_port_b_r = evaluate_run_statistics(portfolio_trades_b_router)
    stat_port_b_u = evaluate_run_statistics(portfolio_trades_b_uncond)
    stat_port_b_adv = evaluate_run_statistics(portfolio_trades_b_router_adverse)

    stat_port_c_r = evaluate_run_statistics(portfolio_trades_c_router)
    stat_port_c_u = evaluate_run_statistics(portfolio_trades_c_uncond)
    stat_port_c_adv = evaluate_run_statistics(portfolio_trades_c_router_adverse)

    # Simulación Concurrente Cartera B + C (con resolución de colisiones)
    all_combined_candidates: list[tuple[str, int, TradeCandidate]] = []
    for sym in symbols:
        for idx, cand in symbol_data[sym]["candidates_b_router"]:
            all_combined_candidates.append((sym, idx, cand))
        for idx, cand in symbol_data[sym]["candidates_c_router"]:
            all_combined_candidates.append((sym, idx, cand))

    all_combined_candidates.sort(key=lambda x: x[1])  # Ordenar cronológicamente por idx

    # Resolver colisiones en misma barra y símbolo
    filtered_combined_candidates: dict[str, list[tuple[int, TradeCandidate]]] = {s: [] for s in symbols}
    collision_counts = 0
    seen_bar_symbol: dict[tuple[str, int], TradeCandidate] = {}

    for sym, idx, cand in all_combined_candidates:
        key = (sym, idx)
        if key in seen_bar_symbol:
            collision_counts += 1
            prev_cand = seen_bar_symbol[key]
            # Si van en direcciones opuestas -> conflicto: abstención conservadora
            if prev_cand.direction != cand.direction:
                # Cancelar ambas
                filtered_combined_candidates[sym] = [
                    item for item in filtered_combined_candidates[sym] if item[0] != idx
                ]
            else:
                # Misma dirección: conservar la de mayor confidence
                if cand.confidence_score > prev_cand.confidence_score:
                    filtered_combined_candidates[sym] = [
                        item for item in filtered_combined_candidates[sym] if item[0] != idx
                    ]
                    filtered_combined_candidates[sym].append((idx, cand))
                    seen_bar_symbol[key] = cand
        else:
            seen_bar_symbol[key] = cand
            filtered_combined_candidates[sym].append((idx, cand))

    portfolio_combined_trades: list[ResearchTradeOutcome] = []
    for sym in symbols:
        cdls = symbol_data[sym]["candles"]
        tr_comb = backtester_baseline.simulate_trades(filtered_combined_candidates[sym], cdls)
        portfolio_combined_trades.extend(tr_comb)

    stat_combined_bc = evaluate_run_statistics(portfolio_combined_trades)

    audit_results["portfolio"] = {
        "strategy_b": {
            "router_conditioned": stat_port_b_r,
            "unconditioned": stat_port_b_u,
            "delta_expectancy_r": round(stat_port_b_r["mean_net_r"] - stat_port_b_u["mean_net_r"], 3),
            "router_adverse_friction": stat_port_b_adv,
        },
        "strategy_c": {
            "router_conditioned": stat_port_c_r,
            "unconditioned": stat_port_c_u,
            "delta_expectancy_r": round(stat_port_c_r["mean_net_r"] - stat_port_c_u["mean_net_r"], 3),
            "router_adverse_friction": stat_port_c_adv,
        },
        "combined_b_and_c": {
            "collisions_detected": collision_counts,
            "statistics": stat_combined_bc,
        },
    }

    # ==========================================================================
    # EVALUACIÓN SEGÚN LOS 5 GATES DE DECISIÓN
    # ==========================================================================
    def classify_gate_status(stat_r: dict[str, Any], stat_u: dict[str, Any], stat_adv: dict[str, Any]) -> str:
        net_positive = stat_r["mean_net_r"] > 0
        ci_lower_positive = stat_r["ci_95_r_lower"] > 0
        router_superior = stat_r["mean_net_r"] > stat_u["mean_net_r"]
        adverse_positive = stat_adv["mean_net_r"] > 0

        if net_positive and ci_lower_positive and router_superior and adverse_positive:
            return "[ALPHA VALIDATED]"
        elif net_positive and router_superior:
            return "[PROMISING BUT INCONCLUSIVE] (CI cruza 0 o débil ante costes adversos)"
        elif router_superior:
            return "[ROUTER EFFECT CONFIRMED / ALPHA FAILED] (Router mejora, pero Net R <= 0)"
        else:
            return "[HYPOTHESIS REJECTED] (Router no mejora o Net R negativo)"

    gate_b = classify_gate_status(stat_port_b_r, stat_port_b_u, stat_port_b_adv)
    gate_c = classify_gate_status(stat_port_c_r, stat_port_c_u, stat_port_c_adv)

    audit_results["portfolio"]["verdict_gates"] = {
        "strategy_b": gate_b,
        "strategy_c": gate_c,
    }

    # Guardar reporte JSON
    out_file = Path("data/reports/alpha_motors_empirical_v0.1.0.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(audit_results, f, indent=2)

    # ==========================================================================
    # PRESENTACIÓN EJECUTIVA POR PANTALLA
    # ==========================================================================
    print("\n" + "=" * 80)
    print("REPORTE EJECUTIVO DE VALIDACIÓN: CARTERA AGREGADA (50,178 BARRAS)")
    print("=" * 80)

    for strat_name, strat_key in [("STRATEGY B (Deep Pullback)", "strategy_b"), ("STRATEGY C (Liquidity Sweep)", "strategy_c")]:
        d = audit_results["portfolio"][strat_key]
        r = d["router_conditioned"]
        u = d["unconditioned"]
        adv = d["router_adverse_friction"]
        delta_r = d["delta_expectancy_r"]

        print(f"\n--- {strat_name} ---")
        print(f"  Veredicto Formal: {audit_results['portfolio']['verdict_gates'][strat_key]}")
        print(f"  ROUTER ARMED:    N = {r['n_trades']:>4} trades | Net PnL = {r['net_return_pct']:>+7.2f}% | E[R] = {r['mean_net_r']:>+6.3f}R | 95% CI = [{r['ci_95_r_lower']:>+6.3f}R, {r['ci_95_r_upper']:>+6.3f}R] | Win = {r['win_rate_pct']:>4.1f}% | PF = {r['profit_factor']:>4.2f} | MaxDD = {r['max_drawdown_pct']:>5.2f}%")
        print(f"  UNCONDITIONED:   N = {u['n_trades']:>4} trades | Net PnL = {u['net_return_pct']:>+7.2f}% | E[R] = {u['mean_net_r']:>+6.3f}R | 95% CI = [{u['ci_95_r_lower']:>+6.3f}R, {u['ci_95_r_upper']:>+6.3f}R] | Win = {u['win_rate_pct']:>4.1f}% | PF = {u['profit_factor']:>4.2f} | MaxDD = {u['max_drawdown_pct']:>5.2f}%")
        print(f"  DELTA (R - U):   Trades = {r['n_trades'] - u['n_trades']:>+4} | Delta Net PnL = {r['net_return_pct'] - u['net_return_pct']:>+7.2f}% | Delta E[R] = {delta_r:>+6.3f}R")
        print(f"  COSTE ADVERSO:   Net PnL = {adv['net_return_pct']:>+7.2f}% | E[R] = {adv['mean_net_r']:>+6.3f}R | 95% CI = [{adv['ci_95_r_lower']:>+6.3f}R, {adv['ci_95_r_upper']:>+6.3f}R] (40 bps round trip)")

        print("  Desglose Temporal (Router):")
        for yr, y_stat in r["by_year"].items():
            print(f"    {yr}: N={y_stat['n_trades']:>3} | Net PnL = {y_stat['net_return_pct']:>+6.2f}% | E[R] = {y_stat['mean_r']:>+6.3f}R | Win = {y_stat['win_rate_pct']:>4.1f}%")

    print("\n--- CARTERA CONCURRENTE COMBINADA (B + C) ---")
    comb = audit_results["portfolio"]["combined_b_and_c"]["statistics"]
    print(f"  Colisiones detectadas y resueltas: {audit_results['portfolio']['combined_b_and_c']['collisions_detected']}")
    print(f"  Total Trades: {comb['n_trades']} | Net PnL = {comb['net_return_pct']:>+7.2f}% | E[R] = {comb['mean_net_r']:>+6.3f}R | 95% CI = [{comb['ci_95_r_lower']:>+6.3f}R, {comb['ci_95_r_upper']:>+6.3f}R] | Win = {comb['win_rate_pct']:.1f}% | PF = {comb['profit_factor']:.2f} | MaxDD = {comb['max_drawdown_pct']:.2f}%")
    print(f"  Autocorrelación de retornos lag-1: {comb['autocorrelation_lag1']}")

    print(f"\n[OK] Auditoría empírica de Alpha Motors guardada en: {out_file}")
    return audit_results


if __name__ == "__main__":
    run_alpha_motors_audit()
