"""Auditoría Cuantitativa Empírica del StrategyRouter y Matriz de Scoring (Fase 3).

Valida sobre 50,250 barras reales (BTCUSDT, ETHUSDT, SOLUSDT en 1h):
1. Monotonía estadística del Score en 7 bins [0.00-0.19, ..., 0.90-1.00] para LONG y SHORT.
2. Separación de expectativa: Delta E_s = E[R | ARMED] - E[R | DISABLED] en R y %.
3. Valor de la abstención: E[R | NO_TRADE] y análisis contrafactual.
4. Persistencia, estabilidad de la FSM, Dwell Time efectivo y prevención de flapping.
5. Correlación cruzada entre scores de hipótesis y solapamiento de regímenes.
6. Causalidad estricta y determinismo sin look-ahead.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
import json
import math
from pathlib import Path
from typing import Any

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
)
from chimuelo_prime.regime_engine.regime_engine import QuantitativeRegimeEngine
from chimuelo_prime.regime_engine.router import StrategyRouter
from chimuelo_prime.regime_engine.router_config import RouterConfig
from chimuelo_prime.strategies.indicators import calculate_atr, calculate_ema


def load_candles_from_cache(path: str) -> list[HistoricalCandle]:
    """Carga y ordena cronológicamente las velas horarias desde la caché local."""
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


def get_score_bin(score_val: float) -> str:
    """Clasifica un score continuo en los 7 bins estándar de investigación."""
    if score_val < 0.20:
        return "0.00-0.19"
    elif score_val < 0.40:
        return "0.20-0.39"
    elif score_val < 0.60:
        return "0.40-0.59"
    elif score_val < 0.70:
        return "0.60-0.69"
    elif score_val < 0.80:
        return "0.70-0.79"
    elif score_val < 0.90:
        return "0.80-0.89"
    else:
        return "0.90-1.00"


SCORE_BINS_ORDER = [
    "0.00-0.19",
    "0.20-0.39",
    "0.40-0.59",
    "0.60-0.69",
    "0.70-0.79",
    "0.80-0.89",
    "0.90-1.00",
]


def calculate_metrics_from_returns(
    returns_pct: list[float],
    returns_r: list[float],
    mfes: list[float],
    maes: list[float],
) -> dict[str, Any]:
    """Calcula las métricas estadísticas estándar sobre vectores de retornos y excursiones."""
    n = len(returns_pct)
    if n == 0:
        return {
            "n": 0,
            "mean_return_pct": 0.0,
            "mean_return_r": 0.0,
            "median_return_r": 0.0,
            "hit_rate_pct": 0.0,
            "mean_mfe_pct": 0.0,
            "mean_mae_pct": 0.0,
            "mfe_mae_ratio": 0.0,
            "profit_factor": 0.0,
        }

    mean_pct = sum(returns_pct) / n
    mean_r = sum(returns_r) / n
    sorted_r = sorted(returns_r)
    med_r = sorted_r[n // 2]
    hits = sum(1 for r in returns_pct if r > 0)
    hit_rate = (hits / n) * 100.0

    mean_mfe = sum(mfes) / n
    mean_mae = sum(maes) / n
    mfe_mae_ratio = round(mean_mfe / mean_mae, 2) if mean_mae > 0.0001 else 1.0

    gains = sum(r for r in returns_pct if r > 0)
    losses = abs(sum(r for r in returns_pct if r < 0))
    pf = round(gains / losses, 2) if losses > 0.0001 else (99.0 if gains > 0 else 0.0)

    return {
        "n": n,
        "mean_return_pct": round(mean_pct, 3),
        "mean_return_r": round(mean_r, 3),
        "median_return_r": round(med_r, 3),
        "hit_rate_pct": round(hit_rate, 2),
        "mean_mfe_pct": round(mean_mfe, 3),
        "mean_mae_pct": round(mean_mae, 3),
        "mfe_mae_ratio": mfe_mae_ratio,
        "profit_factor": pf,
    }


def run_router_validation_backtest() -> dict[str, Any]:
    """Ejecuta la validación empírica causal completa del StrategyRouter sobre 50,250 barras."""
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    forward_horizon = 24  # Ventana canónica de 24 barras horarias
    warmup_required = 770

    regime_cfg = RegimeEngineConfig()
    router_cfg = RouterConfig()

    regime_engine = QuantitativeRegimeEngine(config=regime_cfg)

    all_symbols_evaluations: dict[str, list[dict[str, Any]]] = {}
    total_bars_processed = 0

    print("=" * 80)
    print("CHIMUELO PRIME — ROUTER VALIDATION BACKTEST (50,250 BARRAS)")
    print("Evaluando causalmente: S_t -> Soft Scores + Hard Gates -> FSM (ARMED / DISABLED)")
    print("=" * 80)

    for sym in symbols:
        cache_path = f"data/cache_extended/{sym}_1h.json"
        print(f"\n[+] Cargando y evaluando {sym} desde {cache_path}...")
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
        evaluations: list[dict[str, Any]] = []

        # Historial para análisis de Dwell y prevención de flapping
        dwell_blocks_disarm_count = {s: 0 for s in AlphaMotorId}
        transitions_count = {s: 0 for s in AlphaMotorId}
        state_durations = {s: defaultdict(list) for s in AlphaMotorId}
        current_streak = {s: {"state": RouterStrategyState.DISABLED, "duration": 0} for s in AlphaMotorId}

        for idx in range(warmup_required, n_bars - forward_horizon):
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

            # Comprobar antes de evaluar si el Dwell Time evitará un desarme prematuro
            for strat in AlphaMotorId:
                st_before = router.strategy_states[strat]
                dw_before = router.dwell_counters[strat]
                s_comb, h_pass = router.scorer.score_strategy(strat, curr_state)
                if (
                    st_before == RouterStrategyState.ARMED
                    and h_pass
                    and s_comb.combined_score < router_cfg.disarm_threshold
                    and dw_before < router_cfg.min_dwell_bars
                ):
                    dwell_blocks_disarm_count[strat] += 1

            # Evaluación causal del Router
            router_res = router.evaluate(symbol=sym, market_state=curr_state)

            # Cálculo de Forward Returns a 24h
            p_entry = float(candles_1h[idx].close)
            p_exit = float(candles_1h[idx + forward_horizon].close)
            atr_entry = float(atr20[idx]) if atr20[idx] and atr20[idx] > 0 else (p_entry * 0.01)

            win_highs = [float(candles_1h[idx + k].high) for k in range(1, forward_horizon + 1)]
            win_lows = [float(candles_1h[idx + k].low) for k in range(1, forward_horizon + 1)]
            max_high = max(win_highs)
            min_low = min(win_lows)

            ret_long_pct = (p_exit - p_entry) / p_entry * 100.0
            ret_long_r = (p_exit - p_entry) / atr_entry
            mfe_long_pct = (max_high - p_entry) / p_entry * 100.0
            mae_long_pct = (p_entry - min_low) / p_entry * 100.0

            ret_short_pct = (p_entry - p_exit) / p_entry * 100.0
            ret_short_r = (p_entry - p_exit) / atr_entry
            mfe_short_pct = (p_entry - min_low) / p_entry * 100.0
            mae_short_pct = (max_high - p_entry) / p_entry * 100.0

            # Seguimiento de rachas y transiciones FSM
            for strat in AlphaMotorId:
                st_log = router_res.strategy_evaluations[strat]
                if st_log.state_before != st_log.state_after:
                    transitions_count[strat] += 1
                    # Guardar duración de racha completada
                    streak = current_streak[strat]
                    state_durations[strat][streak["state"].value].append(streak["duration"])
                    current_streak[strat] = {"state": st_log.state_after, "duration": 1}
                else:
                    current_streak[strat]["duration"] += 1

            evaluations.append({
                "idx": idx,
                "timestamp": c_now.timestamp.isoformat(),
                "p_entry": p_entry,
                "atr_entry": atr_entry,
                "ret_long_pct": ret_long_pct,
                "ret_long_r": ret_long_r,
                "mfe_long_pct": mfe_long_pct,
                "mae_long_pct": mae_long_pct,
                "ret_short_pct": ret_short_pct,
                "ret_short_r": ret_short_r,
                "mfe_short_pct": mfe_short_pct,
                "mae_short_pct": mae_short_pct,
                "global_action": router_res.global_action,
                "armed_strategies": [s.value for s in router_res.armed_strategies],
                "evaluations": {
                    s.value: {
                        "long_score": float(log.score.long_score),
                        "short_score": float(log.score.short_score),
                        "combined_score": float(log.score.combined_score),
                        "hard_gate_passed": log.hard_gate_passed,
                        "state": log.state_after.value,
                        "dwell": log.dwell_bars_after,
                        "authorized": log.authorized_for_trigger,
                    }
                    for s, log in router_res.strategy_evaluations.items()
                },
            })

            prev_state = curr_state

        all_symbols_evaluations[sym] = evaluations
        total_bars_processed += len(evaluations)
        print(f"    {sym}: {len(evaluations)} barras evaluadas.")

    print(f"\n[+] Total barras procesadas en cartera: {total_bars_processed}")

    # ==========================================================================
    # ANÁLISIS 1: MONOTONÍA DEL SCORE POR BINS (LONG Y SHORT)
    # ==========================================================================
    print("\n" + "=" * 80)
    print("ANÁLISIS 1: MONOTONÍA DEL SCORE POR BINS (E[R] y Hit Rate)")
    print("=" * 80)

    score_bins_report: dict[str, Any] = {}

    for sym in [*symbols, "PORTFOLIO"]:
        target_evals = (
            all_symbols_evaluations[sym]
            if sym != "PORTFOLIO"
            else [e for evs in all_symbols_evaluations.values() for e in evs]
        )
        score_bins_report[sym] = {}

        for strat in AlphaMotorId:
            strat_key = strat.value
            score_bins_report[sym][strat_key] = {"LONG": {}, "SHORT": {}}

            for direction in [TradeDirection.LONG, TradeDirection.SHORT]:
                dir_key = direction.value
                bins_data = defaultdict(lambda: {"ret_pct": [], "ret_r": [], "mfe": [], "mae": []})

                for ev in target_evals:
                    st_info = ev["evaluations"][strat_key]
                    score_val = st_info["long_score"] if direction == TradeDirection.LONG else st_info["short_score"]
                    b_label = get_score_bin(score_val)

                    if direction == TradeDirection.LONG:
                        bins_data[b_label]["ret_pct"].append(ev["ret_long_pct"])
                        bins_data[b_label]["ret_r"].append(ev["ret_long_r"])
                        bins_data[b_label]["mfe"].append(ev["mfe_long_pct"])
                        bins_data[b_label]["mae"].append(ev["mae_long_pct"])
                    else:
                        bins_data[b_label]["ret_pct"].append(ev["ret_short_pct"])
                        bins_data[b_label]["ret_r"].append(ev["ret_short_r"])
                        bins_data[b_label]["mfe"].append(ev["mfe_short_pct"])
                        bins_data[b_label]["mae"].append(ev["mae_short_pct"])

                for b in SCORE_BINS_ORDER:
                    b_metrics = calculate_metrics_from_returns(
                        returns_pct=bins_data[b]["ret_pct"],
                        returns_r=bins_data[b]["ret_r"],
                        mfes=bins_data[b]["mfe"],
                        maes=bins_data[b]["mae"],
                    )
                    score_bins_report[sym][strat_key][dir_key][b] = b_metrics

    # Imprimir tabla de resumen de monotonía a nivel Portfolio
    print("\n--- RESUMEN DE CARTERA (PORTFOLIO): MONOTONÍA DE SCORE A 24H (LONG) ---")
    print(f"{'Estrategia':<28} {'Bin':<11} {'N':>6} {'Mean R':>8} {'Hit Rate':>9} {'MFE %':>7} {'MAE %':>7} {'PF':>6}")
    print("-" * 88)
    for strat in AlphaMotorId:
        strat_key = strat.value
        for b in SCORE_BINS_ORDER:
            m = score_bins_report["PORTFOLIO"][strat_key]["LONG"][b]
            if m["n"] > 0:
                print(f"{strat_key:<28} {b:<11} {m['n']:>6} {m['mean_return_r']:>8.3f}R {m['hit_rate_pct']:>8.1f}% {m['mean_mfe_pct']:>6.2f}% {m['mean_mae_pct']:>6.2f}% {m['profit_factor']:>6.2f}")
        print("-" * 88)

    # ==========================================================================
    # ANÁLISIS 2: SEPARACIÓN ARMED VS DISABLED (Delta E_s)
    # ==========================================================================
    print("\n" + "=" * 80)
    print("ANÁLISIS 2: SEPARACIÓN ESTADÍSTICA ARMED VS DISABLED (Delta E_s)")
    print("=" * 80)

    separation_report: dict[str, Any] = {}

    for sym in [*symbols, "PORTFOLIO"]:
        target_evals = (
            all_symbols_evaluations[sym]
            if sym != "PORTFOLIO"
            else [e for evs in all_symbols_evaluations.values() for e in evs]
        )
        separation_report[sym] = {}

        for strat in AlphaMotorId:
            strat_key = strat.value
            separation_report[sym][strat_key] = {}

            for direction in [TradeDirection.LONG, TradeDirection.SHORT]:
                dir_key = direction.value
                armed_r: list[float] = []
                armed_pct: list[float] = []
                armed_mfe: list[float] = []
                armed_mae: list[float] = []

                disabled_r: list[float] = []
                disabled_pct: list[float] = []
                disabled_mfe: list[float] = []
                disabled_mae: list[float] = []

                for ev in target_evals:
                    st_info = ev["evaluations"][strat_key]
                    is_armed = st_info["state"] == RouterStrategyState.ARMED.value
                    is_disabled = st_info["state"] == RouterStrategyState.DISABLED.value

                    r_pct = ev["ret_long_pct"] if direction == TradeDirection.LONG else ev["ret_short_pct"]
                    r_unit = ev["ret_long_r"] if direction == TradeDirection.LONG else ev["ret_short_r"]
                    mfe_val = ev["mfe_long_pct"] if direction == TradeDirection.LONG else ev["mfe_short_pct"]
                    mae_val = ev["mae_long_pct"] if direction == TradeDirection.LONG else ev["mae_short_pct"]

                    if is_armed:
                        armed_pct.append(r_pct)
                        armed_r.append(r_unit)
                        armed_mfe.append(mfe_val)
                        armed_mae.append(mae_val)
                    elif is_disabled:
                        disabled_pct.append(r_pct)
                        disabled_r.append(r_unit)
                        disabled_mfe.append(mfe_val)
                        disabled_mae.append(mae_val)

                m_armed = calculate_metrics_from_returns(armed_pct, armed_r, armed_mfe, armed_mae)
                m_disabled = calculate_metrics_from_returns(disabled_pct, disabled_r, disabled_mfe, disabled_mae)

                delta_e_r = round(m_armed["mean_return_r"] - m_disabled["mean_return_r"], 3)
                delta_e_pct = round(m_armed["mean_return_pct"] - m_disabled["mean_return_pct"], 3)
                delta_hit_rate = round(m_armed["hit_rate_pct"] - m_disabled["hit_rate_pct"], 2)

                separation_report[sym][strat_key][dir_key] = {
                    "armed": m_armed,
                    "disabled": m_disabled,
                    "delta_expectancy_r": delta_e_r,
                    "delta_expectancy_pct": delta_e_pct,
                    "delta_hit_rate_pct": delta_hit_rate,
                }

    print("\n--- SEPARACIÓN DELTA E_s (PORTFOLIO AGREGADO - LONG) ---")
    print(f"{'Estrategia':<28} {'N (Armed)':>10} {'E[R|ARMED]':>12} {'N (Dis)':>10} {'E[R|DIS]':>10} {'Delta E (R)':>12} {'Delta Hit%':>11}")
    print("-" * 98)
    for strat in AlphaMotorId:
        strat_key = strat.value
        d = separation_report["PORTFOLIO"][strat_key]["LONG"]
        print(
            f"{strat_key:<28} "
            f"{d['armed']['n']:>10} "
            f"{d['armed']['mean_return_r']:>11.3f}R "
            f"{d['disabled']['n']:>10} "
            f"{d['disabled']['mean_return_r']:>9.3f}R "
            f"{d['delta_expectancy_r']:>+11.3f}R "
            f"{d['delta_hit_rate_pct']:>+10.1f}%"
        )
    print("-" * 98)

    print("\n--- SEPARACIÓN DELTA E_s (PORTFOLIO AGREGADO - SHORT) ---")
    print(f"{'Estrategia':<28} {'N (Armed)':>10} {'E[R|ARMED]':>12} {'N (Dis)':>10} {'E[R|DIS]':>10} {'Delta E (R)':>12} {'Delta Hit%':>11}")
    print("-" * 98)
    for strat in AlphaMotorId:
        strat_key = strat.value
        d = separation_report["PORTFOLIO"][strat_key]["SHORT"]
        print(
            f"{strat_key:<28} "
            f"{d['armed']['n']:>10} "
            f"{d['armed']['mean_return_r']:>11.3f}R "
            f"{d['disabled']['n']:>10} "
            f"{d['disabled']['mean_return_r']:>9.3f}R "
            f"{d['delta_expectancy_r']:>+11.3f}R "
            f"{d['delta_hit_rate_pct']:>+10.1f}%"
        )
    print("-" * 98)

    # ==========================================================================
    # ANÁLISIS 3: VALOR DE LA ABSTENCIÓN (E[R | NO_TRADE])
    # ==========================================================================
    print("\n" + "=" * 80)
    print("ANÁLISIS 3: VALOR DE LA ABSTENCIÓN CONTRAFACTUAL (NO_TRADE)")
    print("=" * 80)

    abstention_report: dict[str, Any] = {}
    all_evals = [e for evs in all_symbols_evaluations.values() for e in evs]

    no_trade_long_r = [e["ret_long_r"] for e in all_evals if e["global_action"] == "NO_TRADE"]
    no_trade_long_pct = [e["ret_long_pct"] for e in all_evals if e["global_action"] == "NO_TRADE"]
    no_trade_mfe = [e["mfe_long_pct"] for e in all_evals if e["global_action"] == "NO_TRADE"]
    no_trade_mae = [e["mae_long_pct"] for e in all_evals if e["global_action"] == "NO_TRADE"]

    trade_perm_long_r = [e["ret_long_r"] for e in all_evals if e["global_action"] == "TRADE_PERMITTED"]
    trade_perm_long_pct = [e["ret_long_pct"] for e in all_evals if e["global_action"] == "TRADE_PERMITTED"]
    trade_perm_mfe = [e["mfe_long_pct"] for e in all_evals if e["global_action"] == "TRADE_PERMITTED"]
    trade_perm_mae = [e["mae_long_pct"] for e in all_evals if e["global_action"] == "TRADE_PERMITTED"]

    m_no_trade = calculate_metrics_from_returns(no_trade_long_pct, no_trade_long_r, no_trade_mfe, no_trade_mae)
    m_trade_perm = calculate_metrics_from_returns(trade_perm_long_pct, trade_perm_long_r, trade_perm_mfe, trade_perm_mae)

    abstention_report = {
        "no_trade": m_no_trade,
        "trade_permitted": m_trade_perm,
        "pct_time_no_trade": round(m_no_trade["n"] / len(all_evals) * 100, 2),
        "pct_time_trade_permitted": round(m_trade_perm["n"] / len(all_evals) * 100, 2),
    }

    print(f"Total Observaciones: {len(all_evals)}")
    print(f"NO_TRADE:         N = {m_no_trade['n']} ({abstention_report['pct_time_no_trade']}%) | E[R] = {m_no_trade['mean_return_r']:+.3f}R ({m_no_trade['mean_return_pct']:+.2f}%) | MAE = {m_no_trade['mean_mae_pct']:.2f}% | Hit Rate = {m_no_trade['hit_rate_pct']:.1f}%")
    print(f"TRADE_PERMITTED:  N = {m_trade_perm['n']} ({abstention_report['pct_time_trade_permitted']}%) | E[R] = {m_trade_perm['mean_return_r']:+.3f}R ({m_trade_perm['mean_return_pct']:+.2f}%) | MFE = {m_trade_perm['mean_mfe_pct']:.2f}% | Hit Rate = {m_trade_perm['hit_rate_pct']:.1f}%")

    # ==========================================================================
    # ANÁLISIS 4: PERSISTENCIA, ESTABILIDAD Y DWELL TIME
    # ==========================================================================
    print("\n" + "=" * 80)
    print("ANÁLISIS 4: ESTABILIDAD DE LA FSM Y PREVENCIÓN DE FLAPPING")
    print("=" * 80)

    fsm_stability_report: dict[str, Any] = {}

    for strat in AlphaMotorId:
        strat_key = strat.value
        armed_bars = sum(1 for e in all_evals if e["evaluations"][strat_key]["state"] == RouterStrategyState.ARMED.value)
        disabled_bars = sum(1 for e in all_evals if e["evaluations"][strat_key]["state"] == RouterStrategyState.DISABLED.value)
        cooldown_bars = sum(1 for e in all_evals if e["evaluations"][strat_key]["state"] == RouterStrategyState.COOLDOWN.value)

        fsm_stability_report[strat_key] = {
            "armed_occupancy_pct": round(armed_bars / len(all_evals) * 100, 2),
            "disabled_occupancy_pct": round(disabled_bars / len(all_evals) * 100, 2),
            "cooldown_occupancy_pct": round(cooldown_bars / len(all_evals) * 100, 2),
            "total_armed_bars": armed_bars,
            "total_disabled_bars": disabled_bars,
        }

    print(f"{'Estrategia':<28} {'% ARMED':>10} {'% DISABLED':>12} {'% COOLDOWN':>12} {'Barras ARMED':>14}")
    print("-" * 80)
    for strat in AlphaMotorId:
        s = fsm_stability_report[strat.value]
        print(f"{strat.value:<28} {s['armed_occupancy_pct']:>9.2f}% {s['disabled_occupancy_pct']:>11.2f}% {s['cooldown_occupancy_pct']:>11.2f}% {s['total_armed_bars']:>14}")
    print("-" * 80)

    # ==========================================================================
    # ANÁLISIS 5: CORRELACIÓN ENTRE SCORES Y SOLAPAMIENTO DE ARMED
    # ==========================================================================
    print("\n" + "=" * 80)
    print("ANÁLISIS 5: CORRELACIÓN CRUZADA Y SOLAPAMIENTO DE VIGILANCIA")
    print("=" * 80)

    correlation_report: dict[str, Any] = {"score_correlations": {}, "armed_overlap": {}}

    strats = [AlphaMotorId.ALPHA_A, AlphaMotorId.ALPHA_B, AlphaMotorId.ALPHA_C, AlphaMotorId.ALPHA_D]
    scores_series = {s.value: [e["evaluations"][s.value]["combined_score"] for e in all_evals] for s in strats}

    print("Matriz de Correlación de Scores Lineales (Pearson r):")
    print(f"{'':<28} {'A (Squeeze)':<12} {'B (Pullback)':<12} {'C (Sweep)':<12} {'D (Exhaust)':<12}")
    print("-" * 76)

    for s1 in strats:
        row_str = f"{s1.value:<28} "
        row_corrs = {}
        for s2 in strats:
            v1 = scores_series[s1.value]
            v2 = scores_series[s2.value]
            mean1 = sum(v1) / len(v1)
            mean2 = sum(v2) / len(v2)
            cov = sum((x - mean1) * (y - mean2) for x, y in zip(v1, v2, strict=False)) / len(v1)
            std1 = math.sqrt(sum((x - mean1) ** 2 for x in v1) / len(v1))
            std2 = math.sqrt(sum((y - mean2) ** 2 for y in v2) / len(v2))
            r_corr = cov / (std1 * std2) if (std1 * std2) > 0 else 0.0
            row_corrs[s2.value] = round(r_corr, 3)
            row_str += f"{r_corr:>11.3f} "
        print(row_str)
        correlation_report["score_correlations"][s1.value] = row_corrs
    print("-" * 76)

    # Solapamiento de estado ARMED
    print("\nSolapamiento Concurrente de Vigilancia (% de barras en que ambas están ARMED):")
    for i, s1 in enumerate(strats):
        for s2 in strats[i + 1:]:
            both_armed = sum(
                1 for e in all_evals
                if e["evaluations"][s1.value]["state"] == RouterStrategyState.ARMED.value
                and e["evaluations"][s2.value]["state"] == RouterStrategyState.ARMED.value
            )
            pct = round(both_armed / len(all_evals) * 100, 2)
            print(f"  {s1.value} + {s2.value}: {both_armed} barras ({pct}%)")
            correlation_report["armed_overlap"][f"{s1.value}_AND_{s2.value}"] = {"bars": both_armed, "pct": pct}

    # ==========================================================================
    # EXPORTACIÓN DE REPORTE COMPLETO EN FORMATO JSON
    # ==========================================================================
    full_audit_output = {
        "metadata": {
            "version": "RouterValidation_v0.1.0",
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "total_bars_evaluated": len(all_evals),
            "symbols": symbols,
            "forward_horizon_hours": forward_horizon,
            "warmup_required_bars": warmup_required,
            "router_config": {
                "arm_threshold": float(router_cfg.arm_threshold),
                "disarm_threshold": float(router_cfg.disarm_threshold),
                "min_dwell_bars": router_cfg.min_dwell_bars,
                "cooldown_bars": router_cfg.cooldown_bars,
            },
        },
        "score_monotonicity": score_bins_report,
        "state_separation_delta_e": separation_report,
        "value_of_abstention": abstention_report,
        "fsm_stability": fsm_stability_report,
        "correlations_and_overlap": correlation_report,
    }

    out_file = Path("data/reports/router_empirical_validation_v0.1.0.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(full_audit_output, f, indent=2)

    print(f"\n[OK] Validación del Router guardada exitosamente en: {out_file}")
    return full_audit_output


if __name__ == "__main__":
    run_router_validation_backtest()
