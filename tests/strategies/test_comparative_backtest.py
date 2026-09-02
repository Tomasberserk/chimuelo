"""Test suite y ejecutor para el backtest cuantitativo comparativo TP Ciego vs TP Estructural 75%."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.backtesting.strategy_engine import SignalStrategyBacktester
from chimuelo_prime.strategies.rsi_divergence import RSIDivergenceStrategy
from run_comparative_backtest import run_comparative_suite


def test_comparative_backtest_execution() -> None:
    """Ejecuta el backtest cuantitativo comparativo sobre los datos reales cacheados."""
    results = run_comparative_suite()

    assert "comparisons" in results
    assert len(results["comparisons"]) > 0

    for comp in results["comparisons"]:
        assert "symbol" in comp
        assert "interval" in comp
        assert "blind_tp" in comp
        assert "structural_tp_75" in comp

        blind = comp["blind_tp"]
        struct = comp["structural_tp_75"]

        assert blind["win_rate_pct"] >= 0.0
        assert struct["win_rate_pct"] >= 0.0
        assert blind["max_drawdown_pct"] >= 0.0
        assert struct["max_drawdown_pct"] >= 0.0
