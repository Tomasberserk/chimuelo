"""Exports públicos del módulo grid_engine (M5).

API pública:
    GridEngine    — motor de grid trading (ciclo de vida completo).

Modelos de cálculo (no ORM):
    LevelSpec     — especificación inmutable de un nivel del grid.

Excepciones:
    GridEngineError        — raíz de errores de M5.
    GridInitializationError — fallo irrecuperable al inicializar.
    GridCalculationError   — geometría del grid inválida.
    PriceFetchError        — no se pudo obtener precio spot.
    GridResumeError        — fallo irrecuperable al reanudar.

NO se exporta GridCalculator ni PriceFetcher — son detalles de implementación.
Si M7 necesita LevelSpec para logging/reporting, se re-evalúa en esa etapa.
"""

from chimuelo_prime.grid_engine.calculator import LevelSpec
from chimuelo_prime.grid_engine.exceptions import (
    GridCalculationError,
    GridEngineError,
    GridInitializationError,
    GridResumeError,
    PriceFetchError,
)

__all__ = [
    # Modelos de cálculo
    "LevelSpec",
    # Excepciones
    "GridEngineError",
    "GridInitializationError",
    "GridCalculationError",
    "PriceFetchError",
    "GridResumeError",
]
