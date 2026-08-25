"""Tests unitarios para el cálculo de métricas financieras de backtesting (M6)."""

from __future__ import annotations

from decimal import Decimal

from chimuelo_prime.backtesting.metrics import (
    calculate_calmar_ratio,
    calculate_max_drawdown,
    calculate_profit_factor,
    calculate_sortino_ratio,
    calculate_total_return,
)


def test_calculate_total_return() -> None:
    """Valida el cálculo de retorno total."""
    assert calculate_total_return(Decimal("100.00"), Decimal("150.00")) == Decimal("50.00")
    assert calculate_total_return(Decimal("100.00"), Decimal("90.00")) == Decimal("-10.00")
    assert calculate_total_return(Decimal("0.00"), Decimal("150.00")) == Decimal("0.00")


def test_calculate_max_drawdown() -> None:
    """Valida el cálculo de máximo drawdown de una serie."""
    # Serie con picos y valles:
    # 100 -> peak=100, dd=0%
    # 110 -> peak=110, dd=0%
    # 99  -> peak=110, dd=(110-99)/110 * 100 = 10%
    # 88  -> peak=110, dd=(110-88)/110 * 100 = 20%
    # 120 -> peak=120, dd=0%
    # 108 -> peak=120, dd=(120-108)/120 * 100 = 10%
    equities = [
        Decimal("100.00"),
        Decimal("110.00"),
        Decimal("99.00"),
        Decimal("88.00"),
        Decimal("120.00"),
        Decimal("108.00"),
    ]
    assert calculate_max_drawdown(equities) == Decimal("20.0")
    assert calculate_max_drawdown([]) == Decimal("0.0")


def test_calculate_profit_factor() -> None:
    """Valida el cálculo de profit factor."""
    assert calculate_profit_factor(Decimal("100.00"), Decimal("50.00")) == Decimal("2.0")
    assert calculate_profit_factor(Decimal("100.00"), Decimal("0.00")) == Decimal("99.99")
    assert calculate_profit_factor(Decimal("0.00"), Decimal("0.00")) == Decimal("0.00")


def test_calculate_sortino_ratio() -> None:
    """Valida el cálculo del ratio de Sortino anualizado."""
    # Serie de equities que sube y baja
    # Equities: 100 -> 105 -> 100 -> 110
    # Returns:
    # 100 -> 105: 5% (0.05)
    # 105 -> 100: -4.7619% (-0.047619)
    # 100 -> 110: 10% (0.10)
    equities = [
        Decimal("100.00"),
        Decimal("105.00"),
        Decimal("100.00"),
        Decimal("110.00"),
    ]

    # Para "1d" interval -> 365 períodos por año.
    ratio = calculate_sortino_ratio(equities, interval="1d")
    assert ratio > Decimal("0.0")
    assert isinstance(ratio, Decimal)

    # Si no hay suficientes elementos
    assert calculate_sortino_ratio([Decimal("100.00")], interval="1d") == Decimal("0.0")


def test_calculate_calmar_ratio() -> None:
    """Valida el cálculo del ratio de Calmar anualizado."""
    # Equities: 100 -> 105 -> 100 -> 110 (3 periodos totales)
    # Rentabilidad total: (110 - 100)/100 = 10%
    # Máximo drawdown: peak=105, dd=(105-100)/105 * 100 = 4.7619%
    # Intervalo: "1d" -> 365 períodos por año
    # Retorno anualizado: (10% / 3) * 365 = 1216.66%
    # Calmar: 1216.66% / 4.7619% = ~255.5
    equities = [
        Decimal("100.00"),
        Decimal("105.00"),
        Decimal("100.00"),
        Decimal("110.00"),
    ]
    max_dd = calculate_max_drawdown(equities)

    calmar = calculate_calmar_ratio(equities, max_dd, interval="1d")
    assert calmar > Decimal("0.0")
    assert isinstance(calmar, Decimal)

    # Casos límite
    assert calculate_calmar_ratio([Decimal("100.00")], max_dd, interval="1d") == Decimal("0.0")
    assert calculate_calmar_ratio(equities, Decimal("0.0"), interval="1d") == Decimal("99.99")


def test_get_periods_per_year() -> None:
    """Valida la conversión de intervalos a periodos anuales."""
    from chimuelo_prime.backtesting.metrics import _get_periods_per_year

    assert _get_periods_per_year("1m") == Decimal("525600")
    assert _get_periods_per_year("5m") == Decimal("105120")
    assert _get_periods_per_year("1h") == Decimal("8760")
    assert _get_periods_per_year("4h") == Decimal("2190")
    assert _get_periods_per_year("1d") == Decimal("365")
    assert _get_periods_per_year("1w") == Decimal("52")
    assert _get_periods_per_year("unknown") == Decimal("365")
