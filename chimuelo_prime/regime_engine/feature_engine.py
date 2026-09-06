"""Motor de Features Cuantitativas Causales y Sincronización Temporal.

Implementa los cálculos matemáticos para las 5 dimensiones del MarketStateVector
asegurando estricta causabilidad (cero look-ahead), cálculo dinámico de warmup
y sincronización temporal verificada entre series 1h, 4h y derivados.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.regime_engine.models import ensure_utc_aware
from chimuelo_prime.strategies.indicators import calculate_atr, calculate_ema


def calculate_adx(
    highs: Sequence[Decimal],
    lows: Sequence[Decimal],
    closes: Sequence[Decimal],
    period: int = 14,
) -> list[Decimal | None]:
    """Calcula el Average Directional Index (ADX) con Wilder's Smoothing y pureza Decimal."""
    n = len(closes)
    result: list[Decimal | None] = [None] * n
    if n < period * 2:
        return result

    tr_list: list[Decimal] = [Decimal("0.0")] * n
    dm_plus: list[Decimal] = [Decimal("0.0")] * n
    dm_minus: list[Decimal] = [Decimal("0.0")] * n

    for i in range(1, n):
        h_diff = highs[i] - highs[i - 1]
        l_diff = lows[i - 1] - lows[i]

        if h_diff > l_diff and h_diff > Decimal("0.0"):
            dm_plus[i] = h_diff
        else:
            dm_plus[i] = Decimal("0.0")

        if l_diff > h_diff and l_diff > Decimal("0.0"):
            dm_minus[i] = l_diff
        else:
            dm_minus[i] = Decimal("0.0")

        tr_list[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )

    # Wilder's Smoothing inicial (primeros `period` valores)
    smooth_tr = sum(tr_list[1 : period + 1], Decimal("0.0"))
    smooth_plus = sum(dm_plus[1 : period + 1], Decimal("0.0"))
    smooth_minus = sum(dm_minus[1 : period + 1], Decimal("0.0"))

    dx_list: list[Decimal | None] = [None] * n
    alpha = Decimal("1") / Decimal(str(period))

    def _calc_dx(p_dm: Decimal, m_dm: Decimal, tr_val: Decimal) -> Decimal:
        if tr_val <= Decimal("0.0"):
            return Decimal("0.0")
        p_di = (p_dm / tr_val) * Decimal("100.0")
        m_di = (m_dm / tr_val) * Decimal("100.0")
        denom = p_di + m_di
        if denom <= Decimal("0.0"):
            return Decimal("0.0")
        return (abs(p_di - m_di) / denom) * Decimal("100.0")

    dx_list[period] = _calc_dx(smooth_plus, smooth_minus, smooth_tr)

    for i in range(period + 1, n):
        smooth_tr = smooth_tr - (smooth_tr * alpha) + tr_list[i]
        smooth_plus = smooth_plus - (smooth_plus * alpha) + dm_plus[i]
        smooth_minus = smooth_minus - (smooth_minus * alpha) + dm_minus[i]
        dx_list[i] = _calc_dx(smooth_plus, smooth_minus, smooth_tr)

    # Suavizar DX para obtener ADX
    dx_start = period
    valid_dx = [x for x in dx_list[dx_start : dx_start + period] if x is not None]
    if len(valid_dx) == period:
        adx_val = sum(valid_dx, Decimal("0.0")) / Decimal(str(period))
        result[dx_start + period - 1] = round(adx_val, 2)

        for i in range(dx_start + period, n):
            curr_dx = dx_list[i]
            if curr_dx is not None:
                adx_val = adx_val - (adx_val * alpha) + (curr_dx * alpha)
                result[i] = round(adx_val, 2)

    return result


class InsufficientWarmupError(ValueError):
    """Excepción lanzada cuando el historial no satisface el warmup dinámico requerido."""


@dataclass(frozen=True)
class DerivativeObservation:
    """Observación puntual de fondeo o interés abierto con timestamp UTC estricto."""

    timestamp: datetime
    funding_rate_8h: Decimal
    open_interest: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp", ensure_utc_aware(self.timestamp))


