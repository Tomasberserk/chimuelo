"""Script Maestro de Diagnóstico Forense y Oracle Envelope (Fase 4.1).

Ejecuta el análisis causal sobre las 50,178 barras históricas de BTCUSDT, ETHUSDT y SOLUSDT:
- MFE / MAE multitemporal (1h, 4h, 8h, 24h) en % y múltiplos R.
- Oracle Envelope diagnóstico (desacoplamiento de trigger vs regla de salida).
- Latencia de entrada t -> t+1 y ratio de movimiento previo.
- Microestructura de barrido (profundidad ATR, mecha de rechazo, re-tests a 4h/8h/24h).
- Contraste estadístico formal de Gate 0 (disjunto e inclusivo) con Moving Block Bootstrap (L=24).
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

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
    AlphaMotorId,
    MarketStateVector,
    RouterStrategyState,
    TradeDirection,
    TrendRegime,
)
from chimuelo_prime.regime_engine.regime_engine import QuantitativeRegimeEngine
from chimuelo_prime.regime_engine.router import StrategyRouter
from chimuelo_prime.regime_engine.router_config import RouterConfig
from chimuelo_prime.research.alpha_forensics import (
    AlphaForensicsAnalyzer,
    ForensicSignalRecord,
    aggregate_forensic_metrics,
    calculate_moving_block_bootstrap_diff,
)
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


def run_forensics_audit() -> dict[str, Any]:
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    warmup_required = 770
    lookback_c = 24

    regime_cfg = RegimeEngineConfig()
    router_cfg = RouterConfig()

    regime_engine = QuantitativeRegimeEngine(config=regime_cfg)
    motor_b = DeepPullbackAlphaMotor(risk_reward_ratio=Decimal("2.0"))
    motor_c = LiquiditySweepAlphaMotor(lookback_bars=lookback_c)
    analyzer = AlphaForensicsAnalyzer(
        slippage=Decimal("0.0005"),  # 5 bps
        fee_rate=Decimal("0.0005"),  # 5 bps
    )

    print("=" * 80)
    print("CHIMUELO PRIME — FASE 4.1: ALPHA FORENSICS & ORACLE ENVELOPE")
    print("Diagnóstico causal bar-by-bar sobre 50,178 barras horarias continuas")
    print("=" * 80)

    all_records_b_router: list[ForensicSignalRecord] = []
    all_records_b_uncond: list[ForensicSignalRecord] = []
    all_records_c_router: list[ForensicSignalRecord] = []
    all_records_c_uncond: list[ForensicSignalRecord] = []

    # Series para Gate 0 Disjunto (Retornos forward a 24h en %)
    gate0_b_trig_returns: list[float] = []
    gate0_b_non_trig_returns: list[float] = []
    gate0_c_trig_returns: list[float] = []
    gate0_c_non_trig_returns: list[float] = []

    by_symbol_results: dict[str, Any] = {}

    for sym in symbols:
        cache_path = f"data/cache_extended/{sym}_1h.json"
        print(f"\n[+] Extrayendo métricas forenses para {sym}...")
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

        sym_records_b_router: list[ForensicSignalRecord] = []
        sym_records_b_uncond: list[ForensicSignalRecord] = []
        sym_records_c_router: list[ForensicSignalRecord] = []
        sym_records_c_uncond: list[ForensicSignalRecord] = []

        sym_gate0_b_trig: list[float] = []
        sym_gate0_b_non: list[float] = []
        sym_gate0_c_trig: list[float] = []
        sym_gate0_c_non: list[float] = []

        for idx in range(warmup_required, n_bars - 25):
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
            prev_state = curr_state

            # Evaluación causal de señales
            cand_b_router = motor_b.evaluate_candidate(
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
            cand_b_uncond = motor_b.evaluate_candidate(
                symbol=sym,
                candles=candles_1h,
                current_idx=idx,
                market_state=curr_state,
                ema20=ema20,
                ema50=ema50,
                atr20=atr20,
                unconditioned=True,
            )

            cand_c_router = motor_c.evaluate_candidate(
                symbol=sym,
                candles=candles_1h,
                current_idx=idx,
                market_state=curr_state,
                ema20=ema20,
                atr20=atr20,
                router_result=router_res,
                unconditioned=False,
            )
            cand_c_uncond = motor_c.evaluate_candidate(
                symbol=sym,
                candles=candles_1h,
                current_idx=idx,
                market_state=curr_state,
                ema20=ema20,
                atr20=atr20,
                unconditioned=True,
            )

            # Forensics B
            if cand_b_router is not None:
                rec_b = analyzer.evaluate_candidate_forensics(cand_b_router, idx, candles_1h, atr20)
                if rec_b is not None:
                    sym_records_b_router.append(rec_b)
            if cand_b_uncond is not None:
                rec_bu = analyzer.evaluate_candidate_forensics(cand_b_uncond, idx, candles_1h, atr20)
                if rec_bu is not None:
                    sym_records_b_uncond.append(rec_bu)

            # Forensics C
            if cand_c_router is not None:
                rec_c = analyzer.evaluate_candidate_forensics(cand_c_router, idx, candles_1h, atr20, lookback_c)
                if rec_c is not None:
                    sym_records_c_router.append(rec_c)
            if cand_c_uncond is not None:
                rec_cu = analyzer.evaluate_candidate_forensics(cand_c_uncond, idx, candles_1h, atr20, lookback_c)
                if rec_cu is not None:
                    sym_records_c_uncond.append(rec_cu)

            # Gate 0 Forward Returns a 24h
            next_open = candles_1h[idx + 1].open
            fwd_close = candles_1h[idx + 24].close

            # B Gate 0:
            b_log = router_res.strategy_evaluations.get(AlphaMotorId.ALPHA_B)
            is_b_armed = (b_log is not None) and (b_log.state_after == RouterStrategyState.ARMED)
            if is_b_armed:
                is_bull = curr_state.trend in (TrendRegime.BULL, TrendRegime.STRONG_BULL)
                is_bear = curr_state.trend in (TrendRegime.BEAR, TrendRegime.STRONG_BEAR)
                if is_bull or is_bear:
                    direction_sign = 1.0 if is_bull else -1.0
                    raw_ret = float(((fwd_close - next_open) / next_open) * Decimal("100.0"))
                    ret_24h_pct = direction_sign * raw_ret
                    if cand_b_router is not None:
                        sym_gate0_b_trig.append(ret_24h_pct)
                    else:
                        sym_gate0_b_non.append(ret_24h_pct)

            # C Gate 0:
            c_log = router_res.strategy_evaluations.get(AlphaMotorId.ALPHA_C)
            is_c_armed = (c_log is not None) and (c_log.state_after == RouterStrategyState.ARMED)
            if is_c_armed and idx >= lookback_c:
                pw = candles_1h[idx - lookback_c : idx]
                hp = max(c.high for c in pw)
                lp = min(c.low for c in pw)
                midpoint = (hp + lp) / Decimal("2.0")
                raw_ret = float(((fwd_close - next_open) / next_open) * Decimal("100.0"))

                if cand_c_router is not None:
                    c_dir_sign = 1.0 if cand_c_router.direction == TradeDirection.LONG else -1.0
                    sym_gate0_c_trig.append(c_dir_sign * raw_ret)
                else:
                    c_dir_sign = 1.0 if c_now.close < midpoint else -1.0
                    sym_gate0_c_non.append(c_dir_sign * raw_ret)

        by_symbol_results[sym] = {
            "strategy_b": {
                "router": aggregate_forensic_metrics(sym_records_b_router),
                "unconditioned": aggregate_forensic_metrics(sym_records_b_uncond),
                "gate_0_contrast": calculate_moving_block_bootstrap_diff(
                    series_trigger=sym_gate0_b_trig,
                    series_non_trigger=sym_gate0_b_non,
                    block_length=24,
                    iterations=1000,
                ),
            },
            "strategy_c": {
                "router": aggregate_forensic_metrics(sym_records_c_router),
                "unconditioned": aggregate_forensic_metrics(sym_records_c_uncond),
                "gate_0_contrast": calculate_moving_block_bootstrap_diff(
                    series_trigger=sym_gate0_c_trig,
                    series_non_trigger=sym_gate0_c_non,
                    block_length=24,
                    iterations=1000,
                ),
            },
        }

        all_records_b_router.extend(sym_records_b_router)
        all_records_b_uncond.extend(sym_records_b_uncond)
        all_records_c_router.extend(sym_records_c_router)
        all_records_c_uncond.extend(sym_records_c_uncond)

        gate0_b_trig_returns.extend(sym_gate0_b_trig)
        gate0_b_non_trig_returns.extend(sym_gate0_b_non)
        gate0_c_trig_returns.extend(sym_gate0_c_trig)
        gate0_c_non_trig_returns.extend(sym_gate0_c_non)

        print(f"    B Señales: {len(sym_records_b_router)} (Router) | C Señales: {len(sym_records_c_router)} (Router)")

    global_b_router = aggregate_forensic_metrics(all_records_b_router)
    global_b_uncond = aggregate_forensic_metrics(all_records_b_uncond)
    global_c_router = aggregate_forensic_metrics(all_records_c_router)
    global_c_uncond = aggregate_forensic_metrics(all_records_c_uncond)

    gate0_b_global = calculate_moving_block_bootstrap_diff(
        series_trigger=gate0_b_trig_returns,
        series_non_trigger=gate0_b_non_trig_returns,
        block_length=24,
        iterations=1000,
    )
    gate0_c_global = calculate_moving_block_bootstrap_diff(
        series_trigger=gate0_c_trig_returns,
        series_non_trigger=gate0_c_non_trig_returns,
        block_length=24,
        iterations=1000,
    )

    armed_b_all = gate0_b_trig_returns + gate0_b_non_trig_returns
    armed_c_all = gate0_c_trig_returns + gate0_c_non_trig_returns

    mean_b_armed_all = sum(armed_b_all) / len(armed_b_all) if armed_b_all else 0.0
    mean_c_armed_all = sum(armed_c_all) / len(armed_c_all) if armed_c_all else 0.0

    delta_inclusive_b = (sum(gate0_b_trig_returns) / len(gate0_b_trig_returns)) - mean_b_armed_all if gate0_b_trig_returns else 0.0
    delta_inclusive_c = (sum(gate0_c_trig_returns) / len(gate0_c_trig_returns)) - mean_c_armed_all if gate0_c_trig_returns else 0.0

    verdict_gate0_b = (
        "[GATE 0 PASSED] (Trigger añade alpha sobre no-trigger en ARMED)"
        if (gate0_b_global["delta_mean"] > 0 and gate0_b_global["ci_95_lower"] > 0 and gate0_b_global["p_value_permutation"] < 0.05)
        else "[GATE 0 FAILED] (H0 NO rechazada: el trigger B no añade ventaja predictiva sobre el régimen)"
    )

    verdict_gate0_c = (
        "[GATE 0 PASSED] (Trigger añade alpha sobre no-trigger en ARMED)"
        if (gate0_c_global["delta_mean"] > 0 and gate0_c_global["ci_95_lower"] > 0 and gate0_c_global["p_value_permutation"] < 0.05)
        else "[GATE 0 FAILED] (H0 NO rechazada: el trigger C no añade ventaja predictiva sobre el régimen)"
    )

    final_report: dict[str, Any] = {
        "metadata": {
            "version": "AlphaForensics_v0.1.0",
            "timestamp": datetime.now(UTC).isoformat(),
            "total_bars_evaluated": 50178,
            "block_length_mbb": 24,
            "bootstrap_iterations": 1000,
            "slippage_bps": 5,
            "fee_rate_bps": 5,
        },
        "portfolio_aggregate": {
            "strategy_b": {
                "router_conditioned": global_b_router,
                "unconditioned": global_b_uncond,
                "gate_0_disjoint_test": {
                    "n_trigger": len(gate0_b_trig_returns),
                    "n_non_trigger": len(gate0_b_non_trig_returns),
                    "mean_return_trigger_pct": gate0_b_global["mean_trigger"],
                    "mean_return_non_trigger_pct": gate0_b_global["mean_non_trigger"],
                    "delta_disjoint_pct": gate0_b_global["delta_mean"],
                    "ci_95_mbb_lower": gate0_b_global["ci_95_lower"],
                    "ci_95_mbb_upper": gate0_b_global["ci_95_upper"],
                    "p_value_permutation": gate0_b_global["p_value_permutation"],
                    "mean_return_armed_total_pct": round(mean_b_armed_all, 4),
                    "delta_inclusive_pct": round(delta_inclusive_b, 4),
                    "verdict": verdict_gate0_b,
                },
            },
            "strategy_c": {
                "router_conditioned": global_c_router,
                "unconditioned": global_c_uncond,
                "gate_0_disjoint_test": {
                    "n_trigger": len(gate0_c_trig_returns),
                    "n_non_trigger": len(gate0_c_non_trig_returns),
                    "mean_return_trigger_pct": gate0_c_global["mean_trigger"],
                    "mean_return_non_trigger_pct": gate0_c_global["mean_non_trigger"],
                    "delta_disjoint_pct": gate0_c_global["delta_mean"],
                    "ci_95_mbb_lower": gate0_c_global["ci_95_lower"],
                    "ci_95_mbb_upper": gate0_c_global["ci_95_upper"],
                    "p_value_permutation": gate0_c_global["p_value_permutation"],
                    "mean_return_armed_total_pct": round(mean_c_armed_all, 4),
                    "delta_inclusive_pct": round(delta_inclusive_c, 4),
                    "verdict": verdict_gate0_c,
                },
            },
        },
        "by_symbol": by_symbol_results,
    }

    out_dir = Path("data/reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    report_file = out_dir / "alpha_forensics_v0.1.0.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(final_report, f, indent=2)

    print("\n" + "=" * 80)
    print("REPORTE EJECUTIVO FORENSE: CARTERA AGREGADA (50,178 BARRAS)")
    print("=" * 80)

    print("\n--- ESTRATEGIA B (Deep Pullback) ---")
    b_or = global_b_router["oracle_envelope"]
    b_dh = global_b_router["directional_hit_rates"]
    b_me = global_b_router["mechanical_exit_rates"]
    b_lat = global_b_router["entry_latency"]
    b_g0 = final_report["portfolio_aggregate"]["strategy_b"]["gate_0_disjoint_test"]

    print(f"  Veredicto Gate 0: {b_g0['verdict']}")
    print(f"  Gate 0 Disjunto: N(Trig)={b_g0['n_trigger']} ({b_g0['mean_return_trigger_pct']}%) vs N(Non-Trig)={b_g0['n_non_trigger']} ({b_g0['mean_return_non_trigger_pct']}%)")
    print(f"  Delta Disjunto: {b_g0['delta_disjoint_pct']}% | 95% CI MBB: [{b_g0['ci_95_mbb_lower']}%, {b_g0['ci_95_mbb_upper']}%] | p-value: {b_g0['p_value_permutation']}")
    print(f"  Delta Inclusivo vs Total ARMED: {b_g0['delta_inclusive_pct']}%")
    print(f"  Oracle Envelope: Mean MFE={b_or['mean_mfe_24h_r']}R ({b_or['mean_mfe_24h_pct']}%) | Mean MAE={b_or['mean_mae_24h_r']}R ({b_or['mean_mae_24h_pct']}%) | MFE/MAE={b_or['mfe_mae_ratio']}")
    print(f"  Probabilidades MFE: P(>=1R)={b_or['p_mfe_ge_1r_pct']}% | P(>=1.5R)={b_or['p_mfe_ge_1_5r_pct']}% | P(>=2R)={b_or['p_mfe_ge_2r_pct']}% | P(MAE<=-1R)={b_or['p_mae_le_minus_1r_pct']}%")
    print(f"  Dirección Pura: 1h={b_dh['1h_pct']}% | 4h={b_dh['4h_pct']}% | 8h={b_dh['8h_pct']}% | 24h={b_dh['24h_pct']}%")
    print(f"  Salida Mecánica: TP-before-SL={b_me['tp_before_sl_pct']}% | SL-before-TP={b_me['sl_before_tp_pct']}% | Sin resolver 24h={b_me['neither_hit_24h_pct']}%")
    print(f"  Latencia de Entrada: Gap medio={b_lat['mean_gap_pct']}% | Movimiento pre-entry={b_lat['mean_pre_entry_mfe_pct']}% | Ratio Excursión Agotada={b_lat['mean_excursion_before_entry_ratio']}")

    print("\n--- ESTRATEGIA C (Liquidity Sweep) ---")
    c_or = global_c_router["oracle_envelope"]
    c_dh = global_c_router["directional_hit_rates"]
    c_me = global_c_router["mechanical_exit_rates"]
    c_lat = global_c_router["entry_latency"]
    c_mic = global_c_router.get("microstructure_c", {})
    c_g0 = final_report["portfolio_aggregate"]["strategy_c"]["gate_0_disjoint_test"]

    print(f"  Veredicto Gate 0: {c_g0['verdict']}")
    print(f"  Gate 0 Disjunto: N(Trig)={c_g0['n_trigger']} ({c_g0['mean_return_trigger_pct']}%) vs N(Non-Trig)={c_g0['n_non_trigger']} ({c_g0['mean_return_non_trigger_pct']}%)")
    print(f"  Delta Disjunto: {c_g0['delta_disjoint_pct']}% | 95% CI MBB: [{c_g0['ci_95_mbb_lower']}%, {c_g0['ci_95_mbb_upper']}%] | p-value: {c_g0['p_value_permutation']}")
    print(f"  Delta Inclusivo vs Total ARMED: {c_g0['delta_inclusive_pct']}%")
    print(f"  Oracle Envelope: Mean MFE={c_or['mean_mfe_24h_r']}R ({c_or['mean_mfe_24h_pct']}%) | Mean MAE={c_or['mean_mae_24h_r']}R ({c_or['mean_mae_24h_pct']}%) | MFE/MAE={c_or['mfe_mae_ratio']}")
    print(f"  Probabilidades MFE: P(>=1R)={c_or['p_mfe_ge_1r_pct']}% | P(>=1.5R)={c_or['p_mfe_ge_1_5r_pct']}% | P(>=2R)={c_or['p_mfe_ge_2r_pct']}% | P(MAE<=-1R)={c_or['p_mae_le_minus_1r_pct']}%")
    print(f"  Dirección Pura: 1h={c_dh['1h_pct']}% | 4h={c_dh['4h_pct']}% | 8h={c_dh['8h_pct']}% | 24h={c_dh['24h_pct']}%")
    print(f"  Salida Mecánica: TP-before-SL={c_me['tp_before_sl_pct']}% | SL-before-TP={c_me['sl_before_tp_pct']}% | Sin resolver 24h={c_me['neither_hit_24h_pct']}%")
    print(f"  Latencia de Entrada: Gap medio={c_lat['mean_gap_pct']}% | Movimiento pre-entry={c_lat['mean_pre_entry_mfe_pct']}% | Ratio Excursión Agotada={c_lat['mean_excursion_before_entry_ratio']}")
    if c_mic:
        print(f"  Microestructura: Penetración media={c_mic['mean_sweep_depth_atr']} ATR ({c_mic['mean_sweep_depth_pct']}%) | Mecha rechazo={c_mic['mean_wick_rejection_ratio']} | Volumen Rel={c_mic['mean_relative_volume']}x")
        print(f"  Frecuencia Re-test Nivel: 4h={c_mic['p_retest_prior_level_4h_pct']}% | 8h={c_mic['p_retest_prior_level_8h_pct']}% | 24h={c_mic['p_retest_prior_level_24h_pct']}%")

    print(f"\n[OK] Diagnóstico Forense guardado exitosamente en: {report_file}")
    return final_report


if __name__ == "__main__":
    run_forensics_audit()
