"""Chimuelo Prime — Regime Engine & Strategy Router Module.

Proporciona la arquitectura cuantitativa multi-motor desacoplada en cuatro capas:
1. Feature Engine (Cálculo causal y sincronización temporal estricta).
2. Regime Engine (Clasificación de estado de mercado en 5 dimensiones).
3. Strategy Router (Gestión de estados ARMED/ACTIVE/COOLDOWN con histéresis).
4. Portfolio Risk Allocator (Control de exposición y correlation gate).
"""

from chimuelo_prime.regime_engine.models import (
    DerivativesRegime,
    MarketStateVector,
    ParticipationRegime,
    RegimeTransition,
    RouterStrategyState,
    StructureRegime,
    TrendRegime,
    VolatilityRegime,
)

__all__ = [
    "TrendRegime",
    "VolatilityRegime",
    "StructureRegime",
    "ParticipationRegime",
    "DerivativesRegime",
    "RouterStrategyState",
    "MarketStateVector",
    "RegimeTransition",
]
