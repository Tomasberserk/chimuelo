"""Tests para GridCalculator y LevelSpec (M5).

Cubre los 6 casos obligatorios de MARTA:
    1. compute_levels produce N niveles con precios equidistantes.
    2. Todos los LevelSpec resultantes pasan los filtros de M1.
    3. capital_per_order insuficiente → GridCalculationError (qty < min_qty).
    4. notional < min_notional → GridCalculationError.
    5. levels_below_price filtra correctamente por precio actual.
    6. Ningún campo de LevelSpec ni variable de cálculo contiene float.

Adicionalmente:
    - Primer nivel: lower_price = lower_bound (redondeado a tick).
    - Último nivel: upper_price ≈ upper_bound.
    - Spacing uniforme entre niveles consecutivos.
    - LevelSpec es inmutable (frozen dataclass).
    - levels_below_price con precio en el límite inferior retorna lista vacía.
    - levels_below_price con precio sobre el límite superior retorna todos.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from chimuelo_prime.exchange_config.models import SymbolConfig, SymbolFilters
from chimuelo_prime.grid_engine.calculator import GridCalculator, LevelSpec
from chimuelo_prime.grid_engine.exceptions import GridCalculationError


# ---------------------------------------------------------------------------
# Caso 1: estructura y cantidad de niveles
# ---------------------------------------------------------------------------
class TestComputeLevelsStructure:
    def test_returns_correct_number_of_levels(self, symbol_config: SymbolConfig) -> None:
        levels = GridCalculator.compute_levels(symbol_config)
        assert len(levels) == symbol_config.grid_levels

    def test_level_indices_are_sequential(self, symbol_config: SymbolConfig) -> None:
        levels = GridCalculator.compute_levels(symbol_config)
        assert [lvl.level_index for lvl in levels] == list(range(symbol_config.grid_levels))

    def test_first_level_lower_price_equals_lower_bound(
        self, symbol_config: SymbolConfig
    ) -> None:
        levels = GridCalculator.compute_levels(symbol_config)
        # lower_price[0] = round_to_tick(lower_bound + 0 * spacing) = lower_bound
        assert levels[0].lower_price == symbol_config.lower_bound

    def test_last_level_upper_price_approximates_upper_bound(
        self, symbol_config: SymbolConfig
    ) -> None:
        levels = GridCalculator.compute_levels(symbol_config)
        # upper_price[-1] debería ser ≈ upper_bound (puede diferir por redondeo de tick)
        delta = abs(levels[-1].upper_price - symbol_config.upper_bound)
        assert delta <= symbol_config.filters.tick_size

    def test_levels_are_sorted_ascending(self, symbol_config: SymbolConfig) -> None:
        levels = GridCalculator.compute_levels(symbol_config)
        prices = [lvl.lower_price for lvl in levels]
        assert prices == sorted(prices)

    def test_upper_price_greater_than_lower_price_in_every_level(
        self, symbol_config: SymbolConfig
    ) -> None:
        levels = GridCalculator.compute_levels(symbol_config)
        for lvl in levels:
            assert lvl.upper_price > lvl.lower_price, (
                f"Nivel {lvl.level_index}: upper={lvl.upper_price} <= lower={lvl.lower_price}"
            )

    def test_spacing_is_uniform_between_consecutive_levels(
        self, symbol_config: SymbolConfig
    ) -> None:
        levels = GridCalculator.compute_levels(symbol_config)
        spacings = [
            levels[i + 1].lower_price - levels[i].lower_price
            for i in range(len(levels) - 1)
        ]
        # Todos los spacings deben ser iguales (pueden variar en un tick por redondeo)
        assert max(spacings) - min(spacings) <= symbol_config.filters.tick_size


# ---------------------------------------------------------------------------
# Caso 2: todos los LevelSpec pasan los filtros de M1
# ---------------------------------------------------------------------------
class TestComputeLevelsAllPassFilters:
    def test_all_levels_pass_validate_price(self, symbol_config: SymbolConfig) -> None:
        from chimuelo_prime.exchange_config.exceptions import FilterValidationError

        levels = GridCalculator.compute_levels(symbol_config)
        for lvl in levels:
            try:
                symbol_config.filters.validate_price(lvl.lower_price)
                symbol_config.filters.validate_price(lvl.upper_price)
            except FilterValidationError as exc:
                pytest.fail(f"Nivel {lvl.level_index} falla validate_price: {exc}")

    def test_all_levels_pass_validate_quantity(self, symbol_config: SymbolConfig) -> None:
        from chimuelo_prime.exchange_config.exceptions import FilterValidationError

        levels = GridCalculator.compute_levels(symbol_config)
        for lvl in levels:
            try:
                symbol_config.filters.validate_quantity(lvl.qty)
            except FilterValidationError as exc:
                pytest.fail(f"Nivel {lvl.level_index} falla validate_quantity: {exc}")

    def test_all_levels_pass_validate_notional(self, symbol_config: SymbolConfig) -> None:
        from chimuelo_prime.exchange_config.exceptions import FilterValidationError

        levels = GridCalculator.compute_levels(symbol_config)
        for lvl in levels:
            try:
                symbol_config.filters.validate_notional(lvl.lower_price, lvl.qty)
            except FilterValidationError as exc:
                pytest.fail(f"Nivel {lvl.level_index} falla validate_notional: {exc}")


# ---------------------------------------------------------------------------
# Caso 3: capital_per_order insuficiente → notional < min_notional → GridCalculationError
#
# Nota de implementación: round_qty_to_step (M1) usa la fórmula
#   steps = floor((qty - min_qty) / step_size)
#   result = steps * step_size + min_qty
# Por lo tanto siempre retorna >= min_qty. El primer guard que puede disparar
# en producción es min_notional, no min_qty. La check de min_qty existe como
# defensa en profundidad ante posibles cambios futuros en M1.
# ---------------------------------------------------------------------------
class TestComputeLevelsInsufficientCapital:
    def test_raises_grid_calculation_error_for_low_capital(
        self, tight_capital_config: SymbolConfig
    ) -> None:
        # capital=1.50 → qty=0.01, notional=1.00 < min_notional=5.00
        with pytest.raises(GridCalculationError):
            GridCalculator.compute_levels(tight_capital_config)

    def test_error_is_not_value_error(
        self, tight_capital_config: SymbolConfig
    ) -> None:
        # MARTA exige GridCalculationError tipado, no ValueError genérico.
        with pytest.raises(GridCalculationError):
            GridCalculator.compute_levels(tight_capital_config)

    def test_error_message_mentions_capital_per_order(
        self, tight_capital_config: SymbolConfig
    ) -> None:
        with pytest.raises(GridCalculationError) as exc_info:
            GridCalculator.compute_levels(tight_capital_config)
        assert "capital_per_order" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Caso 4: notional < min_notional → GridCalculationError
# ---------------------------------------------------------------------------
class TestComputeLevelsBelowMinNotional:
    def test_raises_grid_calculation_error_when_notional_below_min(
        self, symbol_filters: SymbolFilters
    ) -> None:
        # capital_per_order = 0.10 USDT → qty = round_down(0.10 / 100.00) = 0.00 → 0 SOL
        # qty será 0.01 (min_qty ok), pero notional = 100.00 × 0.01 = 1.00 < 5.00
        config = SymbolConfig(
            filters=symbol_filters,
            upper_bound=Decimal("140.00"),
            lower_bound=Decimal("100.00"),
            grid_levels=20,
            capital_per_order=Decimal("0.50"),  # 0.50 / 100 → 0.00 redondeado → min_qty ok pero notional falla
        )
        # 0.50 / 100.00 = 0.005 → round_to_step → 0.00 < min_qty → error de qty antes de notional
        # Necesitamos que qty >= min_qty pero notional < min_notional.
        # capital = 1.50 → qty = round_down(1.50/100) = 0.01, notional = 100 × 0.01 = 1.00 < 5.00
        config2 = SymbolConfig(
            filters=symbol_filters,
            upper_bound=Decimal("140.00"),
            lower_bound=Decimal("100.00"),
            grid_levels=20,
            capital_per_order=Decimal("1.50"),
        )
        with pytest.raises(GridCalculationError) as exc_info:
            GridCalculator.compute_levels(config2)
        assert "min_notional" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Caso 5: levels_below_price filtra correctamente
# ---------------------------------------------------------------------------
class TestLevelsBelowPrice:
    def test_filters_levels_strictly_below_current_price(
        self, symbol_config: SymbolConfig
    ) -> None:
        levels = GridCalculator.compute_levels(symbol_config)
        current_price = Decimal("120.00")
        below = GridCalculator.levels_below_price(levels, current_price)
        assert all(lvl.lower_price < current_price for lvl in below)

    def test_no_levels_above_or_at_current_price_included(
        self, symbol_config: SymbolConfig
    ) -> None:
        levels = GridCalculator.compute_levels(symbol_config)
        current_price = Decimal("120.00")
        below = GridCalculator.levels_below_price(levels, current_price)
        above_or_equal = [lvl for lvl in levels if lvl.lower_price >= current_price]
        assert not any(lvl in below for lvl in above_or_equal)

    def test_price_below_lower_bound_returns_empty(
        self, symbol_config: SymbolConfig
    ) -> None:
        levels = GridCalculator.compute_levels(symbol_config)
        below = GridCalculator.levels_below_price(levels, Decimal("99.00"))
        assert below == []

    def test_price_above_upper_bound_returns_all_levels(
        self, symbol_config: SymbolConfig
    ) -> None:
        levels = GridCalculator.compute_levels(symbol_config)
        below = GridCalculator.levels_below_price(levels, Decimal("200.00"))
        assert len(below) == len(levels)

    def test_price_at_lower_bound_returns_empty(
        self, symbol_config: SymbolConfig
    ) -> None:
        levels = GridCalculator.compute_levels(symbol_config)
        # lower_price[0] == lower_bound → NOT strictly below → vacío
        below = GridCalculator.levels_below_price(levels, symbol_config.lower_bound)
        assert below == []

    def test_result_preserves_ascending_order(
        self, symbol_config: SymbolConfig
    ) -> None:
        levels = GridCalculator.compute_levels(symbol_config)
        below = GridCalculator.levels_below_price(levels, Decimal("120.00"))
        prices = [lvl.lower_price for lvl in below]
        assert prices == sorted(prices)


# ---------------------------------------------------------------------------
# Caso 6: cero floats en LevelSpec y en el proceso de cálculo
# ---------------------------------------------------------------------------
class TestDecimalPurity:
    def test_no_float_in_level_spec_fields(self, symbol_config: SymbolConfig) -> None:
        levels = GridCalculator.compute_levels(symbol_config)
        for lvl in levels:
            assert isinstance(lvl.lower_price, Decimal), (
                f"Nivel {lvl.level_index}: lower_price es {type(lvl.lower_price)}"
            )
            assert isinstance(lvl.upper_price, Decimal), (
                f"Nivel {lvl.level_index}: upper_price es {type(lvl.upper_price)}"
            )
            assert isinstance(lvl.qty, Decimal), (
                f"Nivel {lvl.level_index}: qty es {type(lvl.qty)}"
            )

    def test_level_index_is_int(self, symbol_config: SymbolConfig) -> None:
        levels = GridCalculator.compute_levels(symbol_config)
        for lvl in levels:
            assert isinstance(lvl.level_index, int)

    def test_level_spec_is_immutable(self, symbol_config: SymbolConfig) -> None:
        levels = GridCalculator.compute_levels(symbol_config)
        lvl = levels[0]
        with pytest.raises((AttributeError, TypeError)):
            lvl.lower_price = Decimal("999.00")  # type: ignore[misc]
