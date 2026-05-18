"""Excepciones tipificadas del módulo grid_state (M3).

Jerarquía:
    ChimueloException (M1 — raíz del proyecto)
    └── GridStateError              # Raíz de errores de M3
        ├── DatabaseError           # Fallo irrecuperable de SQLite
        ├── OrderNotFoundError      # Orden no existe en DB local
        ├── GridLevelNotFoundError  # Nivel de grid no existe en DB local
        └── ReconciliationError     # Fallo durante reconciliación con Binance
"""

from chimuelo_prime.exchange_config.exceptions import ChimueloException


class GridStateError(ChimueloException):
    """Raíz de errores del módulo grid_state (M3)."""


class DatabaseError(GridStateError):
    """Error irrecuperable de la base de datos SQLite.

    Se lanza cuando la DB no puede inicializarse, está corrupta
    o produce un error que no se puede recuperar en runtime.
    """


class OrderNotFoundError(GridStateError):
    """La orden solicitada no existe en la base de datos local.

    Args:
        order_id: Binance order ID que no se encontró.
    """


class GridLevelNotFoundError(GridStateError):
    """El nivel de grid solicitado no existe en la base de datos local.

    Args:
        level_id: ID del nivel que no se encontró.
    """


class ReconciliationError(GridStateError):
    """Error durante la reconciliación con Binance.

    Se lanza cuando la API de Binance retorna un error inesperado
    al consultar el estado de órdenes durante la reconciliación.
    """
