"""Cálculo de métricas financieras de rendimiento para backtesting (M6).

Garantiza la ausencia total de floats, utilizando aritmética Decimal de alta precisión
para Sortino, Calmar, Profit Factor, Max Drawdown y Retorno Total.
"""

from __future__ import annotations

from decimal import Decimal


def _get_periods_per_year(interval: str) -> Decimal:
    """Retorna la cantidad de períodos en un año para un intervalo dado."""
    val = interval.lower().strip()
    if "m" in val:
        try:
            minutes = int(val.replace("m", ""))
        except ValueError:
            minutes = 1
        return Decimal(str(525600 // minutes))
    elif "h" in val:
        try:
            hours = int(val.replace("h", ""))
        except ValueError:
            hours = 1
        return Decimal(str(8760 // hours))
    elif "d" in val:
        try:
            days = int(val.replace("d", ""))
        except ValueError:
            days = 1
        return Decimal(str(365 // days))
    elif val.endswith("w"):
        return Decimal("52")
    return Decimal("365")  # Por defecto diario


def calculate_total_return(initial_equity: Decimal, final_equity: Decimal) -> Decimal:
    """Calcula el retorno total porcentual.

    Formula: ((final - initial) / initial) * 100
    """
    if initial_equity <= Decimal("0.0"):
        return Decimal("0.0")
    return ((final_equity - initial_equity) / initial_equity) * Decimal("100")


def calculate_max_drawdown(equities: list[Decimal]) -> Decimal:
    """Calcula el máximo drawdown porcentual de una serie de patrimonio neto."""
    if not equities:
        return Decimal("0.0")

    max_dd = Decimal("0.0")
    peak = Decimal("-Infinity")

    for eq in equities:
        if eq > peak:
            peak = eq
        if peak > Decimal("0.0"):
            dd = ((peak - eq) / peak) * Decimal("100")
            if dd > max_dd:
                max_dd = dd

    return max_dd


def calculate_profit_factor(gross_profits: Decimal, gross_losses: Decimal) -> Decimal:
    """Calcula el Profit Factor (beneficio bruto / pérdida bruta).

    Si no hay pérdidas, retorna Decimal("Infinity") si hay ganancias, o Decimal("0.0").
    """
    if gross_losses == Decimal("0.0"):
        return Decimal("99.99") if gross_profits > Decimal("0.0") else Decimal("0.0")
    return gross_profits / gross_losses


def calculate_sortino_ratio(
    equities: list[Decimal],
    interval: str,
    risk_free_rate: Decimal = Decimal("0.0"),
) -> Decimal:
    """Calcula el ratio de Sortino anualizado.

    Mide el retorno excedente por unidad de riesgo a la baja (downside deviation).
    """
    if len(equities) < 2:
        return Decimal("0.0")

    # 1. Calcular retornos periódicos
    returns: list[Decimal] = []
    for i in range(1, len(equities)):
        prev = equities[i - 1]
        curr = equities[i]
        if prev > Decimal("0.0"):
            returns.append((curr - prev) / prev)
        else:
            returns.append(Decimal("0.0"))

    # 2. Calcular retorno promedio
    avg_return = sum(returns) / Decimal(str(len(returns)))

    # 3. Calcular Downside Deviation
    downside_diff_sq = []
    for r in returns:
        downside = min(r - risk_free_rate, Decimal("0.0"))
        downside_diff_sq.append(downside * downside)

    downside_variance = sum(downside_diff_sq) / Decimal(str(len(returns)))
    downside_deviation = downside_variance.sqrt()

    if downside_deviation == Decimal("0.0"):
        return (
            Decimal("99.99") if (avg_return - risk_free_rate) > Decimal("0.0") else Decimal("0.0")
        )

    # 4. Calcular ratio crudo y anualizar
    raw_sortino = (avg_return - risk_free_rate) / downside_deviation
    periods_per_year = _get_periods_per_year(interval)

    return raw_sortino * periods_per_year.sqrt()


def calculate_calmar_ratio(
    equities: list[Decimal],
    max_drawdown_pct: Decimal,
    interval: str,
) -> Decimal:
    """Calcula el ratio de Calmar anualizado.

    Formula: Retorno Anualizado / Máximo Drawdown
    """
    total_periods = len(equities) - 1
    if total_periods <= 0:
        return Decimal("0.0")

    initial_equity = equities[0]
    if initial_equity <= Decimal("0.0"):
        return Decimal("0.0")

    total_return = (equities[-1] - initial_equity) / initial_equity
    periods_per_year = _get_periods_per_year(interval)

    # Anualización simple del retorno
    annualized_return_pct = (
        (total_return / Decimal(str(total_periods))) * periods_per_year * Decimal("100")
    )

    if max_drawdown_pct <= Decimal("0.0"):
        return Decimal("99.99") if annualized_return_pct > Decimal("0.0") else Decimal("0.0")

    return annualized_return_pct / max_drawdown_pct
