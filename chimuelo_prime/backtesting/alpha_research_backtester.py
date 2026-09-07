"""Motor de Backtesting Causal de Investigación de Alpha Motors (Fase 4 Baseline v0.1).

Implementa la ejecución rigurosa bajo los 6 guardrails metodológicos obligatorios:
- Entrada estrictamente al Open_{t+1} con fricción (slippage + fees).
- Política de ambigüedad OHLC: Stop-First conservador.
- Fricción realista: 5 bps comisión taker + 5 bps slippage por lado (20 bps round trip).
- Resampleo Bootstrap IID (B=1,000) sobre trades cerrados para intervalos de confianza al 95%.
- Contabilidad forense completa: Gross -> Fees -> Slippage -> Net -> R-multiple.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.regime_engine.models import (
    AlphaMotorId,
    TradeCandidate,
    TradeDirection,
)


@dataclass(frozen=True)
class ResearchTradeOutcome:
    """Registro determinista de un trade cerrado durante el backtest de investigación."""

    candidate_id: str
    strategy_id: AlphaMotorId
    symbol: str
    direction: TradeDirection
    entry_idx: int
    exit_idx: int
    entry_time: datetime
    exit_time: datetime
    duration_bars: int
    nominal_entry: Decimal
    executed_entry: Decimal
    nominal_exit: Decimal
    executed_exit: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    risk_unit: Decimal
    gross_return_pct: Decimal
    total_friction_pct: Decimal
    net_return_pct: Decimal
    net_r_multiple: Decimal
    exit_reason: str  # "STOP_LOSS", "TAKE_PROFIT", "END_OF_DATA"


class AlphaResearchBacktester:
    """Simulador causal de ejecución con fricción y resolución conservadora Stop-First."""

    def __init__(
        self,
        fee_rate_per_side: Decimal = Decimal("0.0005"),  # 5 bps taker
        slippage_per_side: Decimal = Decimal("0.0005"),  # 5 bps slippage
        ohlc_ambiguity_policy: str = "stop_first",       # "stop_first" o "target_first"
    ) -> None:
        self.fee_rate = fee_rate_per_side
        self.slippage = slippage_per_side
        self.policy = ohlc_ambiguity_policy

    def simulate_trades(
        self,
        candidates: Sequence[tuple[int, TradeCandidate]],  # (signal_idx, candidate)
        candles: Sequence[HistoricalCandle],
    ) -> list[ResearchTradeOutcome]:
        """Simula secuencialmente los trades generados con entrada al Open_{t+1}."""
        trades: list[ResearchTradeOutcome] = []
        n_bars = len(candles)

        for sig_idx, cand in candidates:
            entry_idx = sig_idx + 1
            if entry_idx >= n_bars:
                continue

            c_entry = candles[entry_idx]
            raw_open = c_entry.open

            # Ejecución al Open_{t+1} con slippage y comisión
            if cand.direction == TradeDirection.LONG:
                exec_entry = raw_open * (Decimal("1.0") + self.slippage)
                entry_fee_pct = self.fee_rate * Decimal("100.0")
            else:
                exec_entry = raw_open * (Decimal("1.0") - self.slippage)
                entry_fee_pct = self.fee_rate * Decimal("100.0")

            sl = cand.stop_loss
            tp = cand.take_profit
            risk_unit = abs(exec_entry - sl)
            if risk_unit <= Decimal("0.0001"):
                risk_unit = exec_entry * Decimal("0.01")  # Fallback 1% si risk es nulo

            exit_idx = n_bars - 1
            exit_price = candles[-1].close
            exit_reason = "END_OF_DATA"

            # Simulación intrabarra a partir de la barra de entrada entry_idx
            for bar_idx in range(entry_idx, n_bars):
                cb = candles[bar_idx]

                if cand.direction == TradeDirection.LONG:
                    hit_sl = cb.low <= sl
                    hit_tp = cb.high >= tp

                    if hit_sl and hit_tp:
                        # Ambigüedad OHLC: Política Stop-First conservadora
                        if self.policy == "stop_first":
                            exit_idx = bar_idx
                            exit_price = sl
                            exit_reason = "STOP_LOSS"
                            break
                        else:
                            exit_idx = bar_idx
                            exit_price = tp
                            exit_reason = "TAKE_PROFIT"
                            break
                    elif hit_sl:
                        exit_idx = bar_idx
                        exit_price = sl
                        exit_reason = "STOP_LOSS"
                        break
                    elif hit_tp:
                        exit_idx = bar_idx
                        exit_price = tp
                        exit_reason = "TAKE_PROFIT"
                        break

                else:  # SHORT
                    hit_sl = cb.high >= sl
                    hit_tp = cb.low <= tp

                    if hit_sl and hit_tp:
                        if self.policy == "stop_first":
                            exit_idx = bar_idx
                            exit_price = sl
                            exit_reason = "STOP_LOSS"
                            break
                        else:
                            exit_idx = bar_idx
                            exit_price = tp
                            exit_reason = "TAKE_PROFIT"
                            break
                    elif hit_sl:
                        exit_idx = bar_idx
                        exit_price = sl
                        exit_reason = "STOP_LOSS"
                        break
                    elif hit_tp:
                        exit_idx = bar_idx
                        exit_price = tp
                        exit_reason = "TAKE_PROFIT"
                        break

            # Ejecución de Salida con slippage y comisión
            if cand.direction == TradeDirection.LONG:
                exec_exit = exit_price * (Decimal("1.0") - self.slippage)
                exit_fee_pct = self.fee_rate * Decimal("100.0")
                gross_pct = (exit_price - raw_open) / raw_open * Decimal("100.0")
                net_pct = (exec_exit - exec_entry) / exec_entry * Decimal("100.0") - (entry_fee_pct + exit_fee_pct)
            else:
                exec_exit = exit_price * (Decimal("1.0") + self.slippage)
                exit_fee_pct = self.fee_rate * Decimal("100.0")
                gross_pct = (raw_open - exit_price) / raw_open * Decimal("100.0")
                net_pct = (exec_entry - exec_exit) / exec_entry * Decimal("100.0") - (entry_fee_pct + exit_fee_pct)

            total_friction = gross_pct - net_pct
            risk_pct = (risk_unit / exec_entry) * Decimal("100.0")
            net_r = net_pct / risk_pct if risk_pct > Decimal("0.0001") else Decimal("0.0")

            c_exit = candles[exit_idx]
            duration = exit_idx - entry_idx + 1

            trades.append(
                ResearchTradeOutcome(
                    candidate_id=cand.candidate_id,
                    strategy_id=cand.strategy_id,
                    symbol=cand.symbol,
                    direction=cand.direction,
                    entry_idx=entry_idx,
                    exit_idx=exit_idx,
                    entry_time=c_entry.timestamp,
                    exit_time=c_exit.timestamp,
                    duration_bars=duration,
                    nominal_entry=round(raw_open, 4),
                    executed_entry=round(exec_entry, 4),
                    nominal_exit=round(exit_price, 4),
                    executed_exit=round(exec_exit, 4),
                    stop_loss=round(sl, 4),
                    take_profit=round(tp, 4),
                    risk_unit=round(risk_unit, 4),
                    gross_return_pct=round(gross_pct, 4),
                    total_friction_pct=round(total_friction, 4),
                    net_return_pct=round(net_pct, 4),
                    net_r_multiple=round(net_r, 4),
                    exit_reason=exit_reason,
                )
            )

        return trades


def run_bootstrap_analysis(
    trades: Sequence[ResearchTradeOutcome],
    iterations: int = 1000,
    alpha: float = 0.05,
    seed: int = 42,
) -> dict[str, Any]:
    """Ejecuta remuestreo Bootstrap IID sobre los trades cerrados para intervalos de confianza."""
    n = len(trades)
    if n == 0:
        return {
            "n_trades": 0,
            "mean_r": 0.0,
            "ci_95_lower": 0.0,
            "ci_95_upper": 0.0,
            "win_rate_pct": 0.0,
            "win_rate_ci_lower": 0.0,
            "win_rate_ci_upper": 0.0,
            "profit_factor": 0.0,
            "autocorrelation_lag1": 0.0,
        }

    random.seed(seed)
    r_multiples = [float(t.net_r_multiple) for t in trades]

    # Cálculo de métricas observadas
    mean_obs = sum(r_multiples) / n
    wins_obs = sum(1 for r in r_multiples if r > 0)
    win_rate_obs = (wins_obs / n) * 100.0

    gains = sum(r for r in r_multiples if r > 0)
    losses = abs(sum(r for r in r_multiples if r < 0))
    pf_obs = round(gains / losses, 2) if losses > 0.0001 else (99.0 if gains > 0 else 0.0)

    # Autocorrelación de retornos lag-1
    autocorr = 0.0
    if n > 2:
        mean_r = mean_obs
        denom = sum((x - mean_r) ** 2 for x in r_multiples)
        if denom > 0:
            num = sum((r_multiples[i] - mean_r) * (r_multiples[i - 1] - mean_r) for i in range(1, n))
            autocorr = round(num / denom, 3)

    # Remuestreo con reemplazo B veces
    boot_means: list[float] = []
    boot_win_rates: list[float] = []

    for _ in range(iterations):
        sample = [random.choice(r_multiples) for _ in range(n)]
        s_mean = sum(sample) / n
        s_win = (sum(1 for x in sample if x > 0) / n) * 100.0
        boot_means.append(s_mean)
        boot_win_rates.append(s_win)

    boot_means.sort()
    boot_win_rates.sort()

    lower_idx = int((alpha / 2.0) * iterations)
    upper_idx = int((1.0 - (alpha / 2.0)) * iterations)

    ci_mean_lower = boot_means[lower_idx]
    ci_mean_upper = boot_means[upper_idx]
    ci_win_lower = boot_win_rates[lower_idx]
    ci_win_upper = boot_win_rates[upper_idx]

    return {
        "n_trades": n,
        "mean_r": round(mean_obs, 3),
        "ci_95_lower": round(ci_mean_lower, 3),
        "ci_95_upper": round(ci_mean_upper, 3),
        "win_rate_pct": round(win_rate_obs, 2),
        "win_rate_ci_lower": round(ci_win_lower, 2),
        "win_rate_ci_upper": round(ci_win_upper, 2),
        "profit_factor": pf_obs,
        "autocorrelation_lag1": autocorr,
    }
