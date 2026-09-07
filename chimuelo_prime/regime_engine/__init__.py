"""Chimuelo Prime — Regime Engine & Strategy Router Module.

Proporciona la arquitectura cuantitativa multi-motor desacoplada en cuatro capas:
1. Feature Engine (Cálculo causal y sincronización temporal estricta).
2. Regime Engine (Clasificación de estado de mercado en 5 dimensiones).
3. Strategy Router (Gestión de estados ARMED/ACTIVE/COOLDOWN con histéresis).
4. Portfolio Risk Allocator (Control de exposición y correlation gate).
"""

from chimuelo_prime.regime_engine.config import RegimeEngineConfig
from chimuelo_prime.regime_engine.models import (
    AlphaMotorId,
    DerivativesRegime,
    DirectionalScore,
    ForensicDecisionLog,
    MarketStateVector,
    NoTradeReasonCode,
    ParticipationRegime,
    RegimeTransition,
    RouterEvaluationResult,
    RouterStrategyState,
    ScoreComponentBreakdown,
    StrategyEvaluationLog,
    StructureRegime,
    TradeCandidate,
    TradeDirection,
    TrendRegime,
    VolatilityRegime,
)
from chimuelo_prime.regime_engine.regime_engine import QuantitativeRegimeEngine
from chimuelo_prime.regime_engine.router import StrategyRouter
from chimuelo_prime.regime_engine.router_config import RouterConfig
from chimuelo_prime.regime_engine.scoring import StrategyCompatibilityScorer

__all__ = [
    "AlphaMotorId",
    "DerivativesRegime",
    "DirectionalScore",
    "ForensicDecisionLog",
    "MarketStateVector",
    "NoTradeReasonCode",
    "ParticipationRegime",
    "QuantitativeRegimeEngine",
    "RegimeEngineConfig",
    "RegimeTransition",
    "RouterConfig",
    "RouterEvaluationResult",
    "RouterStrategyState",
    "ScoreComponentBreakdown",
    "StrategyCompatibilityScorer",
    "StrategyEvaluationLog",
    "StrategyRouter",
    "StructureRegime",
    "TradeCandidate",
    "TradeDirection",
    "TrendRegime",
    "VolatilityRegime",
]

