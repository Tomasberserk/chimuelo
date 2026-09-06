"""Auditoría Empírica Exhaustiva del QuantitativeRegimeEngine (v0.1.0-frozen).

Calcula sobre 2 años de datos reales (BTCUSDT, ETHUSDT, SOLUSDT en 1h):
1. Regime Occupancy (frecuencia y % de tiempo por dimensión)
2. Regime Persistence (duración media, mediana, P10, P90, max, P(S_t = S_{t-1}))
3. Matrices de Transición P(S_{t+1} = j | S_t = i)
4. Estadísticas de Eventos de Transición (COMPRESSION_TO_EXPANSION, etc.)
5. Forward Returns Condicionados (E[R_h], mediana, std, win rate, MFE, MAE para h=1, 4, 8, 24)
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
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
    get_last_closed_4h_context,
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


def synthesize_4h_candles(candles_1h: list[HistoricalCandle]) -> list[HistoricalCandle]:
    """Sintetiza velas 4h alineadas a las 00, 04, 08, 12, 16, 20 UTC."""
    candles_4h = []
    bucket: list[HistoricalCandle] = []
    for c in candles_1h:
        if not bucket:
            # Debe iniciar en frontera de 4h
            if c.timestamp.hour % 4 == 0:
                bucket.append(c)
        else:
            bucket.append(c)
            if len(bucket) == 4:
                c_4h = HistoricalCandle(
                    timestamp=bucket[0].timestamp,
                    open=bucket[0].open,
                    high=max(x.high for x in bucket),
                    low=min(x.low for x in bucket),
                    close=bucket[-1].close,
                    volume=sum((x.volume for x in bucket), Decimal("0")),
                )
                candles_4h.append(c_4h)
                bucket = []
    return candles_4h


def run_empirical_audit() -> dict[str, Any]:
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    cfg = RegimeEngineConfig()
    engine = QuantitativeRegimeEngine(config=cfg)

    results_by_symbol = {}

    for sym in symbols:
        path = f"data/cache_extended/{sym}_1h.json"
        print(f"--> Cargando y procesando {sym} desde {path}...")
        candles_1h = load_candles_from_cache(path)
        candles_4h = synthesize_4h_candles(candles_1h)

        closes = [c.close for c in candles_1h]
        highs = [c.high for c in candles_1h]
        lows = [c.low for c in candles_1h]
        volumes = [c.volume for c in candles_1h]
        n_bars = len(candles_1h)

        print(f"    Calculando indicadores base para {n_bars} velas...")
        ema20 = calculate_ema(closes, 20)
        ema50 = calculate_ema(closes, 50)
        atr20 = calculate_atr(highs, lows, closes, 20)
        adx = calculate_adx(highs, lows, closes, 14)
        rv = [calculate_rolling_realized_volatility(closes, i, 20) for i in range(n_bars)]
        tr = [abs(highs[i] - lows[i]) for i in range(n_bars)]

        warmup_required = 770
        states = []
        prev_state = None

        print(f"    Evaluando QuantitativeRegimeEngine desde barra {warmup_required} hasta {n_bars}...")
        for idx in range(warmup_required, n_bars):
            s50 = calculate_slope_50(ema50, atr20, idx)
            ts = calculate_trend_spread(ema20, ema50, atr20, idx)
            adx_val = adx[idx] or Decimal("15.0")
            er_val = calculate_efficiency_ratio(closes, idx, 20)
            atr_p = calculate_causal_rolling_percentile(atr20, idx, 500)
            rv_p = calculate_causal_rolling_percentile(rv, idx, 500)
            vol_p = calculate_causal_rolling_percentile(volumes, idx, 200)
            tr_p = calculate_causal_rolling_percentile(tr, idx, 200)

            t_reg = engine.classify_trend(s50, ts, adx_val)
            v_reg = engine.classify_volatility(atr_p, rv_p)
            s_reg = engine.classify_structure(er_val)
            p_reg = engine.classify_participation(vol_p, tr_p)
            d_reg = engine.classify_derivatives(None, None, vol_p)

            trans = engine.detect_transition(
                current_trend=t_reg,
                current_volatility=v_reg,
                current_structure=s_reg,
                current_participation=p_reg,
                current_derivatives=d_reg,
                previous_state=prev_state,
            )

            c_now = candles_1h[idx]
            # MarketStateVector simplificado para el histórico
            curr_state = {
                "idx": idx,
                "timestamp": c_now.timestamp.isoformat(),
                "close": float(c_now.close),
                "trend": t_reg.value,
                "volatility": v_reg.value,
                "structure": s_reg.value,
                "participation": p_reg.value,
                "derivatives": d_reg.value,
                "transition": trans.value,
                "slope_50": float(s50),
                "trend_spread": float(ts),
                "adx_14": float(adx_val),
                "efficiency_ratio": float(er_val),
                "atr_percentile": float(atr_p),
                "rv_percentile": float(rv_p),
                "volume_percentile": float(vol_p),
                "tr_percentile": float(tr_p),
            }
            states.append(curr_state)
            prev_state = MarketStateVector(
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

        total_evaluated = len(states)
        print(f"    Evaluación completada: {total_evaluated} barras evaluadas.")

        # ======================================================================
        # 1. REGIME OCCUPANCY
        # ======================================================================
        occupancy = {}
        for dim in ["trend", "volatility", "structure", "participation", "derivatives"]:
            counts = defaultdict(int)
            for s in states:
                counts[s[dim]] += 1
            occupancy[dim] = {
                k: {
                    "count": count,
                    "pct": round(count / total_evaluated * 100, 2),
                }
                for k, count in sorted(counts.items(), key=lambda x: x[1], reverse=True)
            }

        # ======================================================================
        # 2. REGIME PERSISTENCE
        # ======================================================================
        persistence = {}
        for dim in ["trend", "volatility", "structure", "participation"]:
            dim_persistence = {}
            # Obtener lista secuencial de estados en esta dimensión
            seq = [s[dim] for s in states]
            unique_states = sorted(list(set(seq)))

            for u_st in unique_states:
                # Calcular episodios y duraciones
                episodes = []
                current_ep_len = 0
                for val in seq:
                    if val == u_st:
                        current_ep_len += 1
                    else:
                        if current_ep_len > 0:
                            episodes.append(current_ep_len)
                            current_ep_len = 0
                if current_ep_len > 0:
                    episodes.append(current_ep_len)

                # Calcular stay probability P(S_t = S_{t-1} | S_{t-1} = u_st)
                same_stay_count = 0
                total_prev_count = 0
                for t_i in range(1, len(seq)):
                    if seq[t_i - 1] == u_st:
                        total_prev_count += 1
                        if seq[t_i] == u_st:
                            same_stay_count += 1

                p_stay = round(same_stay_count / total_prev_count * 100, 2) if total_prev_count > 0 else 0.0

                if episodes:
                    ep_sorted = sorted(episodes)
                    mean_dur = sum(episodes) / len(episodes)
                    med_dur = ep_sorted[len(ep_sorted) // 2]
                    p10 = ep_sorted[int(len(ep_sorted) * 0.10)]
                    p90 = ep_sorted[min(len(ep_sorted) - 1, int(len(ep_sorted) * 0.90))]
                    max_dur = max(episodes)
                else:
                    mean_dur = med_dur = p10 = p90 = max_dur = 0

                dim_persistence[u_st] = {
                    "episodes": len(episodes),
                    "mean_duration_bars": round(mean_dur, 2),
                    "median_duration_bars": med_dur,
                    "p10_duration_bars": p10,
                    "p90_duration_bars": p90,
                    "max_duration_bars": max_dur,
                    "stay_probability_pct": p_stay,
                }
            persistence[dim] = dim_persistence

        # ======================================================================
        # 3. TRANSITION MATRIX
        # ======================================================================
        transition_matrices = {}
        for dim in ["trend", "volatility", "structure", "participation"]:
            seq = [s[dim] for s in states]
            unique_states = sorted(list(set(seq)))
            matrix = {u_from: {u_to: 0 for u_to in unique_states} for u_from in unique_states}
            totals = {u_from: 0 for u_from in unique_states}

            for t_i in range(len(seq) - 1):
                u_from = seq[t_i]
                u_to = seq[t_i + 1]
                matrix[u_from][u_to] += 1
                totals[u_from] += 1

            prob_matrix = {}
            for u_from in unique_states:
                prob_matrix[u_from] = {}
                tot = totals[u_from]
                for u_to in unique_states:
                    prob = round((matrix[u_from][u_to] / tot) * 100, 2) if tot > 0 else 0.0
                    prob_matrix[u_from][u_to] = prob
            transition_matrices[dim] = prob_matrix

        # ======================================================================
        # 4. TRANSITION EVENT STATISTICS
        # ======================================================================
        trans_counts = defaultdict(int)
        for s in states:
            trans_counts[s["transition"]] += 1

        trans_event_stats = {
            k: {
                "count": count,
                "pct": round(count / total_evaluated * 100, 2),
            }
            for k, count in sorted(trans_counts.items(), key=lambda x: x[1], reverse=True)
        }

        # ======================================================================
        # 5. CONDITIONAL FORWARD RETURNS & EXCURSIONS
        # ======================================================================
        horizons = [1, 4, 8, 24]
        # Calcular retornos futuros y MFE/MAE para cada barra
        # MFE = max_{k=1..h} (High[t+k] - Close[t]) / Close[t] * 100
        # MAE = min_{k=1..h} (Low[t+k] - Close[t]) / Close[t] * 100
        # R_h = (Close[t+h] - Close[t]) / Close[t] * 100

        forward_stats_by_state = {}

        # Mapear estados a investigar: todos los de Trend, Volatility, Structure y Transiciones clave
        test_dimensions = ["trend", "volatility", "structure", "participation", "transition"]

        for dim in test_dimensions:
            forward_stats_by_state[dim] = {}
            unique_states = sorted(list(set(s[dim] for s in states)))

            for st_val in unique_states:
                horizon_results = {}
                for h in horizons:
                    returns_h = []
                    mfe_h = []
                    mae_h = []

                    for i, s in enumerate(states):
                        if s[dim] == st_val:
                            orig_idx = s["idx"]
                            if orig_idx + h < n_bars:
                                p_entry = float(candles_1h[orig_idx].close)
                                p_exit = float(candles_1h[orig_idx + h].close)
                                r = (p_exit - p_entry) / p_entry * 100.0
                                returns_h.append(r)

                                # Excursiones en ventana [1..h]
                                window_highs = [float(candles_1h[orig_idx + k].high) for k in range(1, h + 1)]
                                window_lows = [float(candles_1h[orig_idx + k].low) for k in range(1, h + 1)]
                                mfe = (max(window_highs) - p_entry) / p_entry * 100.0
                                mae = (min(window_lows) - p_entry) / p_entry * 100.0
                                mfe_h.append(mfe)
                                mae_h.append(mae)

                    if returns_h:
                        ret_sorted = sorted(returns_h)
                        mean_r = sum(returns_h) / len(returns_h)
                        med_r = ret_sorted[len(ret_sorted) // 2]
                        variance = sum((x - mean_r) ** 2 for x in returns_h) / len(returns_h)
                        std_r = math.sqrt(variance)
                        win_rate = (sum(1 for x in returns_h if x > 0) / len(returns_h)) * 100.0
                        mean_mfe = sum(mfe_h) / len(mfe_h)
                        mean_mae = sum(mae_h) / len(mae_h)

                        horizon_results[f"h_{h}"] = {
                            "sample_size": len(returns_h),
                            "mean_return_pct": round(mean_r, 3),
                            "median_return_pct": round(med_r, 3),
                            "std_return_pct": round(std_r, 3),
                            "win_rate_pct": round(win_rate, 2),
                            "mean_mfe_pct": round(mean_mfe, 3),
                            "mean_mae_pct": round(mean_mae, 3),
                        }
                    else:
                        horizon_results[f"h_{h}"] = {"sample_size": 0}

                forward_stats_by_state[dim][st_val] = horizon_results

        results_by_symbol[sym] = {
            "total_bars_evaluated": total_evaluated,
            "occupancy": occupancy,
            "persistence": persistence,
            "transition_matrices": transition_matrices,
            "transition_event_stats": trans_event_stats,
            "forward_returns": forward_stats_by_state,
        }

    # Guardar reporte en JSON
    output_path = Path("data/reports/empirical_regime_audit_v0.1.0.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results_by_symbol, f, indent=2)

    print(f"\n[OK] Auditoría empírica guardada exitosamente en {output_path}")
    return results_by_symbol


if __name__ == "__main__":
    run_empirical_audit()
