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

        # 1. Filtro de Tendencia: Precio actual por encima de la EMA 200
        if candle.close <= ema_trend:
            return None

        # 2. Filtro de Volumen: Volumen reciente debe ser respetable
        if candle.volume < (vol_sma * self._vol_mult):
            return None

        # 3. Detección de Divergencia Alcista en RSI dentro de la ventana de lookback
        # Buscamos un mínimo previo en precio y RSI
        divergence_found, prev_price, prev_rsi = self._check_bullish_divergence(
            candles, current_index
        )
        if not divergence_found:
            return None

        # 4. Gatillo de Confirmación: Cierre alcista (close > open) y superando EMA rápida
        if candle.close <= candle.open or candle.close <= ema_fast:
            return None

        # 5. Cálculo Dinámico de Stop Loss y Take Profit basado en ATR
        entry_price = candle.close
        sl_distance = atr_val * self._atr_sl_mult
        stop_loss = entry_price - sl_distance

        # Protección: Stop Loss no puede ser menor o igual a cero ni demasiado distante (> 8%)
        if stop_loss <= Decimal("0") or (sl_distance / entry_price) > Decimal("0.08"):
            return None

        take_profit = entry_price + (sl_distance * self._rr_ratio)

        metadata: dict[str, Any] = {
            "rsi_current": str(rsi_val),
            "rsi_prev": str(prev_rsi),
            "ema_trend": str(ema_trend),
            "ema_fast": str(ema_fast),
            "atr": str(atr_val),
            "sl_distance_pct": str(
                ((sl_distance / entry_price) * Decimal("100")).quantize(Decimal("0.01"))
            ),
            "rr_ratio": str(self._rr_ratio),
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
            reason=f"Bullish RSI Divergence (RSI: {rsi_val:.1f} vs {prev_rsi:.1f}) + Trend > EMA{self._ema_trend_period}",
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
