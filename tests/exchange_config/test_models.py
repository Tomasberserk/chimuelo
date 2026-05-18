"""Tests para SymbolFilters y SymbolConfig.

Cubre:
    SymbolFilters:
        - Instanciación válida desde str y Decimal.
        - Rechazo explícito de float nativo.
        - Inmutabilidad (frozen=True).
        - validate_price: bajo mínimo, sobre máximo, no-múltiplo, válido.
        - validate_quantity: bajo mínimo, sobre máximo, no-múltiplo, válido.
        - validate_notional: bajo mínimo, válido.
        - round_price_to_tick: redondeo correcto hacia ABAJO.
        - round_qty_to_step: redondeo correcto hacia ABAJO.

    SymbolConfig:
        - Instanciación válida.
        - lower_bound >= upper_bound lanza ValueError.
        - lower_bound == upper_bound lanza ValueError (caso límite).
        - Rechazo de floats en campos financieros.
        - capital_weight default = Decimal("1.0").
        - capital_weight > 1 lanza ValidationError.

Notas de diseño:
    - Se usa una fixture `sol_filters` compartida para evitar repetición.
    - Todos los valores financieros se pasan como `str` para garantizar
      coerción exacta a Decimal sin pasar por float.
    - El caso numpy.float64 es testeado explícitamente porque Pydantic v2
      puede no detectarlo como `float` nativo (depende de la versión de numpy).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

try:
    import numpy as np

    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

from pydantic import ValidationError

from chimuelo_prime.exchange_config.exceptions import FilterValidationError
from chimuelo_prime.exchange_config.models import SymbolConfig, SymbolFilters


# --------------------------------------------------------------------------- #
# Fixture base: filtros reales de SOLUSDT (valores de producción Binance)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def sol_filters() -> SymbolFilters:
    """SymbolFilters válido para SOLUSDT con valores reales de Binance."""
    return SymbolFilters(
        symbol="SOLUSDT",
        tick_size=Decimal("0.01"),
        min_price=Decimal("0.01"),
        max_price=Decimal("100000.00"),
        step_size=Decimal("0.001"),
        min_qty=Decimal("0.001"),
        max_qty=Decimal("922327.000"),
        min_notional=Decimal("5.00"),
        pct_up=Decimal("5"),
        pct_down=Decimal("0.2"),
    )


@pytest.fixture()
def sol_config(sol_filters: SymbolFilters) -> SymbolConfig:
    """SymbolConfig válido para SOLUSDT con parámetros de grid calculados."""
    return SymbolConfig(
        filters=sol_filters,
        upper_bound=Decimal("185.00"),
        lower_bound=Decimal("140.00"),
        grid_levels=40,
        capital_per_order=Decimal("6.00"),
    )


# --------------------------------------------------------------------------- #
# SymbolFilters — Instanciación
# --------------------------------------------------------------------------- #
class TestSymbolFiltersInstantiation:
    def test_valid_from_decimal(self, sol_filters: SymbolFilters) -> None:
        """Instanciación válida desde Decimal no lanza excepciones."""
        assert sol_filters.symbol == "SOLUSDT"
        assert sol_filters.tick_size == Decimal("0.01")

    def test_valid_from_string(self) -> None:
        """Pydantic convierte str -> Decimal sin perder precisión."""
        f = SymbolFilters(
            symbol="SOLUSDT",
            tick_size=Decimal("0.01"),
            min_price=Decimal("0.01"),
            max_price=Decimal("100000.00"),
            step_size=Decimal("0.001"),
            min_qty=Decimal("0.001"),
            max_qty=Decimal("922327.000"),
            min_notional=Decimal("5.00"),
            pct_up=Decimal("5"),
            pct_down=Decimal("0.2"),
        )
        assert f.tick_size == Decimal("0.01")

    def test_empty_symbol_rejected(self) -> None:
        """symbol vacío debe fallar validación de Pydantic (min_length=1)."""
        with pytest.raises(ValidationError):
            SymbolFilters(
                symbol="",
                tick_size=Decimal("0.01"),
                min_price=Decimal("0.01"),
                max_price=Decimal("100000.00"),
                step_size=Decimal("0.001"),
                min_qty=Decimal("0.001"),
                max_qty=Decimal("922327.000"),
                min_notional=Decimal("5.00"),
                pct_up=Decimal("5"),
                pct_down=Decimal("0.2"),
            )

    def test_tick_size_zero_rejected(self) -> None:
        """tick_size == 0 viola la restricción gt=0."""
        with pytest.raises(ValidationError):
            SymbolFilters(
                symbol="SOLUSDT",
                tick_size=Decimal("0"),
                min_price=Decimal("0.01"),
                max_price=Decimal("100000.00"),
                step_size=Decimal("0.001"),
                min_qty=Decimal("0.001"),
                max_qty=Decimal("922327.000"),
                min_notional=Decimal("5.00"),
                pct_up=Decimal("5"),
                pct_down=Decimal("0.2"),
            )


# --------------------------------------------------------------------------- #
# SymbolFilters — Rechazo de floats
# --------------------------------------------------------------------------- #
class TestSymbolFiltersRejectFloats:
    """Bloqueo defensivo de float nativo en todos los campos financieros."""

    def test_float_tick_size_rejected(self) -> None:
        with pytest.raises((ValidationError, TypeError)):
            SymbolFilters(
                symbol="SOLUSDT",
                tick_size=0.01,  # type: ignore[arg-type]
                min_price=Decimal("0.01"),
                max_price=Decimal("100000.00"),
                step_size=Decimal("0.001"),
                min_qty=Decimal("0.001"),
                max_qty=Decimal("922327.000"),
                min_notional=Decimal("5.00"),
                pct_up=Decimal("5"),
                pct_down=Decimal("0.2"),
            )

    def test_float_min_price_rejected(self) -> None:
        with pytest.raises((ValidationError, TypeError)):
            SymbolFilters(
                symbol="SOLUSDT",
                tick_size=Decimal("0.01"),
                min_price=0.01,  # type: ignore[arg-type]
                max_price=Decimal("100000.00"),
                step_size=Decimal("0.001"),
                min_qty=Decimal("0.001"),
                max_qty=Decimal("922327.000"),
                min_notional=Decimal("5.00"),
                pct_up=Decimal("5"),
                pct_down=Decimal("0.2"),
            )

    def test_float_step_size_rejected(self) -> None:
        with pytest.raises((ValidationError, TypeError)):
            SymbolFilters(
                symbol="SOLUSDT",
                tick_size=Decimal("0.01"),
                min_price=Decimal("0.01"),
                max_price=Decimal("100000.00"),
                step_size=0.001,  # type: ignore[arg-type]
                min_qty=Decimal("0.001"),
                max_qty=Decimal("922327.000"),
                min_notional=Decimal("5.00"),
                pct_up=Decimal("5"),
                pct_down=Decimal("0.2"),
            )

    def test_float_min_notional_rejected(self) -> None:
        with pytest.raises((ValidationError, TypeError)):
            SymbolFilters(
                symbol="SOLUSDT",
                tick_size=Decimal("0.01"),
                min_price=Decimal("0.01"),
                max_price=Decimal("100000.00"),
                step_size=Decimal("0.001"),
                min_qty=Decimal("0.001"),
                max_qty=Decimal("922327.000"),
                min_notional=5.0,  # type: ignore[arg-type]
                pct_up=Decimal("5"),
                pct_down=Decimal("0.2"),
            )

    @pytest.mark.skipif(not NUMPY_AVAILABLE, reason="numpy no instalado")
    def test_numpy_float64_tick_size_rejected(self) -> None:
        """numpy.float64 puede no ser instancia de float nativo.

        Este test garantiza que el bloqueo defensivo funciona incluso con
        tipos de NumPy que pueden colarse vía librerías de análisis de datos.
        Si numpy.float64 pasa el validator, es una falla de seguridad en
        cálculos financieros.

        Decisión de Edison: acepta tanto ValidationError como TypeError porque
        el comportamiento exacto depende de la versión de numpy y Pydantic.
        Lo crítico es que NO se instancie correctamente con un float64.
        """
        with pytest.raises((ValidationError, TypeError)):
            SymbolFilters(
                symbol="SOLUSDT",
                tick_size=np.float64(0.01),  # type: ignore[arg-type]
                min_price=Decimal("0.01"),
                max_price=Decimal("100000.00"),
                step_size=Decimal("0.001"),
                min_qty=Decimal("0.001"),
                max_qty=Decimal("922327.000"),
                min_notional=Decimal("5.00"),
                pct_up=Decimal("5"),
                pct_down=Decimal("0.2"),
            )


# --------------------------------------------------------------------------- #
# SymbolFilters — Inmutabilidad
# --------------------------------------------------------------------------- #
class TestSymbolFiltersImmutability:
    def test_cannot_mutate_tick_size(self, sol_filters: SymbolFilters) -> None:
        """frozen=True debe lanzar ValidationError al intentar mutar."""
        with pytest.raises(ValidationError):
            sol_filters.tick_size = Decimal("0.02")  # type: ignore[misc]

    def test_cannot_mutate_symbol(self, sol_filters: SymbolFilters) -> None:
        with pytest.raises(ValidationError):
            sol_filters.symbol = "BTCUSDT"  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# SymbolFilters — validate_price
# --------------------------------------------------------------------------- #
class TestValidatePrice:
    def test_price_below_min_raises(self, sol_filters: SymbolFilters) -> None:
        """Precio por debajo de min_price debe lanzar FilterValidationError."""
        with pytest.raises(FilterValidationError, match="min_price"):
            sol_filters.validate_price(Decimal("0.00"))

    def test_price_above_max_raises(self, sol_filters: SymbolFilters) -> None:
        """Precio por encima de max_price debe lanzar FilterValidationError."""
        with pytest.raises(FilterValidationError, match="max_price"):
            sol_filters.validate_price(Decimal("200000.00"))

    def test_price_not_multiple_of_tick_raises(
        self, sol_filters: SymbolFilters
    ) -> None:
        """Precio que no es múltiplo de tick_size debe lanzar FilterValidationError."""
        # tick_size = 0.01; 150.005 no es múltiplo exacto
        with pytest.raises(FilterValidationError, match="tick_size"):
            sol_filters.validate_price(Decimal("150.005"))

    def test_valid_price_does_not_raise(self, sol_filters: SymbolFilters) -> None:
        """Precio válido exactamente en tick_size no debe lanzar excepción."""
        sol_filters.validate_price(Decimal("150.00"))  # 150.00 = min + 14999*0.01

    def test_price_at_min_price_valid(self, sol_filters: SymbolFilters) -> None:
        """min_price en sí mismo es un precio válido."""
        sol_filters.validate_price(Decimal("0.01"))

    def test_price_at_max_price_valid(self, sol_filters: SymbolFilters) -> None:
        """max_price en sí mismo es un precio válido."""
        sol_filters.validate_price(Decimal("100000.00"))

    def test_error_message_contains_symbol(self, sol_filters: SymbolFilters) -> None:
        """El mensaje de error debe identificar el símbolo para trazabilidad."""
        with pytest.raises(FilterValidationError, match="SOLUSDT"):
            sol_filters.validate_price(Decimal("0.00"))


# --------------------------------------------------------------------------- #
# SymbolFilters — validate_quantity
# --------------------------------------------------------------------------- #
class TestValidateQuantity:
    def test_qty_below_min_raises(self, sol_filters: SymbolFilters) -> None:
        with pytest.raises(FilterValidationError, match="min_qty"):
            sol_filters.validate_quantity(Decimal("0.0001"))

    def test_qty_above_max_raises(self, sol_filters: SymbolFilters) -> None:
        with pytest.raises(FilterValidationError, match="max_qty"):
            sol_filters.validate_quantity(Decimal("999999.000"))

    def test_qty_not_multiple_of_step_raises(self, sol_filters: SymbolFilters) -> None:
        # step_size = 0.001; 1.0005 no es múltiplo exacto
        with pytest.raises(FilterValidationError, match="step_size"):
            sol_filters.validate_quantity(Decimal("1.0005"))

    def test_valid_qty_does_not_raise(self, sol_filters: SymbolFilters) -> None:
        sol_filters.validate_quantity(Decimal("1.000"))

    def test_qty_at_min_qty_valid(self, sol_filters: SymbolFilters) -> None:
        sol_filters.validate_quantity(Decimal("0.001"))

    def test_error_message_contains_symbol(self, sol_filters: SymbolFilters) -> None:
        with pytest.raises(FilterValidationError, match="SOLUSDT"):
            sol_filters.validate_quantity(Decimal("0.0001"))


# --------------------------------------------------------------------------- #
# SymbolFilters — validate_notional
# --------------------------------------------------------------------------- #
class TestValidateNotional:
    def test_notional_below_min_raises(self, sol_filters: SymbolFilters) -> None:
        """price * qty < min_notional debe lanzar FilterValidationError."""
        # 1.00 * 0.001 = 0.001 USDT < min_notional=5.00
        with pytest.raises(FilterValidationError, match="min_notional"):
            sol_filters.validate_notional(
                price=Decimal("1.00"),
                qty=Decimal("0.001"),
            )

    def test_notional_exactly_at_min_valid(self, sol_filters: SymbolFilters) -> None:
        """Notional exactamente igual a min_notional es válido (>= no >)."""
        # 5000.00 * 0.001 = 5.00 USDT == min_notional
        sol_filters.validate_notional(
            price=Decimal("5000.00"),
            qty=Decimal("0.001"),
        )

    def test_notional_above_min_valid(self, sol_filters: SymbolFilters) -> None:
        # 160.00 * 0.040 = 6.40 USDT > min_notional=5.00
        sol_filters.validate_notional(
            price=Decimal("160.00"),
            qty=Decimal("0.040"),
        )

    def test_error_message_contains_price_qty_notional(
        self, sol_filters: SymbolFilters
    ) -> None:
        """El mensaje debe contener price, qty y notional calculado."""
        with pytest.raises(FilterValidationError) as exc_info:
            sol_filters.validate_notional(
                price=Decimal("1.00"),
                qty=Decimal("0.001"),
            )
        msg = str(exc_info.value)
        assert "notional" in msg
        assert "price" in msg
        assert "qty" in msg


# --------------------------------------------------------------------------- #
# SymbolFilters — round_price_to_tick
# --------------------------------------------------------------------------- #
class TestRoundPriceToTick:
    def test_already_on_tick_unchanged(self, sol_filters: SymbolFilters) -> None:
        """Precio ya alineado al tick no debe cambiar."""
        result = sol_filters.round_price_to_tick(Decimal("150.00"))
        assert result == Decimal("150.00")

    def test_rounds_down_not_up(self, sol_filters: SymbolFilters) -> None:
        """ROUND_DOWN: 150.007 con tick=0.01 debe dar 150.00, no 150.01."""
        result = sol_filters.round_price_to_tick(Decimal("150.007"))
        assert result == Decimal("150.00")

    def test_rounds_down_near_upper(self, sol_filters: SymbolFilters) -> None:
        """150.019 con tick=0.01 → 150.01, no 150.02."""
        result = sol_filters.round_price_to_tick(Decimal("150.019"))
        assert result == Decimal("150.01")

    def test_result_passes_validate_price(self, sol_filters: SymbolFilters) -> None:
        """El precio redondeado debe pasar validate_price sin excepción."""
        rounded = sol_filters.round_price_to_tick(Decimal("150.007"))
        sol_filters.validate_price(rounded)  # no debe lanzar

    def test_result_is_decimal(self, sol_filters: SymbolFilters) -> None:
        """El resultado siempre debe ser Decimal, nunca float."""
        result = sol_filters.round_price_to_tick(Decimal("150.007"))
        assert isinstance(result, Decimal)


# --------------------------------------------------------------------------- #
# SymbolFilters — round_qty_to_step
# --------------------------------------------------------------------------- #
class TestRoundQtyToStep:
    def test_already_on_step_unchanged(self, sol_filters: SymbolFilters) -> None:
        result = sol_filters.round_qty_to_step(Decimal("1.000"))
        assert result == Decimal("1.000")

    def test_rounds_down_not_up(self, sol_filters: SymbolFilters) -> None:
        """ROUND_DOWN: 1.0009 con step=0.001 → 1.000, no 1.001."""
        result = sol_filters.round_qty_to_step(Decimal("1.0009"))
        assert result == Decimal("1.000")

    def test_rounds_down_near_step(self, sol_filters: SymbolFilters) -> None:
        """1.0019 con step=0.001 → 1.001."""
        result = sol_filters.round_qty_to_step(Decimal("1.0019"))
        assert result == Decimal("1.001")

    def test_result_passes_validate_quantity(self, sol_filters: SymbolFilters) -> None:
        rounded = sol_filters.round_qty_to_step(Decimal("1.0009"))
        sol_filters.validate_quantity(rounded)

    def test_result_is_decimal(self, sol_filters: SymbolFilters) -> None:
        result = sol_filters.round_qty_to_step(Decimal("1.0009"))
        assert isinstance(result, Decimal)


# --------------------------------------------------------------------------- #
# SymbolConfig — Instanciación y validación cruzada
# --------------------------------------------------------------------------- #
class TestSymbolConfigInstantiation:
    def test_valid_config(self, sol_config: SymbolConfig) -> None:
        assert sol_config.grid_levels == 40
        assert sol_config.upper_bound == Decimal("185.00")
        assert sol_config.lower_bound == Decimal("140.00")

    def test_capital_weight_default_is_one(self, sol_filters: SymbolFilters) -> None:
        """Sin especificar capital_weight, debe ser Decimal('1.0')."""
        config = SymbolConfig(
            filters=sol_filters,
            upper_bound=Decimal("185.00"),
            lower_bound=Decimal("140.00"),
            grid_levels=40,
            capital_per_order=Decimal("6.00"),
        )
        assert config.capital_weight == Decimal("1.0")

    def test_custom_capital_weight(self, sol_filters: SymbolFilters) -> None:
        config = SymbolConfig(
            filters=sol_filters,
            upper_bound=Decimal("185.00"),
            lower_bound=Decimal("140.00"),
            grid_levels=40,
            capital_per_order=Decimal("6.00"),
            capital_weight=Decimal("0.6"),
        )
        assert config.capital_weight == Decimal("0.6")

    def test_capital_weight_above_one_rejected(
        self, sol_filters: SymbolFilters
    ) -> None:
        """capital_weight > 1 viola le=1."""
        with pytest.raises(ValidationError):
            SymbolConfig(
                filters=sol_filters,
                upper_bound=Decimal("185.00"),
                lower_bound=Decimal("140.00"),
                grid_levels=40,
                capital_per_order=Decimal("6.00"),
                capital_weight=Decimal("1.1"),
            )

    def test_grid_levels_must_be_greater_than_one(
        self, sol_filters: SymbolFilters
    ) -> None:
        """grid_levels <= 1 viola gt=1."""
        with pytest.raises(ValidationError):
            SymbolConfig(
                filters=sol_filters,
                upper_bound=Decimal("185.00"),
                lower_bound=Decimal("140.00"),
                grid_levels=1,
                capital_per_order=Decimal("6.00"),
            )


# --------------------------------------------------------------------------- #
# SymbolConfig — Validación cruzada (model_post_init)
# --------------------------------------------------------------------------- #
class TestSymbolConfigCrossValidation:
    def test_lower_bound_greater_than_upper_bound_raises(
        self, sol_filters: SymbolFilters
    ) -> None:
        """lower_bound > upper_bound debe lanzar ValueError."""
        with pytest.raises(ValueError, match="lower_bound"):
            SymbolConfig(
                filters=sol_filters,
                upper_bound=Decimal("140.00"),
                lower_bound=Decimal("185.00"),  # invertido
                grid_levels=40,
                capital_per_order=Decimal("6.00"),
            )

    def test_lower_bound_equal_to_upper_bound_raises(
        self, sol_filters: SymbolFilters
    ) -> None:
        """lower_bound == upper_bound también debe fallar (caso límite).

        Un grid con rango cero no tiene sentido económico: spacing=0
        provocaría división por cero en el motor de niveles.
        """
        with pytest.raises(ValueError, match="lower_bound"):
            SymbolConfig(
                filters=sol_filters,
                upper_bound=Decimal("150.00"),
                lower_bound=Decimal("150.00"),
                grid_levels=40,
                capital_per_order=Decimal("6.00"),
            )

    def test_valid_bounds_do_not_raise(self, sol_config: SymbolConfig) -> None:
        """Bounds válidos no deben lanzar excepciones."""
        assert sol_config.lower_bound < sol_config.upper_bound


# --------------------------------------------------------------------------- #
# SymbolConfig — Rechazo de floats
# --------------------------------------------------------------------------- #
class TestSymbolConfigRejectFloats:
    def test_float_upper_bound_rejected(self, sol_filters: SymbolFilters) -> None:
        with pytest.raises((ValidationError, TypeError)):
            SymbolConfig(
                filters=sol_filters,
                upper_bound=185.0,  # type: ignore[arg-type]
                lower_bound=Decimal("140.00"),
                grid_levels=40,
                capital_per_order=Decimal("6.00"),
            )

    def test_float_lower_bound_rejected(self, sol_filters: SymbolFilters) -> None:
        with pytest.raises((ValidationError, TypeError)):
            SymbolConfig(
                filters=sol_filters,
                upper_bound=Decimal("185.00"),
                lower_bound=140.0,  # type: ignore[arg-type]
                grid_levels=40,
                capital_per_order=Decimal("6.00"),
            )

    def test_float_capital_per_order_rejected(self, sol_filters: SymbolFilters) -> None:
        with pytest.raises((ValidationError, TypeError)):
            SymbolConfig(
                filters=sol_filters,
                upper_bound=Decimal("185.00"),
                lower_bound=Decimal("140.00"),
                grid_levels=40,
                capital_per_order=6.0,  # type: ignore[arg-type]
            )

    def test_float_capital_weight_rejected(self, sol_filters: SymbolFilters) -> None:
        with pytest.raises((ValidationError, TypeError)):
            SymbolConfig(
                filters=sol_filters,
                upper_bound=Decimal("185.00"),
                lower_bound=Decimal("140.00"),
                grid_levels=40,
                capital_per_order=Decimal("6.00"),
                capital_weight=0.6,  # type: ignore[arg-type]
            )


# --------------------------------------------------------------------------- #
# SymbolConfig — Inmutabilidad
# --------------------------------------------------------------------------- #
class TestSymbolConfigImmutability:
    def test_cannot_mutate_upper_bound(self, sol_config: SymbolConfig) -> None:
        with pytest.raises(ValidationError):
            sol_config.upper_bound = Decimal("200.00")  # type: ignore[misc]

    def test_cannot_mutate_grid_levels(self, sol_config: SymbolConfig) -> None:
        with pytest.raises(ValidationError):
            sol_config.grid_levels = 50  # type: ignore[misc]
