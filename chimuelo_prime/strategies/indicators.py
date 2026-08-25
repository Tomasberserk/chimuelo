"""Biblioteca de Indicadores Técnicos Cuantitativos con Aritmética Decimal Pura.

Garantiza determinismo financiero y cero errores de coma flotante.
Incluye: SMA, EMA, RSI (Wilder's Smoothing), ATR (Wilder's Smoothing) y detección de Pivots/Swings.
"""

from __future__ import annotations

from decimal import Decimal


def calculate_sma(values: list[Decimal], period: int) -> list[Decimal | None]:
    """Calcula la Media Móvil Simple (SMA).

    Args:
        values: Serie de valores Decimal.
        period: Periodo de la media (ej. 20, 50, 200).

    Returns:
        Lista de igual longitud que `values`, con None para los primeros period - 1 elementos.
    """
    if period <= 0:
        raise ValueError(f"El periodo debe ser mayor a 0, recibido: {period}")

    result: list[Decimal | None] = [None] * len(values)
    if len(values) < period:
        return result

    current_sum = sum(values[:period], Decimal("0"))
    result[period - 1] = current_sum / Decimal(str(period))

    for i in range(period, len(values)):
        current_sum += values[i] - values[i - period]
        result[i] = current_sum / Decimal(str(period))

    return result


def calculate_ema(values: list[Decimal], period: int) -> list[Decimal | None]:
    """Calcula la Media Móvil Exponencial (EMA).

    Args:
        values: Serie de valores Decimal.
        period: Periodo de la media exponencial.

    Returns:
        Lista de igual longitud que `values`.
    """
    if period <= 0:
        raise ValueError(f"El periodo debe ser mayor a 0, recibido: {period}")

    result: list[Decimal | None] = [None] * len(values)
    if len(values) < period:
        return result

    # Inicialización con SMA
    sma_init = sum(values[:period], Decimal("0")) / Decimal(str(period))
    result[period - 1] = sma_init

    multiplier = Decimal("2") / Decimal(str(period + 1))
    one_minus_mult = Decimal("1") - multiplier

    prev_ema = sma_init
    for i in range(period, len(values)):
        current_ema = (values[i] * multiplier) + (prev_ema * one_minus_mult)
        result[i] = current_ema
        prev_ema = current_ema

    return result


def calculate_rsi(prices: list[Decimal], period: int = 14) -> list[Decimal | None]:
    """Calcula el Relative Strength Index (RSI) con suavizado estándar de Wilder.

    Args:
        prices: Serie cronológica de precios de cierre.
        period: Periodo del oscilador (predeterminado 14).

    Returns:
        Lista de valores RSI entre 0 y 100.
    """
    if period <= 0:
        raise ValueError(f"El periodo del RSI debe ser mayor a 0, recibido: {period}")

    result: list[Decimal | None] = [None] * len(prices)
    if len(prices) <= period:
        return result

    # 1. Calcular cambios de precio
    gains: list[Decimal] = []
    losses: list[Decimal] = []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i - 1]
        if diff > Decimal("0"):
            gains.append(diff)
            losses.append(Decimal("0"))
        else:
            gains.append(Decimal("0"))
            losses.append(abs(diff))

    # 2. Primera media simple de ganancias y pérdidas
    avg_gain = sum(gains[:period], Decimal("0")) / Decimal(str(period))
    avg_loss = sum(losses[:period], Decimal("0")) / Decimal(str(period))

    if avg_loss == Decimal("0"):
        result[period] = Decimal("100.0") if avg_gain > Decimal("0") else Decimal("50.0")
    else:
        rs = avg_gain / avg_loss
        result[period] = Decimal("100.0") - (Decimal("100.0") / (Decimal("1.0") + rs))

    # 3. Suavizado de Wilder para los periodos subsecuentes
    period_dec = Decimal(str(period))
    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period_dec - Decimal("1"))) + gains[i]) / period_dec
        avg_loss = ((avg_loss * (period_dec - Decimal("1"))) + losses[i]) / period_dec

        idx = i + 1
        if avg_loss == Decimal("0"):
            result[idx] = Decimal("100.0") if avg_gain > Decimal("0") else Decimal("50.0")
        else:
            rs = avg_gain / avg_loss
            result[idx] = Decimal("100.0") - (Decimal("100.0") / (Decimal("1.0") + rs))

    return result


def calculate_atr(
    highs: list[Decimal],
    lows: list[Decimal],
    closes: list[Decimal],
    period: int = 14,
) -> list[Decimal | None]:
    """Calcula el Average True Range (ATR) con el método de suavizado de Wilder.

    Args:
        highs: Precios máximos de cada vela.
        lows: Precios mínimos de cada vela.
        closes: Precios de cierre de cada vela.
        period: Periodo de cálculo (predeterminado 14).

    Returns:
        Lista con los valores del ATR.
    """
    n = len(closes)
    if len(highs) != n or len(lows) != n:
        raise ValueError("Las listas de highs, lows y closes deben tener la misma longitud.")
    if period <= 0:
        raise ValueError(f"El periodo debe ser mayor a 0, recibido: {period}")

    result: list[Decimal | None] = [None] * n
    if n < period:
        return result

    # 1. Calcular True Range (TR)
    true_ranges: list[Decimal] = [highs[0] - lows[0]]
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        true_ranges.append(tr)

    # 2. Primer valor de ATR como SMA de los primeros True Ranges
    current_atr = sum(true_ranges[:period], Decimal("0")) / Decimal(str(period))
    result[period - 1] = current_atr

    # 3. Suavizado de Wilder
    period_dec = Decimal(str(period))
    for i in range(period, n):
        current_atr = ((current_atr * (period_dec - Decimal("1"))) + true_ranges[i]) / period_dec
        result[i] = current_atr

    return result


def find_pivot_lows(
    lows: list[Decimal],
    left_bars: int = 2,
    right_bars: int = 2,
) -> list[tuple[int, Decimal]]:
    """Encuentra pivotes mínimos (Swing Lows) en una serie de precios.

    Un pivote mínimo en el índice `i` cumple que `lows[i] <= lows[i - k]` para todos los
    k en `[1, left_bars]` y `lows[i] <= lows[i + k]` para todos los k en `[1, right_bars]`.

    Args:
        lows: Lista de precios mínimos.
        left_bars: Cantidad de velas requeridas a la izquierda.
        right_bars: Cantidad de velas requeridas a la derecha.

    Returns:
        Lista de tuplas `(indice, precio_minimo)`.
    """
    pivots: list[tuple[int, Decimal]] = []
    n = len(lows)
    if n < left_bars + right_bars + 1:
        return pivots

    for i in range(left_bars, n - right_bars):
        current = lows[i]
        is_pivot = True
        for left_idx in range(1, left_bars + 1):
            if lows[i - left_idx] < current:
                is_pivot = False
                break
        if not is_pivot:
            continue
        for r in range(1, right_bars + 1):
            if lows[i + r] <= current:
                is_pivot = False
                break
        if is_pivot:
            pivots.append((i, current))

    return pivots
