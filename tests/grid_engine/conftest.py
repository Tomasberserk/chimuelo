"""Fixtures compartidos para tests de grid_engine (M5)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from chimuelo_prime.exchange_config.models import SymbolConfig, SymbolFilters


@pytest.fixture
def symbol_filters() -> SymbolFilters:
    """Filtros realistas de SOLUSDT en Binance (2024)."""
    return SymbolFilters(
        symbol="SOLUSDT",
        tick_size=Decimal("0.01"),
        min_price=Decimal("0.01"),
        max_price=Decimal("100000.00"),
        step_size=Decimal("0.01"),
        min_qty=Decimal("0.01"),
        max_qty=Decimal("100000.00"),
        min_notional=Decimal("5.00"),
        pct_up=Decimal("5.0"),
        pct_down=Decimal("0.2"),
    )


@pytest.fixture
def symbol_config(symbol_filters: SymbolFilters) -> SymbolConfig:
    """Config estándar de SOLUSDT: 20 niveles, $10 por orden, rango $100–$140."""
    return SymbolConfig(
        filters=symbol_filters,
        upper_bound=Decimal("140.00"),
        lower_bound=Decimal("100.00"),
        grid_levels=20,
        capital_per_order=Decimal("10.00"),
    )


@pytest.fixture
def tight_capital_config(symbol_filters: SymbolFilters) -> SymbolConfig:
    """Config con capital_per_order insuficiente — provoca GridCalculationError.

    round_qty_to_step garantiza qty >= min_qty (fórmula de M1 usa offset por min_qty).
    Con capital=1.50 → qty=0.01, notional=100×0.01=1.00 < min_notional=5.00 → error.
    """
    return SymbolConfig(
        filters=symbol_filters,
        upper_bound=Decimal("140.00"),
        lower_bound=Decimal("100.00"),
        grid_levels=20,
        capital_per_order=Decimal("1.50"),
    )
