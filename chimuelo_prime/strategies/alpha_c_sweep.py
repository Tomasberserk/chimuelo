"""Motor de Alpha C: Liquidity Sweep en Rango (Fase 4 Baseline v0.1).

Implementa la detección causal de barridos de liquidez (sweeps) sobre soportes y
resistencias locales, calculados estrictamente sobre las 24 barras previas excluyendo
la vela actual t para evitar el desplazamiento de nivel.
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
    StructureRegime,
    TradeCandidate,
    TradeDirection,
)


class LiquiditySweepAlphaMotor:
    """Motor de Alpha C (Liquidity Sweep) con niveles históricos estrictos."""

    def __init__(self, lookback_bars: int = 24) -> None:
        self.strategy_id = AlphaMotorId.ALPHA_C
        self.lookback = lookback_bars

    def evaluate_candidate(
        self,
        symbol: str,
        candles: Sequence[HistoricalCandle],
        current_idx: int,
        market_state: MarketStateVector,
        ema20: Sequence[Decimal | None],
        atr20: Sequence[Decimal | None],
        router_result: RouterEvaluationResult | None = None,
        unconditioned: bool = False,
    ) -> TradeCandidate | None:
        """Evalúa causalmente si la vela en current_idx ejecuta un sweep de liquidez."""
        if current_idx < self.lookback:
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
        else:
            # En modo unconditioned, al menos verifica que no esté en tendencia direccional extrema
            if market_state.structure == StructureRegime.DIRECTIONAL:
                return None

        c_now = candles[current_idx]
        e20 = ema20[current_idx]
        atr = atr20[current_idx]

        if e20 is None or atr is None or atr <= Decimal("0.0"):
            return None

        # 2. CÁLCULO ESTRICTAMENTE HISTÓRICO: Excluye la vela actual current_idx (t)
        # High_prior = max(High_{t-24} .. High_{t-1})
        # Low_prior  = min(Low_{t-24} .. Low_{t-1})
        prior_window = candles[current_idx - self.lookback : current_idx]
        high_prior = max(c.high for c in prior_window)
        low_prior = min(c.low for c in prior_window)
        midpoint_prior = (high_prior + low_prior) / Decimal("2.0")

        atr_buffer = atr * Decimal("0.2")

        # 3. GATILLO LONG: Barrido del mínimo previo y recuperación (Close > Low_prior)
        # Low_t < Low_prior_24 AND Close_t > Low_prior_24
        is_long_sweep = (c_now.low < low_prior) and (c_now.close > low_prior)
        if is_long_sweep:
            stop_loss = c_now.low - atr_buffer
            risk_distance = c_now.close - stop_loss
            if risk_distance < (atr * Decimal("0.30")):
                risk_distance = atr * Decimal("0.30")
                stop_loss = c_now.close - risk_distance

            # Take Profit al midpoint del rango o EMA20 (lo que ofrezca al menos 1.2R)
            target_mid = max(midpoint_prior, e20)
            if target_mid <= c_now.close + risk_distance:
                target_mid = c_now.close + (risk_distance * Decimal("1.5"))

            return TradeCandidate(
                candidate_id=f"C_LONG_{symbol}_{c_now.timestamp.strftime('%Y%m%d%H%M')}",
                strategy_id=self.strategy_id,
                symbol=symbol,
                direction=TradeDirection.LONG,
                entry_price=c_now.close,  # Ejecución real en Open_{t+1}
                stop_loss=round(stop_loss, 4),
                take_profit=round(target_mid, 4),
                confidence_score=Decimal("1.0") - market_state.efficiency_ratio,
                timestamp=c_now.timestamp,
            )

        # 4. GATILLO SHORT: Barrido del máximo previo y rechazo (Close < High_prior)
        # High_t > High_prior_24 AND Close_t < High_prior_24
        is_short_sweep = (c_now.high > high_prior) and (c_now.close < high_prior)
        if is_short_sweep:
            stop_loss = c_now.high + atr_buffer
            risk_distance = stop_loss - c_now.close
            if risk_distance < (atr * Decimal("0.30")):
                risk_distance = atr * Decimal("0.30")
                stop_loss = c_now.close + risk_distance

            # Take Profit al midpoint del rango o EMA20
            target_mid = min(midpoint_prior, e20)
            if target_mid >= c_now.close - risk_distance:
                target_mid = c_now.close - (risk_distance * Decimal("1.5"))

            return TradeCandidate(
                candidate_id=f"C_SHORT_{symbol}_{c_now.timestamp.strftime('%Y%m%d%H%M')}",
                strategy_id=self.strategy_id,
                symbol=symbol,
                direction=TradeDirection.SHORT,
                entry_price=c_now.close,
                stop_loss=round(stop_loss, 4),
                take_profit=round(target_mid, 4),
                confidence_score=Decimal("1.0") - market_state.efficiency_ratio,
                timestamp=c_now.timestamp,
            )

        return None
