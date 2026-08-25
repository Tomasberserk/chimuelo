"""Módulo de Estrategias y Señales Cuantitativas para Chimuelo Prime."""

from chimuelo_prime.strategies.base import BaseStrategy
from chimuelo_prime.strategies.models import Position, SignalType, TradeSignal
from chimuelo_prime.strategies.optimizer import (
    OptimizationParamGrid,
    OptimizationSummary,
    OptimizationTrialResult,
    StrategyParameterOptimizer,
)
from chimuelo_prime.strategies.rsi_divergence import RSIDivergenceStrategy
from chimuelo_prime.strategies.sentiment_models import (
    MacroRegime,
    MarketSentimentReport,
    SentimentCategory,
)
from chimuelo_prime.strategies.sentiment_service import MacroSentimentService

__all__ = [
    "BaseStrategy",
    "Position",
    "SignalType",
    "TradeSignal",
    "RSIDivergenceStrategy",
    "OptimizationParamGrid",
    "OptimizationTrialResult",
    "OptimizationSummary",
    "StrategyParameterOptimizer",
    "MacroRegime",
    "MarketSentimentReport",
    "SentimentCategory",
    "MacroSentimentService",
]
