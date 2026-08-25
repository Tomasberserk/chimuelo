"""Cálculo de geometría del grid — funciones puras sin I/O (M5).

GridCalculator es el único lugar donde se define la distribución de niveles.
Si la estrategia cambia (aritmética → geométrica en v2), solo cambia este módulo.
GridEngine nunca hace aritmética de precios directamente.

Invariante de precisión:
    Ningún valor intermedio ni resultado final es float.
    Todo opera con Decimal y los métodos de redondeo de SymbolFilters (M1).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from chimuelo_prime.exchange_config.models import SymbolConfig
from chimuelo_prime.grid_engine.exceptions import GridCalculationError


@dataclass(frozen=True)
class LevelSpec:
    """Especificación inmutable de un nivel del grid.

    Producida por GridCalculator. Consumida por GridEngine para crear
    GridLevel en M3 y colocar órdenes via M4.

    No es un modelo Pydantic ni un ORM — es un dataclass de cálculo puro.

    Attributes:
        level_index: Posición en el grid (0 = nivel más bajo).
        lower_price: Precio de la orden BUY límite.
        upper_price: Precio de la orden SELL complementaria.
        qty:         Cantidad de base asset por orden (redondeada a step_size).
    """

    level_index: int
    lower_price: Decimal
    upper_price: Decimal
    qty: Decimal


class GridCalculator:
    """Calcula la geometría del grid. Sin I/O. Sin efectos secundarios.

    Toda la lógica de distribución de precios y cantidades vive aquí.
    Testeable sin mocks de ningún tipo.

    Estrategia v1: spacing aritmético uniforme.
    Estrategia v2 (backlog): spacing geométrico para activos con alta volatilidad.
    """

    @staticmethod
    def compute_levels(config: SymbolConfig) -> list[LevelSpec]:
        """Distribuye grid_levels niveles equidistantes entre lower_bound y upper_bound.

        Fórmula aritmética:
            spacing        = (upper_bound - lower_bound) / grid_levels
            lower_price[i] = round_to_tick(lower_bound + i × spacing)
            upper_price[i] = round_to_tick(lower_price[i] + spacing)
            qty[i]         = round_to_step(capital_per_order / lower_price[i])

        El redondeo usa ROUND_DOWN (conservador): preferimos comprar ligeramente
        más barato y vender ligeramente más barato que violar los filtros de Binance.

        Args:
            config: SymbolConfig con filtros (M1) y parámetros de estrategia.

        Returns:
            Lista de LevelSpec ordenada de menor a mayor (level_index 0 = más bajo).
            Todos los valores pasan validate_price, validate_quantity y validate_notional.

        Raises:
            GridCalculationError: si qty < min_qty o notional < min_notional en
                                  cualquier nivel. El bot no debe arrancar en ese caso.
        """
        filters = config.filters
        n = config.grid_levels
        spacing = (config.upper_bound - config.lower_bound) / Decimal(n)

        levels: list[LevelSpec] = []
        for i in range(n):
            lower = filters.round_price_to_tick(config.lower_bound + Decimal(i) * spacing)
            upper = filters.round_price_to_tick(lower + spacing)
            qty = filters.round_qty_to_step(config.capital_per_order / lower)

            # Defensa en profundidad: round_qty_to_step (M1) garantiza qty >= min_qty
            # con su fórmula offset. Este guard solo dispararía si M1 cambia su
            # implementación. En la práctica, el guard de notional dispara primero.
            if qty < filters.min_qty:
                raise GridCalculationError(
                    f"Nivel {i}: qty={qty} < min_qty={filters.min_qty}. "
                    f"capital_per_order={config.capital_per_order} insuficiente "
                    f"para lower_price={lower}. Aumentá capital_per_order o "
                    f"reducí el rango del grid."
                )

            notional = lower * qty
            if notional < filters.min_notional:
                raise GridCalculationError(
                    f"Nivel {i}: notional={notional} < min_notional={filters.min_notional}. "
                    f"lower_price={lower}, qty={qty}. Aumentá capital_per_order."
                )

            levels.append(
                LevelSpec(
                    level_index=i,
                    lower_price=lower,
                    upper_price=upper,
                    qty=qty,
                )
            )

        return levels

    @staticmethod
    def levels_below_price(levels: list[LevelSpec], current_price: Decimal) -> list[LevelSpec]:
        """Retorna los niveles cuyo lower_price < current_price.

        Estos son los candidatos a BUY inicial cuando el grid arranca por primera vez.
        Un nivel con lower_price >= current_price no tiene sentido como BUY:
        el precio de mercado ya está por encima de lo que queremos comprar.

        Args:
            levels:        Lista completa de niveles (resultado de compute_levels).
            current_price: Precio spot actual del símbolo.

        Returns:
            Subconjunto de levels ordenado de menor a mayor (mismo orden que la entrada).
        """
        return [lvl for lvl in levels if lvl.lower_price < current_price]
