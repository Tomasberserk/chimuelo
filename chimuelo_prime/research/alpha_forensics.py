"""Módulo de Diagnóstico Forense y Oracle Envelope de Alpha Motors (Fase 4.1).

Implementa la descomposición causal de la cadena de decisión:
MarketState -> Router Score -> ARMED -> Trigger -> Entry Timing -> MFE/MAE -> Exit -> Net R.

Incluye:
- Perfil multitemporal MFE / MAE (1h, 4h, 8h, 24h) en % y múltiplos R.
- Medición de latencia de entrada t -> t+1.
- Microestructura de barrido (penetración, mechas, volumen y re-tests).
- Oracle Envelope estrictamente diagnóstico.
- Gate 0 disjunto con Moving Block Bootstrap (L=24) para corregir autocorrelación.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.regime_engine.models import (
    AlphaMotorId,
    TradeCandidate,
    TradeDirection,
)


@dataclass(frozen=True)
class ForensicSignalRecord:
    """Registro forense detallado de una señal evaluada en investigación."""

    candidate_id: str
    strategy_id: str
    symbol: str
    direction: str
    score: float
    trigger_idx: int
    trigger_time: str
    entry_idx: int
    entry_time: str
    close_t: float
    open_next: float
    executed_entry: float
    stop_loss: float
    take_profit: float
    risk_unit: float
    risk_pct: float
    # MFE / MAE en %
    mfe_1h_pct: float
    mfe_4h_pct: float
    mfe_8h_pct: float
    mfe_24h_pct: float
    mae_1h_pct: float
    mae_4h_pct: float
    mae_8h_pct: float
    mae_24h_pct: float
    # MFE / MAE en R
    mfe_1h_r: float
    mfe_4h_r: float
    mfe_8h_r: float
    mfe_24h_r: float
    mae_1h_r: float
    mae_4h_r: float
    mae_8h_r: float
    mae_24h_r: float
    # Retornos de cierre en % y R
    return_1h_pct: float
    return_4h_pct: float
    return_8h_pct: float
    return_24h_pct: float
    return_24h_r: float
    # Timing
    time_to_mfe_24h_bars: int
    time_to_mae_24h_bars: int
    dir_hit_1h: bool
    dir_hit_4h: bool
    dir_hit_8h: bool
    dir_hit_24h: bool
    # Comportamiento mecánico bajo SL/TP
    would_hit_tp_before_sl: bool
    would_hit_sl_before_tp: bool
    neither_hit_24h: bool
    # Latencia t -> t+1
    mfe_t_to_next_open_pct: float
    mfe_t_to_next_open_r: float
    gap_open_close_pct: float
    excursion_before_entry_ratio: float
    # Atributos específicos de Microestructura (para C - Liquidity Sweep)
    sweep_depth_pct: float | None = None
    sweep_depth_atr: float | None = None
    wick_rejection_ratio: float | None = None
    reclaim_efficiency: float | None = None
    relative_volume: float | None = None
    second_tests_4h: int | None = None
    second_tests_8h: int | None = None
    second_tests_24h: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def calculate_moving_block_bootstrap_diff(
    series_trigger: Sequence[float],
    series_non_trigger: Sequence[float],
    block_length: int = 24,
    iterations: int = 1000,
    seed: int = 42,
) -> dict[str, Any]:
    """Calcula el Moving Block Bootstrap (MBB) para la diferencia de medias.

    Diseñado para preservar la dependencia temporal y autocorrelación en series solapadas.
    """
    n_trig = len(series_trigger)
    n_non = len(series_non_trigger)

    if n_trig == 0 or n_non == 0:
        return {
            "mean_trigger": 0.0,
            "mean_non_trigger": 0.0,
            "delta_mean": 0.0,
            "ci_95_lower": 0.0,
            "ci_95_upper": 0.0,
            "p_value_permutation": 1.0,
            "std_error": 0.0,
        }

    rng = random.Random(seed)
    mean_trig_obs = sum(series_trigger) / n_trig
    mean_non_obs = sum(series_non_trigger) / n_non
    delta_obs = mean_trig_obs - mean_non_obs

    # Construcción de bloques para series independientes o combinadas
    def sample_blocks(series: Sequence[float], target_len: int) -> list[float]:
        n = len(series)
        if n <= block_length:
            return rng.choices(list(series), k=target_len)
        resampled: list[float] = []
        max_start = n - block_length
        while len(resampled) < target_len:
            start = rng.randint(0, max_start)
            resampled.extend(series[start : start + block_length])
        return resampled[:target_len]

    boot_diffs: list[float] = []
    for _ in range(iterations):
        sample_trig = sample_blocks(series_trigger, n_trig)
        sample_non = sample_blocks(series_non_trigger, n_non)
        m_t = sum(sample_trig) / n_trig
        m_nt = sum(sample_non) / n_non
        boot_diffs.append(m_t - m_nt)

    boot_diffs.sort()
    idx_lower = int(0.025 * iterations)
    idx_upper = int(0.975 * iterations)
    ci_lower = boot_diffs[idx_lower]
    ci_upper = boot_diffs[idx_upper]

    # Test de permutación por bloques bajo H0 (delta = 0)
    # Concatenamos y re-muestreamos etiquetas por bloques
    combined = list(series_trigger) + list(series_non_trigger)
    perm_count = 0
    perm_iterations = min(iterations, 1000)

    for _ in range(perm_iterations):
        shuffled = sample_blocks(combined, n_trig + n_non)
        perm_trig = shuffled[:n_trig]
        perm_non = shuffled[n_trig:]
        perm_delta = (sum(perm_trig) / n_trig) - (sum(perm_non) / n_non)
        if abs(perm_delta) >= abs(delta_obs):
            perm_count += 1

    p_value = perm_count / perm_iterations

    # Error estándar
    mean_boot = sum(boot_diffs) / iterations
    variance = sum((x - mean_boot) ** 2 for x in boot_diffs) / (iterations - 1)
    std_error = math.sqrt(variance)

    return {
        "mean_trigger": round(mean_trig_obs, 4),
        "mean_non_trigger": round(mean_non_obs, 4),
        "delta_mean": round(delta_obs, 4),
        "ci_95_lower": round(ci_lower, 4),
        "ci_95_upper": round(ci_upper, 4),
        "p_value_permutation": round(p_value, 4),
        "std_error": round(std_error, 4),
    }


class AlphaForensicsAnalyzer:
    """Motor de análisis y diagnóstico forense profundo."""

    def __init__(
        self,
        slippage: Decimal = Decimal("0.0005"),  # 5 bps
        fee_rate: Decimal = Decimal("0.0005"),  # 5 bps
    ) -> None:
        self.slippage = slippage
        self.fee_rate = fee_rate

    def evaluate_candidate_forensics(
        self,
        candidate: TradeCandidate,
        trigger_idx: int,
        candles: Sequence[HistoricalCandle],
        atr20: Sequence[Decimal | None],
        lookback_c: int = 24,
    ) -> ForensicSignalRecord | None:
        """Calcula el perfil forense completo de una señal técnica generada."""
        n_bars = len(candles)
        entry_idx = trigger_idx + 1

        if entry_idx >= n_bars:
            return None

        c_trig = candles[trigger_idx]
        c_entry = candles[entry_idx]
        atr_trig = atr20[trigger_idx] or Decimal("1.0")

        raw_open = c_entry.open
        close_t = c_trig.close
        is_long = candidate.direction == TradeDirection.LONG

        # 1. Ejecución al Open_{t+1} con slippage
        if is_long:
            exec_entry = raw_open * (Decimal("1.0") + self.slippage)
        else:
            exec_entry = raw_open * (Decimal("1.0") - self.slippage)

        sl = candidate.stop_loss
        tp = candidate.take_profit
        risk_unit = abs(exec_entry - sl)
        if risk_unit <= Decimal("0.0001"):
            risk_unit = exec_entry * Decimal("0.01")
        risk_pct = (risk_unit / exec_entry) * Decimal("100.0")

        # 2. Latencia y excursión entre Close_t y Open_{t+1}
        gap_pct = ((raw_open - close_t) / close_t) * Decimal("100.0")
        mfe_pre_pct = max(Decimal("0.0"), gap_pct) if is_long else max(Decimal("0.0"), -gap_pct)
        mfe_pre_r = mfe_pre_pct / risk_pct if risk_pct > Decimal("0.0") else Decimal("0.0")

        # 3. Trayectoria forward en horizontes H in {1, 4, 8, 24}
        horizons = [1, 4, 8, 24]
        max_h = 24
        available_bars = min(max_h, n_bars - entry_idx)

        highs_forward = [candles[entry_idx + k].high for k in range(available_bars)]
        lows_forward = [candles[entry_idx + k].low for k in range(available_bars)]
        closes_forward = [candles[entry_idx + k].close for k in range(available_bars)]

        mfe_h_pct: dict[int, Decimal] = {}
        mae_h_pct: dict[int, Decimal] = {}
        ret_h_pct: dict[int, Decimal] = {}
        dir_hit_h: dict[int, bool] = {}

        for h in horizons:
            bars_to_check = min(h, available_bars)
            if bars_to_check == 0:
                mfe_h_pct[h] = Decimal("0.0")
                mae_h_pct[h] = Decimal("0.0")
                ret_h_pct[h] = Decimal("0.0")
                dir_hit_h[h] = False
                continue

            sub_highs = highs_forward[:bars_to_check]
            sub_lows = lows_forward[:bars_to_check]
            c_h = closes_forward[bars_to_check - 1]

            if is_long:
                max_favorable = max(sub_highs)
                max_adverse = min(sub_lows)
                mfe_val = ((max_favorable - exec_entry) / exec_entry) * Decimal("100.0")
                mae_val = ((max_adverse - exec_entry) / exec_entry) * Decimal("100.0")
                ret_val = ((c_h - exec_entry) / exec_entry) * Decimal("100.0")
            else:
                max_favorable = min(sub_lows)
                max_adverse = max(sub_highs)
                mfe_val = ((exec_entry - max_favorable) / exec_entry) * Decimal("100.0")
                mae_val = ((exec_entry - max_adverse) / exec_entry) * Decimal("100.0")
                ret_val = ((exec_entry - c_h) / exec_entry) * Decimal("100.0")

            mfe_h_pct[h] = max(Decimal("0.0"), mfe_val)
            mae_h_pct[h] = min(Decimal("0.0"), mae_val)
            ret_h_pct[h] = ret_val
            dir_hit_h[h] = ret_val > Decimal("0.0")

        # Tiempo hasta MFE / MAE en 24h
        time_mfe = 1
        time_mae = 1
        if available_bars > 0:
            if is_long:
                peak_idx = max(range(available_bars), key=lambda i: highs_forward[i])
                trough_idx = min(range(available_bars), key=lambda i: lows_forward[i])
            else:
                peak_idx = min(range(available_bars), key=lambda i: lows_forward[i])
                trough_idx = max(range(available_bars), key=lambda i: highs_forward[i])
            time_mfe = peak_idx + 1
            time_mae = trough_idx + 1

        # Ratios R
        mfe_24_pct = mfe_h_pct[24]
        mae_24_pct = mae_h_pct[24]
        mfe_24_r = mfe_24_pct / risk_pct if risk_pct > Decimal("0.0") else Decimal("0.0")
        mae_24_r = mae_24_pct / risk_pct if risk_pct > Decimal("0.0") else Decimal("0.0")
        ret_24_r = ret_h_pct[24] / risk_pct if risk_pct > Decimal("0.0") else Decimal("0.0")

        # Excursion before entry ratio
        denom = mfe_24_pct + mfe_pre_pct
        excursion_ratio = float(mfe_pre_pct / denom) if denom > Decimal("0.0001") else 0.0

        # 4. Evaluación de SL/TP mecánico en 24h bajo Stop-First
        would_hit_tp = False
        would_hit_sl = False

        for k in range(available_bars):
            h_bar = highs_forward[k]
            l_bar = lows_forward[k]

            if is_long:
                hit_s = l_bar <= sl
                hit_t = h_bar >= tp
            else:
                hit_s = h_bar >= sl
                hit_t = l_bar <= tp

            if hit_s and hit_t:
                would_hit_sl = True  # Stop-First
                break
            elif hit_s:
                would_hit_sl = True
                break
            elif hit_t:
                would_hit_tp = True
                break

        neither_hit = not (would_hit_tp or would_hit_sl)

        # 5. Atributos de Microestructura para C (Liquidity Sweep)
        sweep_depth_pct: float | None = None
        sweep_depth_atr: float | None = None
        wick_rejection: float | None = None
        reclaim_eff: float | None = None
        rel_vol: float | None = None
        tests_4h: int | None = None
        tests_8h: int | None = None
        tests_24h: int | None = None

        if candidate.strategy_id == AlphaMotorId.ALPHA_C and trigger_idx >= lookback_c:
            prior_window = candles[trigger_idx - lookback_c : trigger_idx]
            high_prior = max(c.high for c in prior_window)
            low_prior = min(c.low for c in prior_window)
            rng_trig = c_trig.high - c_trig.low
            if rng_trig <= Decimal("0.0"):
                rng_trig = Decimal("0.0001")

            # SMA 20 volumen
            vol_win = [c.volume for c in candles[max(0, trigger_idx - 20) : trigger_idx]]
            sma_vol = (sum(vol_win) / Decimal(len(vol_win))) if vol_win else Decimal("1.0")
            if sma_vol <= Decimal("0.0"):
                sma_vol = Decimal("1.0")
            rel_vol = float(c_trig.volume / sma_vol)

            if is_long:
                depth = max(Decimal("0.0"), low_prior - c_trig.low)
                sweep_depth_pct = float((depth / close_t) * Decimal("100.0"))
                sweep_depth_atr = float(depth / atr_trig) if atr_trig > Decimal("0.0") else 0.0
                wick = c_trig.close - c_trig.low
                wick_rejection = float(wick / rng_trig)
                reclaim_eff = float((c_trig.close - low_prior) / rng_trig)

                # Re-tests de nivel Low_prior en las siguientes barras
                tests_4h = sum(1 for k in range(min(4, available_bars)) if lows_forward[k] <= low_prior)
                tests_8h = sum(1 for k in range(min(8, available_bars)) if lows_forward[k] <= low_prior)
                tests_24h = sum(1 for k in range(available_bars) if lows_forward[k] <= low_prior)
            else:
                depth = max(Decimal("0.0"), c_trig.high - high_prior)
                sweep_depth_pct = float((depth / close_t) * Decimal("100.0"))
                sweep_depth_atr = float(depth / atr_trig) if atr_trig > Decimal("0.0") else 0.0
                wick = c_trig.high - c_trig.close
                wick_rejection = float(wick / rng_trig)
                reclaim_eff = float((high_prior - c_trig.close) / rng_trig)

                tests_4h = sum(1 for k in range(min(4, available_bars)) if highs_forward[k] >= high_prior)
                tests_8h = sum(1 for k in range(min(8, available_bars)) if highs_forward[k] >= high_prior)
                tests_24h = sum(1 for k in range(available_bars) if highs_forward[k] >= high_prior)

        return ForensicSignalRecord(
            candidate_id=candidate.candidate_id,
            strategy_id=candidate.strategy_id.value,
            symbol=candidate.symbol,
            direction=candidate.direction.value,
            score=float(candidate.confidence_score),
            trigger_idx=trigger_idx,
            trigger_time=c_trig.timestamp.isoformat(),
            entry_idx=entry_idx,
            entry_time=c_entry.timestamp.isoformat(),
            close_t=round(float(close_t), 4),
            open_next=round(float(raw_open), 4),
            executed_entry=round(float(exec_entry), 4),
            stop_loss=round(float(sl), 4),
            take_profit=round(float(tp), 4),
            risk_unit=round(float(risk_unit), 4),
            risk_pct=round(float(risk_pct), 3),
            mfe_1h_pct=round(float(mfe_h_pct[1]), 3),
            mfe_4h_pct=round(float(mfe_h_pct[4]), 3),
            mfe_8h_pct=round(float(mfe_h_pct[8]), 3),
            mfe_24h_pct=round(float(mfe_24_pct), 3),
            mae_1h_pct=round(float(mae_h_pct[1]), 3),
            mae_4h_pct=round(float(mae_h_pct[4]), 3),
            mae_8h_pct=round(float(mae_h_pct[8]), 3),
            mae_24h_pct=round(float(mae_24_pct), 3),
            mfe_1h_r=round(float(mfe_h_pct[1] / risk_pct), 3) if risk_pct > 0 else 0.0,
            mfe_4h_r=round(float(mfe_h_pct[4] / risk_pct), 3) if risk_pct > 0 else 0.0,
            mfe_8h_r=round(float(mfe_h_pct[8] / risk_pct), 3) if risk_pct > 0 else 0.0,
            mfe_24h_r=round(float(mfe_24_r), 3),
            mae_1h_r=round(float(mae_h_pct[1] / risk_pct), 3) if risk_pct > 0 else 0.0,
            mae_4h_r=round(float(mae_h_pct[4] / risk_pct), 3) if risk_pct > 0 else 0.0,
            mae_8h_r=round(float(mae_h_pct[8] / risk_pct), 3) if risk_pct > 0 else 0.0,
            mae_24h_r=round(float(mae_24_r), 3),
            return_1h_pct=round(float(ret_h_pct[1]), 3),
            return_4h_pct=round(float(ret_h_pct[4]), 3),
            return_8h_pct=round(float(ret_h_pct[8]), 3),
            return_24h_pct=round(float(ret_h_pct[24]), 3),
            return_24h_r=round(float(ret_24_r), 3),
            time_to_mfe_24h_bars=time_mfe,
            time_to_mae_24h_bars=time_mae,
            dir_hit_1h=dir_hit_h[1],
            dir_hit_4h=dir_hit_h[4],
            dir_hit_8h=dir_hit_h[8],
            dir_hit_24h=dir_hit_h[24],
            would_hit_tp_before_sl=would_hit_tp,
            would_hit_sl_before_tp=would_hit_sl,
            neither_hit_24h=neither_hit,
            mfe_t_to_next_open_pct=round(float(mfe_pre_pct), 3),
            mfe_t_to_next_open_r=round(float(mfe_pre_r), 3),
            gap_open_close_pct=round(float(gap_pct), 3),
            excursion_before_entry_ratio=round(excursion_ratio, 3),
            sweep_depth_pct=round(sweep_depth_pct, 3) if sweep_depth_pct is not None else None,
            sweep_depth_atr=round(sweep_depth_atr, 3) if sweep_depth_atr is not None else None,
            wick_rejection_ratio=round(wick_rejection, 3) if wick_rejection is not None else None,
            reclaim_efficiency=round(reclaim_eff, 3) if reclaim_eff is not None else None,
            relative_volume=round(rel_vol, 2) if rel_vol is not None else None,
            second_tests_4h=tests_4h,
            second_tests_8h=tests_8h,
            second_tests_24h=tests_24h,
        )


def aggregate_forensic_metrics(records: list[ForensicSignalRecord]) -> dict[str, Any]:
    """Genera las estadísticas agregadas del Oracle Envelope y métricas diagnósticas."""
    n = len(records)
    if n == 0:
        return {"n_signals": 0}

    # Distribución MFE / MAE en R
    mfe_24_r = [r.mfe_24h_r for r in records]
    mae_24_r = [r.mae_24h_r for r in records]
    mfe_24_pct = [r.mfe_24h_pct for r in records]
    mae_24_pct = [r.mae_24h_pct for r in records]

    mean_mfe_r = sum(mfe_24_r) / n
    mean_mae_r = sum(mae_24_r) / n
    mean_mfe_pct = sum(mfe_24_pct) / n
    mean_mae_pct = sum(mae_24_pct) / n

    # Probabilidades de MFE / MAE
    p_mfe_ge_1r = (sum(1 for x in mfe_24_r if x >= 1.0) / n) * 100.0
    p_mfe_ge_1_5r = (sum(1 for x in mfe_24_r if x >= 1.5) / n) * 100.0
    p_mfe_ge_2r = (sum(1 for x in mfe_24_r if x >= 2.0) / n) * 100.0
    p_mae_le_minus_1r = (sum(1 for x in mae_24_r if x <= -1.0) / n) * 100.0

    # Direccionalidad pura por horizonte
    dir_1h = (sum(1 for r in records if r.dir_hit_1h) / n) * 100.0
    dir_4h = (sum(1 for r in records if r.dir_hit_4h) / n) * 100.0
    dir_8h = (sum(1 for r in records if r.dir_hit_8h) / n) * 100.0
    dir_24h = (sum(1 for r in records if r.dir_hit_24h) / n) * 100.0

    # Comportamiento mecánico SL/TP
    p_tp_first = (sum(1 for r in records if r.would_hit_tp_before_sl) / n) * 100.0
    p_sl_first = (sum(1 for r in records if r.would_hit_sl_before_tp) / n) * 100.0
    p_neither = (sum(1 for r in records if r.neither_hit_24h) / n) * 100.0

    # Timing
    mean_time_mfe = sum(r.time_to_mfe_24h_bars for r in records) / n
    mean_time_mae = sum(r.time_to_mae_24h_bars for r in records) / n

    # Latencia pre-entry
    mean_pre_mfe_pct = sum(r.mfe_t_to_next_open_pct for r in records) / n
    mean_gap_pct = sum(r.gap_open_close_pct for r in records) / n
    mean_excursion_ratio = sum(r.excursion_before_entry_ratio for r in records) / n

    res: dict[str, Any] = {
        "n_signals": n,
        "oracle_envelope": {
            "mean_mfe_24h_r": round(mean_mfe_r, 3),
            "mean_mae_24h_r": round(mean_mae_r, 3),
            "mean_mfe_24h_pct": round(mean_mfe_pct, 2),
            "mean_mae_24h_pct": round(mean_mae_pct, 2),
            "mfe_mae_ratio": round(abs(mean_mfe_r / mean_mae_r), 2) if abs(mean_mae_r) > 0.001 else 0.0,
            "p_mfe_ge_1r_pct": round(p_mfe_ge_1r, 1),
            "p_mfe_ge_1_5r_pct": round(p_mfe_ge_1_5r, 1),
            "p_mfe_ge_2r_pct": round(p_mfe_ge_2r, 1),
            "p_mae_le_minus_1r_pct": round(p_mae_le_minus_1r, 1),
        },
        "directional_hit_rates": {
            "1h_pct": round(dir_1h, 1),
            "4h_pct": round(dir_4h, 1),
            "8h_pct": round(dir_8h, 1),
            "24h_pct": round(dir_24h, 1),
        },
        "mechanical_exit_rates": {
            "tp_before_sl_pct": round(p_tp_first, 1),
            "sl_before_tp_pct": round(p_sl_first, 1),
            "neither_hit_24h_pct": round(p_neither, 1),
        },
        "timing": {
            "mean_bars_to_mfe": round(mean_time_mfe, 1),
            "mean_bars_to_mae": round(mean_time_mae, 1),
        },
        "entry_latency": {
            "mean_pre_entry_mfe_pct": round(mean_pre_mfe_pct, 3),
            "mean_gap_pct": round(mean_gap_pct, 3),
            "mean_excursion_before_entry_ratio": round(mean_excursion_ratio, 3),
        },
    }

    # Métricas de microestructura si existen (Strategy C)
    sweeps = [r for r in records if r.sweep_depth_pct is not None]
    if sweeps:
        n_sw = len(sweeps)
        mean_depth_pct = sum(r.sweep_depth_pct for r in sweeps if r.sweep_depth_pct is not None) / n_sw
        mean_depth_atr = sum(r.sweep_depth_atr for r in sweeps if r.sweep_depth_atr is not None) / n_sw
        mean_wick = sum(r.wick_rejection_ratio for r in sweeps if r.wick_rejection_ratio is not None) / n_sw
        mean_reclaim = sum(r.reclaim_efficiency for r in sweeps if r.reclaim_efficiency is not None) / n_sw
        mean_rel_vol = sum(r.relative_volume for r in sweeps if r.relative_volume is not None) / n_sw
        p_retest_4h = (sum(1 for r in sweeps if (r.second_tests_4h or 0) > 0) / n_sw) * 100.0
        p_retest_8h = (sum(1 for r in sweeps if (r.second_tests_8h or 0) > 0) / n_sw) * 100.0
        p_retest_24h = (sum(1 for r in sweeps if (r.second_tests_24h or 0) > 0) / n_sw) * 100.0

        res["microstructure_c"] = {
            "mean_sweep_depth_pct": round(mean_depth_pct, 3),
            "mean_sweep_depth_atr": round(mean_depth_atr, 2),
            "mean_wick_rejection_ratio": round(mean_wick, 2),
            "mean_reclaim_efficiency": round(mean_reclaim, 2),
            "mean_relative_volume": round(mean_rel_vol, 2),
            "p_retest_prior_level_4h_pct": round(p_retest_4h, 1),
            "p_retest_prior_level_8h_pct": round(p_retest_8h, 1),
            "p_retest_prior_level_24h_pct": round(p_retest_24h, 1),
        }

    return res
