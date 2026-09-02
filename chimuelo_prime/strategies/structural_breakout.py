"""Estrategia Canónica Strategy C: Structural Breakout (v1.0.0-frozen).

Implementación estricta y determinista de los 9 gates canónicos pre-registrados.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.paper_trading.decision_models import (
    FilterEvaluationSnapshot,
    ensure_utc_aware,
)
from chimuelo_prime.strategies.base import BaseStrategy
from chimuelo_prime.strategies.indicators import calculate_atr, calculate_ema
from chimuelo_prime.strategies.models import SignalType, TradeSignal


class StructuralBreakoutStrategy(BaseStrategy):
    """Strategy C canónica (v1.0.0-frozen) para temporalidad 1h en BTC y SOL."""

    VERSION: str = "v1.0.0-frozen"

    # Parámetros congelados inmutables
    LOOKBACK_RESISTANCE: int = 20
    EMA_TREND_PERIOD: int = 100
    ATR_PERIOD: int = 14
    VOLUME_SMA_PERIOD: int = 20
    VOLUME_SMA_MULT: Decimal = Decimal("1.20")
    VOLUME_P70_WINDOW: int = 100
    VOLUME_P70_PERCENTILE: float = 0.70
    RANGE_SPAN_ATR_MULT: Decimal = Decimal("4.0")
    CLOSE_POSITION_RATIO: Decimal = Decimal("0.65")
    TAKE_PROFIT_RATIO: Decimal = Decimal("2.20")
    STOP_LOSS_ATR_MULT: Decimal = Decimal("0.50")
    STOP_LOSS_RES_MULT: Decimal = Decimal("1.00")
    MAX_SL_PCT: Decimal = Decimal("0.08")

    def __init__(
        self,
        symbol: str = "SOLUSDT",
        btc_daily_candles: list[HistoricalCandle] | None = None,
    ) -> None:
        self._name = f"StructuralBreakout_{symbol}"
        self._symbol = symbol
        self._btc_daily_map: dict[date, tuple[Decimal, Decimal, bool]] = {}

        if btc_daily_candles:
            self.set_btc_daily_context(btc_daily_candles)

        self._cached_ema_trend: list[Decimal | None] = []
        self._cached_atr: list[Decimal | None] = []
        self._cached_vol_sma: list[Decimal | None] = []

    @classmethod
    def get_config_hash(cls) -> str:
        """Retorna el hash SHA-256 inmutable de las reglas congeladas."""
        config_dict = {
            "version": cls.VERSION,
            "lookback": cls.LOOKBACK_RESISTANCE,
            "ema_trend": cls.EMA_TREND_PERIOD,
            "atr_period": cls.ATR_PERIOD,
            "vol_sma_mult": str(cls.VOLUME_SMA_MULT),
            "vol_p70_window": cls.VOLUME_P70_WINDOW,
            "vol_p70_pct": cls.VOLUME_P70_PERCENTILE,
            "range_atr_mult": str(cls.RANGE_SPAN_ATR_MULT),
            "close_pos_ratio": str(cls.CLOSE_POSITION_RATIO),
            "tp_ratio": str(cls.TAKE_PROFIT_RATIO),
            "max_sl_pct": str(cls.MAX_SL_PCT),
        }
        raw_bytes = json.dumps(config_dict, sort_keys=True).encode("utf-8")
        return hashlib.sha256(raw_bytes).hexdigest()

    @property
    def name(self) -> str:
        return self._name

    def set_btc_daily_context(self, btc_daily_candles: list[HistoricalCandle]) -> None:
        """Construye el mapa de régimen de BTC en velas diarias cerradas (D-1).

        Garantiza estrictamente CERO look-ahead diario: sólo indexa días que ya han cerrado.
        """
        sorted_daily = sorted(btc_daily_candles, key=lambda c: c.timestamp)
        closes = [c.close for c in sorted_daily]
        ema50_vals = calculate_ema(closes, 50)

        daily_map: dict[date, tuple[Decimal, Decimal, bool]] = {}
        for i, candle in enumerate(sorted_daily):
            ema_val = ema50_vals[i]
            d_date = candle.timestamp.date()
            if ema_val is not None:
                is_bullish = candle.close > ema_val
                daily_map[d_date] = (candle.close, ema_val, is_bullish)
            else:
                daily_map[d_date] = (candle.close, candle.close, False)

        self._btc_daily_map = daily_map

    def prepare_indicators(self, candles: list[HistoricalCandle]) -> None:
        """Pre-calcula series de indicadores para optimizar evaluación."""
        closes = [c.close for c in candles]
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        volumes = [c.volume for c in candles]

        self._cached_ema_trend = calculate_ema(closes, self.EMA_TREND_PERIOD)
        self._cached_atr = calculate_atr(highs, lows, closes, self.ATR_PERIOD)

        vol_smas: list[Decimal | None] = []
        for i in range(len(volumes)):
            if i < self.VOLUME_SMA_PERIOD:
                vol_smas.append(None)
            else:
                window = volumes[i - self.VOLUME_SMA_PERIOD : i]
                vol_smas.append(sum(window) / Decimal(str(self.VOLUME_SMA_PERIOD)))
        self._cached_vol_sma = vol_smas

    def evaluate_gates(
        self, candles: list[HistoricalCandle], idx: int
    ) -> tuple[FilterEvaluationSnapshot, TradeSignal | None]:
        """Evalúa los 9 gates canónicos sobre la barra idx."""
        if not self._cached_ema_trend or len(self._cached_ema_trend) != len(candles):
            self.prepare_indicators(candles)

        if idx < max(self.LOOKBACK_RESISTANCE + 5, self.VOLUME_P70_WINDOW):
            raise ValueError(f"Índice {idx} insuficiente para ventana histórica requerida (mínimo 100 barras)")

        candle = candles[idx]
        ensure_utc_aware(candle.timestamp)

        ema_trend = self._cached_ema_trend[idx] or Decimal("0")
        atr_val = self._cached_atr[idx] or Decimal("0")
        vol_sma = self._cached_vol_sma[idx] or Decimal("0")

        # -------------------------------------------------------------
        # Gate 1: Trend base (Close > EMA100)
        # -------------------------------------------------------------
        gate1_passed = bool(ema_trend > Decimal("0") and candle.close > ema_trend)

        # -------------------------------------------------------------
        # Gate 2: Breakout 20-bar resistance (excluyendo vela actual)
        # -------------------------------------------------------------
        past_res_window = candles[idx - self.LOOKBACK_RESISTANCE : idx]
        past_resistance = max(c.high for c in past_res_window)
        gate2_passed = bool(candle.close > past_resistance)

        # -------------------------------------------------------------
        # Gate 3: Close in upper 35% of candle range (ratio >= 0.65)
        # -------------------------------------------------------------
        candle_range = candle.high - candle.low
        close_pos_ratio = (candle.close - candle.low) / candle_range if candle_range > Decimal("0") else Decimal("0")
        gate3_passed = bool(candle_range > Decimal("0") and close_pos_ratio >= self.CLOSE_POSITION_RATIO)

        # -------------------------------------------------------------
        # Gate 4: Volume expansion immediate (Volume >= 1.20x SMA20)
        # -------------------------------------------------------------
        gate4_passed = bool(vol_sma > Decimal("0") and candle.volume >= (vol_sma * self.VOLUME_SMA_MULT))

        # -------------------------------------------------------------
        # Gate 5: BTC Daily macro regime (BTC Close[D-1] > BTC EMA50[D-1])
        # -------------------------------------------------------------
        # Estrictamente el día anterior D-1
        prev_day_date = candle.timestamp.date() - timedelta(days=1)
        btc_daily_info = self._btc_daily_map.get(prev_day_date)
        if btc_daily_info:
            btc_close_prev, btc_ema50_prev, btc_macro_bullish = btc_daily_info
        else:
            btc_close_prev, btc_ema50_prev, btc_macro_bullish = Decimal("0"), Decimal("0"), False
        gate5_passed = bool(btc_macro_bullish)

        # -------------------------------------------------------------
        # Gate 6: Extreme Relative Volume (Volume >= P70 of last 100 bars)
        # -------------------------------------------------------------
        past_100_vols = sorted([c.volume for c in candles[idx - self.VOLUME_P70_WINDOW : idx]])
        vol_p70_threshold = past_100_vols[int(len(past_100_vols) * self.VOLUME_P70_PERCENTILE)]
        gate6_passed = bool(candle.volume >= vol_p70_threshold)

        # -------------------------------------------------------------
        # Gate 7: Range maturity (Range 20 bars >= 4.0x ATR14)
        # -------------------------------------------------------------
        past_min_low = min(c.low for c in past_res_window)
        range_span = past_resistance - past_min_low
        range_atr_ratio = range_span / atr_val if atr_val > Decimal("0") else Decimal("0")
        gate7_passed = bool(atr_val > Decimal("0") and range_span >= (atr_val * self.RANGE_SPAN_ATR_MULT))

        all_gates = bool(
            gate1_passed
            and gate2_passed
            and gate3_passed
            and gate4_passed
            and gate5_passed
            and gate6_passed
            and gate7_passed
        )

        filters_snapshot = FilterEvaluationSnapshot(
            price_above_ema100=gate1_passed,
            ema100_val=ema_trend,
            breakout_20_high=gate2_passed,
            resistance_val=past_resistance,
            close_position_ratio=close_pos_ratio,
            close_position_passed=gate3_passed,
            volume_sma20_val=vol_sma,
            volume_sma20_passed=gate4_passed,
            btc_daily_date_prev=str(prev_day_date),
            btc_daily_close_prev=btc_close_prev,
            btc_daily_ema50_prev=btc_ema50_prev,
            btc_macro_bullish=gate5_passed,
            volume_p70_threshold=vol_p70_threshold,
            volume_p70_passed=gate6_passed,
            range_span_val=range_span,
            atr14_val=atr_val,
            range_atr_ratio=range_atr_ratio,
            range_filter_passed=gate7_passed,
            all_gates_passed=all_gates,
        )

        signal: TradeSignal | None = None
        if all_gates:
            entry_price = candle.close
            stop_loss = max(
                candle.low - (atr_val * self.STOP_LOSS_ATR_MULT),
                past_resistance - (atr_val * self.STOP_LOSS_RES_MULT),
            )
            sl_distance = entry_price - stop_loss
            if sl_distance > Decimal("0") and (sl_distance / entry_price) <= self.MAX_SL_PCT:
                take_profit = entry_price + (sl_distance * self.TAKE_PROFIT_RATIO)
                signal = TradeSignal(
                    timestamp=candle.timestamp,
                    symbol=self._symbol,
                    signal_type=SignalType.BUY,
                    price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    reason=f"Canonical Strategy C ({self.VERSION})",
                )

        return filters_snapshot, signal

    def evaluate_candle(self, candles: list[HistoricalCandle], idx: int) -> TradeSignal | None:
        """Compatibilidad con interfaz BaseStrategy."""
        if idx < max(self.LOOKBACK_RESISTANCE + 5, self.VOLUME_P70_WINDOW):
            return None
        _, signal = self.evaluate_gates(candles, idx)
        return signal

    def calculate_position_size(
        self,
        account_equity: Decimal,
        entry_price: Decimal,
        stop_loss_price: Decimal,
        min_notional: Decimal = Decimal("5.0"),
        risk_pct: Decimal = Decimal("0.025"),
    ) -> Decimal:
        """Calcula el tamaño de posición arriesgando exactamente risk_pct del capital."""
        if account_equity <= Decimal("0") or entry_price <= Decimal("0"):
            return Decimal("0")
        sl_dist = abs(entry_price - stop_loss_price)
        if sl_dist <= Decimal("0"):
            return Decimal("0")
        risk_usd = account_equity * risk_pct
        qty = risk_usd / sl_dist
        if (qty * entry_price) < min_notional:
            qty = min_notional / entry_price
        max_q = account_equity / entry_price
        return min(qty, max_q).quantize(Decimal("0.00000001"))
