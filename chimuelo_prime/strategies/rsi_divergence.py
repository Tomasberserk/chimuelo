"""Estrategia Cuantitativa MVP: Divergencia Alcista en RSI + Filtro de Tendencia EMA 200 + ATR Risk.

Diseñada para capturar reversiones de alta probabilidad a favor de la macro-tendencia,
optimizada para micro-cuentas ($25 USD) con estricto control de riesgo y ratio R:R >= 1:2.5.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.strategies.base import BaseStrategy
from chimuelo_prime.strategies.indicators import (
    calculate_atr,
    calculate_ema,
    calculate_rsi,
    calculate_sma,
)
from chimuelo_prime.strategies.models import SignalType, TradeSignal
from chimuelo_prime.strategies.sentiment_service import MacroSentimentService


class RSIDivergenceStrategy(BaseStrategy):
    """Estrategia de trading algorítmico basada en divergencias RSI y filtros de volumen/tendencia."""

    def __init__(
        self,
        symbol: str = "SOLUSDT",
        rsi_period: int = 14,
        rsi_oversold_threshold: Decimal = Decimal("38.0"),
        ema_trend_period: int = 200,
        ema_fast_period: int = 20,
        atr_period: int = 14,
        atr_sl_multiplier: Decimal = Decimal("1.5"),
        risk_reward_ratio: Decimal = Decimal("2.5"),
        volume_sma_period: int = 20,
        volume_multiplier: Decimal = Decimal("1.1"),
        lookback_bars: int = 25,
        macro_sentiment_service: MacroSentimentService | None = None,
        use_structural_tp: bool = True,
        structural_tp_ratio: Decimal = Decimal("0.75"),
        rsi_overbought_exit: Decimal | None = Decimal("70.0"),
        enable_oversold_bounce: bool = True,
        oversold_bounce_rsi_threshold: Decimal = Decimal("30.0"),
    ) -> None:
        self._symbol = symbol
        self._rsi_period = rsi_period
        self._rsi_oversold = rsi_oversold_threshold
        self._ema_trend_period = ema_trend_period
        self._ema_fast_period = ema_fast_period
        self._atr_period = atr_period
        self._atr_sl_mult = atr_sl_multiplier
        self._rr_ratio = risk_reward_ratio
        self._vol_period = volume_sma_period
        self._vol_mult = volume_multiplier
        self._lookback = lookback_bars
        self._macro_sentiment_service = macro_sentiment_service
        self._use_structural_tp = use_structural_tp
        self._structural_tp_ratio = structural_tp_ratio
        self._rsi_overbought_exit = rsi_overbought_exit
        self._enable_oversold_bounce = enable_oversold_bounce
        self._oversold_bounce_rsi = Decimal(str(oversold_bounce_rsi_threshold))

        # Cachés de series temporales para evitar recomputar O(N^2)
        self._cached_closes: list[Decimal] = []
        self._cached_ema_trend: list[Decimal | None] = []
        self._cached_ema_fast: list[Decimal | None] = []
        self._cached_rsi: list[Decimal | None] = []
        self._cached_atr: list[Decimal | None] = []
        self._cached_vol_sma: list[Decimal | None] = []

    @property
    def macro_sentiment_service(self) -> MacroSentimentService | None:
        """Servicio de análisis y gestión de régimen de sentimiento macroeconómico."""
        return self._macro_sentiment_service

    @macro_sentiment_service.setter
    def macro_sentiment_service(self, service: MacroSentimentService | None) -> None:
        self._macro_sentiment_service = service

    @property
    def name(self) -> str:
        return f"RSIDivergence_{self._symbol}_TrendEMA{self._ema_trend_period}"

    def prepare_indicators(self, candles: list[HistoricalCandle]) -> None:
        """Precalcula todos los indicadores sobre la serie histórica completa."""
        closes = [c.close for c in candles]
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        volumes = [c.volume for c in candles]

        self._cached_closes = closes
        self._cached_ema_trend = calculate_ema(closes, self._ema_trend_period)
        self._cached_ema_fast = calculate_ema(closes, self._ema_fast_period)
        self._cached_rsi = calculate_rsi(closes, self._rsi_period)
        self._cached_atr = calculate_atr(highs, lows, closes, self._atr_period)
        self._cached_vol_sma = calculate_sma(volumes, self._vol_period)

    def evaluate_candle(
        self,
        candles: list[HistoricalCandle],
        current_index: int,
    ) -> TradeSignal | None:
        """Evalúa si la vela en `current_index` cumple los criterios del setup de entrada."""
        min_required = max(self._ema_trend_period, self._vol_period, self._lookback + 10)
        if current_index < min_required:
            return None

        # Si los cachés no están inicializados o tienen diferente tamaño, calcular
        if len(self._cached_closes) != len(candles):
            self.prepare_indicators(candles)

        ema_trend = self._cached_ema_trend[current_index]
        ema_fast = self._cached_ema_fast[current_index]
        rsi_val = self._cached_rsi[current_index]
        atr_val = self._cached_atr[current_index]
        vol_sma = self._cached_vol_sma[current_index]

        if (
            ema_trend is None
            or ema_fast is None
            or rsi_val is None
            or atr_val is None
            or vol_sma is None
        ):
            return None

        candle = candles[current_index]

        # 0. Filtro Macroeconómico de Sentimiento (M10): Veto de compras si can_open_longs es False
        if self._macro_sentiment_service is not None:
            if not self._macro_sentiment_service.can_open_longs():
                return None

        signal_type_matched: str | None = None
        prev_rsi_val = Decimal("0")

        # --- SETUP A: Divergencia Alcista en RSI a favor de la macro-tendencia (Precio > EMA 200) ---
        if candle.close > ema_trend and candle.volume >= (vol_sma * self._vol_mult):
            div_found, prev_price, prev_rsi = self._check_bullish_divergence(
                candles, current_index
            )
            if div_found and candle.close > candle.open and candle.close > ema_fast:
                signal_type_matched = "DIVERGENCE"
                prev_rsi_val = prev_rsi

        # --- SETUP B: Rebote en Sobreventa Extrema (Oversold Bounce / Mean Reversion) ---
        if signal_type_matched is None and self._enable_oversold_bounce:
            recent_min_rsi = min(
                (r for r in self._cached_rsi[max(0, current_index - 3) : current_index + 1] if r is not None),
                default=Decimal("100"),
            )
            prev_candle_rsi = self._cached_rsi[current_index - 1] or Decimal("0")

            # RSI en zona extrema de sobreventa y comenzando a girar al alza
            if recent_min_rsi <= self._oversold_bounce_rsi and rsi_val > prev_candle_rsi:
                # Confirmación de vela: Cierre alcista o mecha inferior de rechazo (Hammer)
                candle_range = candle.high - candle.low
                lower_wick = min(candle.open, candle.close) - candle.low
                is_bullish_candle = candle.close > candle.open
                is_hammer = candle_range > Decimal("0") and (lower_wick / candle_range) >= Decimal("0.35")

                # Volumen con absorción mínima respetable
                has_volume = candle.volume >= (vol_sma * Decimal("0.80"))

                if (is_bullish_candle or is_hammer) and has_volume:
                    signal_type_matched = "OVERSOLD_BOUNCE"

        if signal_type_matched is None:
            return None

        # 5. Cálculo Dinámico de Stop Loss y Take Profit
        entry_price = candle.close
        sl_distance = atr_val * self._atr_sl_mult
        stop_loss = entry_price - sl_distance

        # Protección: Stop Loss no puede ser menor o igual a cero ni demasiado distante (> 8%)
        if stop_loss <= Decimal("0") or (sl_distance / entry_price) > Decimal("0.08"):
            return None

        # Take Profit Matemático ATR
        math_tp = entry_price + (sl_distance * self._rr_ratio)

        if signal_type_matched == "OVERSOLD_BOUNCE":
            # Para rebote en sobreventa, proyectar hacia la EMA rápida o ratio R:R objetivo
            target_tp = math_tp
            if ema_fast > entry_price + sl_distance:
                target_tp = min(math_tp, ema_fast)
            take_profit = target_tp
            reason_text = f"Oversold Bounce (RSI: {rsi_val:.1f} <= {self._oversold_bounce_rsi}) - Mean Reversion"
        else:
            if self._use_structural_tp:
                # Techo Estructural (Máximo de las últimas velas de lookback)
                lookback_window = candles[max(0, current_index - self._lookback) : current_index + 1]
                local_swing_high = max((c.high for c in lookback_window), default=entry_price)

                if local_swing_high > entry_price:
                    structural_tp = entry_price + ((local_swing_high - entry_price) * self._structural_tp_ratio)
                    take_profit = min(math_tp, structural_tp)
                    if take_profit <= entry_price + sl_distance:
                        take_profit = math_tp
                else:
                    take_profit = math_tp
            else:
                take_profit = math_tp
            reason_text = f"Bullish RSI Divergence (RSI: {rsi_val:.1f} vs {prev_rsi_val:.1f}) + Trend > EMA{self._ema_trend_period}"

        metadata: dict[str, Any] = {
            "rsi_current": str(rsi_val),
            "rsi_prev": str(prev_rsi_val),
            "ema_trend": str(ema_trend),
            "ema_fast": str(ema_fast),
            "atr": str(atr_val),
            "sl_distance_pct": str(
                ((sl_distance / entry_price) * Decimal("100")).quantize(Decimal("0.01"))
            ),
            "rr_ratio": str(self._rr_ratio),
            "signal_mode": signal_type_matched,
        }
        if self._macro_sentiment_service is not None:
            sentiment_report = self._macro_sentiment_service.get_sentiment_report()
            metadata["macro_sentiment_score"] = str(sentiment_report.score)
            metadata["macro_sentiment_regime"] = sentiment_report.macro_regime.value
            metadata["macro_sentiment_category"] = sentiment_report.category.value

        return TradeSignal(
            timestamp=candle.timestamp,
            symbol=self._symbol,
            signal_type=SignalType.BUY,
            price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            reason=reason_text,
            metadata=metadata,
        )

    def _check_bullish_divergence(
        self,
        candles: list[HistoricalCandle],
        idx: int,
    ) -> tuple[bool, Decimal, Decimal]:
        """Detecta si existe divergencia alcista regular entre el mínimo actual y uno previo."""
        current_low = candles[idx].low
        current_rsi = self._cached_rsi[idx]
        if current_rsi is None:
            return False, Decimal("0"), Decimal("0")

        # El RSI actual o de las últimas 2 velas debe estar en zona baja/reversal (<= 45)
        recent_min_rsi = min(
            (r for r in self._cached_rsi[max(0, idx - 2) : idx + 1] if r is not None),
            default=Decimal("100"),
        )
        if recent_min_rsi > Decimal("45.0"):
            return False, Decimal("0"), Decimal("0")

        # Buscar en la ventana lookback un mínimo local anterior donde el RSI haya estado en sobreventa
        start_search = max(0, idx - self._lookback)
        end_search = max(0, idx - 4)  # Al menos 4 velas de separación

        for j in range(end_search, start_search, -1):
            past_rsi = self._cached_rsi[j]
            if past_rsi is None:
                continue

            if past_rsi <= self._rsi_oversold:
                past_low = candles[j].low
                # Precio actual hizo un mínimo más bajo o doble suelo (<= past_low + 0.5%)
                price_made_lower_or_equal = current_low <= (past_low * Decimal("1.005"))
                # RSI actual es más alto que el RSI pasado por al menos 2 puntos
                rsi_made_higher = current_rsi >= (past_rsi + Decimal("2.0"))

                if price_made_lower_or_equal and rsi_made_higher:
                    return True, past_low, past_rsi

        return False, Decimal("0"), Decimal("0")

    def should_exit_position(
        self,
        candles: list[HistoricalCandle],
        current_index: int,
    ) -> tuple[bool, str]:
        """Evalúa si la posición activa debe cerrarse dinámicamente (ej. sobrecompra de RSI)."""
        if self._rsi_overbought_exit is None:
            return False, ""

        if len(self._cached_rsi) != len(candles):
            self.prepare_indicators(candles)

        if current_index >= len(self._cached_rsi):
            return False, ""

        rsi_val = self._cached_rsi[current_index]
        if rsi_val is not None and rsi_val >= self._rsi_overbought_exit:
            return True, f"RSI Overbought (RSI {rsi_val:.1f} >= {self._rsi_overbought_exit:.1f})"

        return False, ""
