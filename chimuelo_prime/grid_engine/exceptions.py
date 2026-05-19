"""Excepciones tipificadas del módulo grid_engine (M5).

Jerarquía:
    ChimueloException (M1 — raíz del proyecto)
    └── GridEngineError
        ├── GridInitializationError  # fallo irrecuperable al inicializar el grid
        ├── GridCalculationError     # geometría del grid inválida con los parámetros dados
        ├── PriceFetchError          # no se pudo obtener el precio spot actual
        └── GridResumeError          # fallo durante reanudación post-reconciliación

Regla: M7 captura por tipo específico. Nunca `except Exception` genérico en producción.
"""

from __future__ import annotations

from chimuelo_prime.exchange_config.exceptions import ChimueloException


class GridEngineError(ChimueloException):
    """Raíz de todas las excepciones de M5."""


class GridInitializationError(GridEngineError):
    """Fallo irrecuperable durante la inicialización del grid.

    Si se lanza, el bot no debe entrar al loop de operación.
    Causas típicas: FilterViolationError propagada desde M4, o geometría inválida.
    """


class GridCalculationError(GridEngineError):
    """Los parámetros de config producen un grid geométricamente inválido.

    Causas típicas:
    - capital_per_order insuficiente para que qty >= min_qty en algún nivel.
    - notional (precio × qty) < min_notional en algún nivel.
    Si se lanza en GridCalculator.compute_levels, el bot no debe arrancar.
    """


class PriceFetchError(GridEngineError):
    """No se pudo obtener el precio spot actual del símbolo.

    Causas típicas: respuesta malformada de Binance (clave 'price' ausente
    o valor no convertible a Decimal).
    BinanceAPIError se propaga sin envolver si el endpoint retorna error HTTP.
    """


class GridResumeError(GridEngineError):
    """Fallo irrecuperable durante la reanudación post-reconciliación.

    Si se lanza, el bot no debe entrar al loop de operación.
    """