class FeatureWarmupPolicy:
    """Política formal de cálculo dinámico de ventana de calentamiento (Warmup)."""

    def __init__(
        self,
        window_atr_percentile: int = 500,
        window_rv_percentile: int = 500,
        window_volume_percentile: int = 200,
        window_funding_zscore: int = 720,
        window_trend_ema: int = 50,
        safety_margin: int = 50,
    ) -> None:
        self.window_atr = window_atr_percentile
        self.window_rv = window_rv_percentile
        self.window_vol = window_volume_percentile
        self.window_funding = window_funding_zscore
        self.window_ema = window_trend_ema
        self.safety_margin = safety_margin

    @property
    def required_bars_1h(self) -> int:
        """Retorna el mínimo de barras 1h requerido para computar todas las features activas."""
        return max(
            self.window_atr,
            self.window_rv,
            self.window_vol,
            self.window_funding,
            self.window_ema,
        ) + self.safety_margin

    def validate_buffer_size(self, total_bars: int) -> None:
        """Valida que la longitud del búfer cumpla el requisito estricto."""
        if total_bars < self.required_bars_1h:
            raise InsufficientWarmupError(
                f"Búfer histórico insuficiente: se proporcionaron {total_bars} barras, "
                f"pero se requieren al menos {self.required_bars_1h} barras para causalidad completa."
            )


# ==============================================================================
# FUNCIONES MATEMÁTICAS PURAS CAUSALES
# ==============================================================================


def calculate_slope_50(
    ema50_series: Sequence[Decimal | None],
    atr20_series: Sequence[Decimal | None],
    current_idx: int,
    lookback: int = 20,
) -> Decimal:
    """Calcula la pendiente de EMA50 normalizada por ATR: (EMA50[t] - EMA50[t-20]) / ATR20[t]."""
    if current_idx < lookback:
        return Decimal("0.0")

    ema_now = ema50_series[current_idx]
    ema_prev = ema50_series[current_idx - lookback]
    atr_now = atr20_series[current_idx]

    if ema_now is None or ema_prev is None or atr_now is None or atr_now <= Decimal("0.0"):
        return Decimal("0.0")

    return (ema_now - ema_prev) / atr_now


def calculate_trend_spread(
    ema20_series: Sequence[Decimal | None],
    ema50_series: Sequence[Decimal | None],
    atr20_series: Sequence[Decimal | None],
    current_idx: int,
) -> Decimal:
    """Calcula la separación de medias normalizada por volatilidad: (EMA20[t] - EMA50[t]) / ATR20[t]."""
    ema20 = ema20_series[current_idx]
    ema50 = ema50_series[current_idx]
    atr20 = atr20_series[current_idx]

    if ema20 is None or ema50 is None or atr20 is None or atr20 <= Decimal("0.0"):
        return Decimal("0.0")

    return (ema20 - ema50) / atr20


def calculate_efficiency_ratio(
    closes: Sequence[Decimal],
    current_idx: int,
    window: int = 20,
) -> Decimal:
    """Calcula el Kaufman Efficiency Ratio (ER) en la ventana causal [current_idx - window : current_idx].

    ER = |Close[t] - Close[t - window]| / Sum(|Close[i] - Close[i-1]|)
    Retorna un valor en el rango cerrado [0.0, 1.0].
    """
    if current_idx < window:
        return Decimal("0.5")

    net_change = abs(closes[current_idx] - closes[current_idx - window])
    total_movement = Decimal("0.0")

    for i in range(current_idx - window + 1, current_idx + 1):
        total_movement += abs(closes[i] - closes[i - 1])

    if total_movement <= Decimal("0.0"):
        return Decimal("0.0")

    er = net_change / total_movement
    if er > Decimal("1.0"):
        return Decimal("1.0")
    if er < Decimal("0.0"):
        return Decimal("0.0")
    return er


def calculate_rolling_realized_volatility(
    closes: Sequence[Decimal],
    current_idx: int,
    window: int = 20,
) -> Decimal:
    """Calcula la volatilidad realizada (RV) como la desviación cuadrática de retornos logarítmicos."""
    if current_idx < window:
        return Decimal("0.0")

    sum_sq = 0.0
    for i in range(current_idx - window + 1, current_idx + 1):
        c_curr = float(closes[i])
        c_prev = float(closes[i - 1])
        if c_curr > 0 and c_prev > 0:
            log_ret = math.log(c_curr / c_prev)
            sum_sq += log_ret * log_ret

    return Decimal(str(round(math.sqrt(sum_sq), 6)))


