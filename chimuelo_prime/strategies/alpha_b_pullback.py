"""Motor de Alpha B: Deep Pullback en Tendencia (Fase 4 Baseline v0.1).

Implementa la detección causal de retrocesos profundos hacia medias móviles
en regímenes de tendencia favorable validados por el Strategy Router.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.regime_engine.models import (
    AlphaMotorId,
    MarketStateVector,
    RouterEvaluationResult,
    RouterStrategyState,
    TradeCandidate,
    TradeDirection,
    TrendRegime,
)


class DeepPullbackAlphaMotor:
    """Motor de Alpha B (Deep Pullback) con soporte condicionado (Router) y no-condicionado."""

    def __init__(self, risk_reward_ratio: Decimal = Decimal("2.0")) -> None:
        self.strategy_id = AlphaMotorId.ALPHA_B
        self.rr_ratio = risk_reward_ratio

    def evaluate_candidate(
        self,
        symbol: str,
        candles: Sequence[HistoricalCandle],
        current_idx: int,
        market_state: MarketStateVector,
        ema20: Sequence[Decimal | None],
        ema50: Sequence[Decimal | None],
        atr20: Sequence[Decimal | None],
        router_result: RouterEvaluationResult | None = None,
        unconditioned: bool = False,
    ) -> TradeCandidate | None:
        """Evalúa causalmente si la vela en current_idx confirma un gatillo de Deep Pullback."""
        if current_idx < 3:
            return None

        # 1. Comprobación de autorización del Router (si no es modo unconditioned)
        if not unconditioned:
            if router_result is None:
                return None
            strat_log = router_result.strategy_evaluations.get(self.strategy_id)
            if strat_log is None or strat_log.state_after != RouterStrategyState.ARMED:
                return None
            if not strat_log.authorized_for_trigger:
                return None

        c_now = candles[current_idx]
        e20 = ema20[current_idx]
        e50 = ema50[current_idx]
        atr = atr20[current_idx]

        if e20 is None or e50 is None or atr is None or atr <= Decimal("0.0"):
            return None

        atr_buffer = atr * Decimal("0.3")

        # 2. Evaluación de Gatillo LONG (Pullback en Tendencia Alcista)
        is_bull_trend = market_state.trend in (TrendRegime.BULL, TrendRegime.STRONG_BULL)
        if is_bull_trend:
            # El precio penetra hacia EMA20/EMA50 pero no se destruye por debajo de EMA50
            pullback_reached = c_now.low <= (e20 + atr_buffer)
            held_support = c_now.close >= (e50 - atr_buffer)
            candle_range = c_now.high - c_now.low

            # Confirmación de rechazo alcista (cierre en mitad superior o vela verde)
            bullish_rejection = (
                candle_range > Decimal("0.0")
                and ((c_now.close - c_now.low) >= (candle_range * Decimal("0.50")))
                and (c_now.close >= c_now.open)
            )

            if pullback_reached and held_support and bullish_rejection:
                # Stop Loss en el swing low reciente (últimas 3 barras) - 0.3 ATR
                recent_lows = [candles[i].low for i in range(current_idx - 2, current_idx + 1)]
                swing_low = min(recent_lows)
                stop_loss = swing_low - atr_buffer

                risk_distance = c_now.close - stop_loss
                if risk_distance < (atr * Decimal("0.50")):
                    risk_distance = atr * Decimal("0.50")
                    stop_loss = c_now.close - risk_distance

                take_profit = c_now.close + (risk_distance * self.rr_ratio)

                return TradeCandidate(
                    candidate_id=f"B_LONG_{symbol}_{c_now.timestamp.strftime('%Y%m%d%H%M')}",
                    strategy_id=self.strategy_id,
                    symbol=symbol,
                    direction=TradeDirection.LONG,
                    entry_price=c_now.close,  # Nota: la ejecución real se realiza en Open_{t+1}
                    stop_loss=round(stop_loss, 4),
                    take_profit=round(take_profit, 4),
                    confidence_score=market_state.slope_50,
                    timestamp=c_now.timestamp,
                )

        # 3. Evaluación de Gatillo SHORT (Pullback en Tendencia Bajista)
        is_bear_trend = market_state.trend in (TrendRegime.BEAR, TrendRegime.STRONG_BEAR)
        if is_bear_trend:
            pullback_reached = c_now.high >= (e20 - atr_buffer)
            held_resistance = c_now.close <= (e50 + atr_buffer)
            candle_range = c_now.high - c_now.low

            bearish_rejection = (
                candle_range > Decimal("0.0")
                and ((c_now.high - c_now.close) >= (candle_range * Decimal("0.50")))
                and (c_now.close <= c_now.open)
            )

            if pullback_reached and held_resistance and bearish_rejection:
                recent_highs = [candles[i].high for i in range(current_idx - 2, current_idx + 1)]
                swing_high = max(recent_highs)
                stop_loss = swing_high + atr_buffer

                risk_distance = stop_loss - c_now.close
                if risk_distance < (atr * Decimal("0.50")):
                    risk_distance = atr * Decimal("0.50")
                    stop_loss = c_now.close + risk_distance

                take_profit = c_now.close - (risk_distance * self.rr_ratio)

                return TradeCandidate(
                    candidate_id=f"B_SHORT_{symbol}_{c_now.timestamp.strftime('%Y%m%d%H%M')}",
                    strategy_id=self.strategy_id,
                    symbol=symbol,
                    direction=TradeDirection.SHORT,
                    entry_price=c_now.close,
                    stop_loss=round(stop_loss, 4),
                    take_profit=round(take_profit, 4),
                    confidence_score=abs(market_state.slope_50),
                    timestamp=c_now.timestamp,
                )

        return None
