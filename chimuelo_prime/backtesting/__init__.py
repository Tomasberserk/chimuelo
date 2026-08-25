"""Módulo de Backtesting Engine (M6).

Permite realizar simulaciones offline de la estrategia de grid trading sobre datos
históricos públicos de Binance, respetando la pureza Decimal y la máquina de estados.
"""

from __future__ import annotations

from chimuelo_prime.backtesting.data_loader import HistoricalCandle, HistoricalDataLoader
from chimuelo_prime.backtesting.engine import BacktestReport, BacktestSimulator
from chimuelo_prime.backtesting.metrics import (
    calculate_calmar_ratio,
    calculate_max_drawdown,
    calculate_profit_factor,
    calculate_sortino_ratio,
    calculate_total_return,
)
from chimuelo_prime.backtesting.reporter import BacktestReporter, SignalBacktestReporter
from chimuelo_prime.backtesting.strategy_engine import (
    SignalBacktestReport,
    SignalStrategyBacktester,
    StrategyEquityPoint,
    TradeExecutionRecord,
)

__all__ = [
    "HistoricalCandle",
    "HistoricalDataLoader",
    "BacktestSimulator",
    "BacktestReport",
    "SignalStrategyBacktester",
    "SignalBacktestReport",
    "SignalBacktestReporter",
    "StrategyEquityPoint",
    "TradeExecutionRecord",
    "calculate_total_return",
    "calculate_max_drawdown",
    "calculate_profit_factor",
    "calculate_sortino_ratio",
    "calculate_calmar_ratio",
    "BacktestReporter",
]