def calculate_causal_rolling_percentile(
    series: Sequence[Decimal | None],
    current_idx: int,
    window: int,
) -> Decimal:
    """Calcula el percentil causal estrictamente sobre la ventana pasada [current_idx - window + 1 : current_idx + 1].

    Garantiza CERO data leakage: ninguna observación futura influye en el cálculo.
    Retorna un valor en [0.0, 100.0].
    """
    if current_idx < window - 1:
        return Decimal("50.0")

    val_current = series[current_idx]
    if val_current is None:
        return Decimal("50.0")

    valid_window: list[Decimal] = []
    for i in range(current_idx - window + 1, current_idx + 1):
        v = series[i]
        if v is not None:
            valid_window.append(v)

    if not valid_window:
        return Decimal("50.0")

    count_le = sum(1 for x in valid_window if x <= val_current)
    pct = (Decimal(str(count_le)) / Decimal(str(len(valid_window)))) * Decimal("100.0")
    return round(pct, 2)


def calculate_funding_zscore(
    funding_observations: Sequence[Decimal],
    current_idx: int,
    window: int = 720,
) -> Decimal:
    """Calcula el Z-Score del funding acumulado en ventana causal: (F[t] - mean) / std."""
    if current_idx < window - 1 or not funding_observations:
        return Decimal("0.0")

    window_data = [float(funding_observations[i]) for i in range(current_idx - window + 1, current_idx + 1)]
    mean = sum(window_data) / len(window_data)
    variance = sum((x - mean) ** 2 for x in window_data) / len(window_data)
    std = math.sqrt(variance)

    if std <= 1e-12:
        return Decimal("0.0")

    current_f = float(funding_observations[current_idx])
    z = (current_f - mean) / std
    return Decimal(str(round(z, 3)))


def calculate_delta_oi_4h(
    oi_series: Sequence[Decimal],
    current_idx: int,
    lookback_bars: int = 4,
) -> Decimal:
    """Calcula el porcentaje de variación de Open Interest en 4 horas: (OI[t] - OI[t-4]) / OI[t-4]."""
    if current_idx < lookback_bars:
        return Decimal("0.0")

    oi_now = oi_series[current_idx]
    oi_prev = oi_series[current_idx - lookback_bars]

    if oi_prev <= Decimal("0.0"):
        return Decimal("0.0")

    return round((oi_now - oi_prev) / oi_prev, 4)


# ==============================================================================
# SINCRONIZACIÓN TEMPORAL ESTRICTA (CERO LOOK-AHEAD)
# ==============================================================================


def get_last_closed_4h_context(
    candle_1h_open_time: datetime,
    candles_4h: Sequence[HistoricalCandle],
) -> HistoricalCandle | None:
    """Obtiene estrictamente la última vela 4h CERRADA antes del inicio de la vela 1h actual.

    Regla Invariante de Causalidad:
    Una vela 4h que inició a las `T_4h` se cierra formalmente a las `T_4h + 4 horas`.
    Por tanto, para una vela 1h que inicia a las `T_1h`, una vela 4h sólo es visible si:
        (T_4h + 4 horas) <= T_1h

    Ejemplo de test:
        A las 10:00 1h: La vela 4h de las 08:00 se cierra a las 12:00 -> NO CERRADA -> INVISIBLE.
        La última vela 4h cerrada es la de las 04:00 (que cerró a las 08:00).
    """
    t_1h = ensure_utc_aware(candle_1h_open_time)
    latest_closed: HistoricalCandle | None = None

    for c_4h in candles_4h:
        t_4h_open = ensure_utc_aware(c_4h.timestamp)
        t_4h_close = t_4h_open + timedelta(hours=4)
        if t_4h_close <= t_1h and (
            latest_closed is None or c_4h.timestamp > latest_closed.timestamp
        ):
            latest_closed = c_4h

    return latest_closed


def get_last_causal_derivative_observation(
    candle_1h_open_time: datetime,
    derivative_observations: Sequence[DerivativeObservation],
) -> DerivativeObservation | None:
    """Filtra y retorna la última observación de derivados disponible estrictamente antes o en `t`."""
    t_1h = ensure_utc_aware(candle_1h_open_time)
    eligible = [obs for obs in derivative_observations if obs.timestamp <= t_1h]
    if not eligible:
        return None
    return max(eligible, key=lambda x: x.timestamp)


# ==============================================================================
# CLASE ORQUESTADORA: FEATURE ENGINE
# ==============================================================================


class QuantitativeFeatureEngine:
    """Motor de cálculo de features normalizadas y sincronización temporal multiactivo."""

    def __init__(self, warmup_policy: FeatureWarmupPolicy | None = None) -> None:
        self.warmup_policy = warmup_policy or FeatureWarmupPolicy()

    def compute_candle_features(
        self,
        candles_1h: Sequence[HistoricalCandle],
        current_idx: int,
        candles_4h: Sequence[HistoricalCandle] | None = None,
        derivatives_feed: Sequence[DerivativeObservation] | None = None,
    ) -> dict[str, Any]:
        """Calcula de forma pura y causal el conjunto de features para una vela específica."""
        # 1. Validación de Warmup
        self.warmup_policy.validate_buffer_size(current_idx + 1)

        c = candles_1h[current_idx]
        t_now = ensure_utc_aware(c.timestamp)

        closes = [x.close for x in candles_1h]
        highs = [x.high for x in candles_1h]
        lows = [x.low for x in candles_1h]
        volumes = [x.volume for x in candles_1h]

        # 2. Indicadores base
        ema20_series = calculate_ema(closes, 20)
        ema50_series = calculate_ema(closes, 50)
        atr20_series = calculate_atr(highs, lows, closes, 20)
        adx_series = calculate_adx(highs, lows, closes, 14)

        # 3. Features de Tendencia
        slope_50 = calculate_slope_50(ema50_series, atr20_series, current_idx)
        trend_spread = calculate_trend_spread(ema20_series, ema50_series, atr20_series, current_idx)
        adx_val = adx_series[current_idx] or Decimal("15.0")

        # 4. Features de Estructura (Efficiency Ratio)
        er_val = calculate_efficiency_ratio(closes, current_idx, window=20)

        # 5. Features de Volatilidad (ATR Rank y RV Rank causales)
        atr_rank = calculate_causal_rolling_percentile(atr20_series, current_idx, self.warmup_policy.window_atr)

        rv_series = [calculate_rolling_realized_volatility(closes, i, 20) for i in range(current_idx + 1)]
        rv_rank = calculate_causal_rolling_percentile(rv_series, current_idx, self.warmup_policy.window_rv)

        # 6. Features de Participación (Volume Rank y TR Rank causales)
        vol_rank = calculate_causal_rolling_percentile(volumes, current_idx, self.warmup_policy.window_vol)

        tr_series = [abs(highs[i] - lows[i]) for i in range(current_idx + 1)]
        tr_rank = calculate_causal_rolling_percentile(tr_series, current_idx, self.warmup_policy.window_vol)

        # 7. Sincronización Temporal de Contexto 4h
        context_4h_closed = None
        if candles_4h:
            context_4h = get_last_closed_4h_context(t_now, candles_4h)
            if context_4h:
                context_4h_closed = ensure_utc_aware(context_4h.timestamp)

        # 8. Sincronización Causal de Derivados
        z_funding = Decimal("0.0")
        delta_oi = Decimal("0.0")
        if derivatives_feed:
            last_deriv = get_last_causal_derivative_observation(t_now, derivatives_feed)
            if last_deriv:
                # Extraer histórico causal de fondeo
                causal_funding = [obs.funding_rate_8h for obs in derivatives_feed if obs.timestamp <= t_now]
                if len(causal_funding) >= self.warmup_policy.window_funding:
                    z_funding = calculate_funding_zscore(causal_funding, len(causal_funding) - 1, self.warmup_policy.window_funding)

                causal_oi = [obs.open_interest for obs in derivatives_feed if obs.timestamp <= t_now]
                if len(causal_oi) >= 5:
                    delta_oi = calculate_delta_oi_4h(causal_oi, len(causal_oi) - 1, 4)

        return {
            "timestamp": t_now,
            "slope_50": slope_50,
            "trend_spread": trend_spread,
            "adx_14": adx_val,
            "efficiency_ratio": er_val,
            "atr_percentile": atr_rank,
            "rv_percentile": rv_rank,
            "volume_percentile": vol_rank,
            "tr_percentile": tr_rank,
            "z_funding": z_funding,
            "delta_oi_4h": delta_oi,
            "context_4h_closed_timestamp": context_4h_closed,
        }
