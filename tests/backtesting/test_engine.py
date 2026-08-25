"""Tests unitarios para el motor de simulación de backtesting (M6)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.backtesting.engine import BacktestSimulator
from chimuelo_prime.exchange_config.models import SymbolConfig, SymbolFilters


@pytest.fixture
def test_filters() -> SymbolFilters:
    """Filtros simplificados de prueba."""
    return SymbolFilters(
        symbol="BTCUSDT",
        tick_size=Decimal("1.00"),
        min_price=Decimal("1.00"),
        max_price=Decimal("100000.00"),
        step_size=Decimal("0.001"),
        min_qty=Decimal("0.001"),
        max_qty=Decimal("100.00"),
        min_notional=Decimal("10.00"),
        pct_up=Decimal("5"),
        pct_down=Decimal("0.2"),
    )


@pytest.fixture
def test_config(test_filters: SymbolFilters) -> SymbolConfig:
    """Configuración del grid simplificada para tests (3 niveles entre 90 y 120)."""
    return SymbolConfig(
        filters=test_filters,
        upper_bound=Decimal("120.00"),
        lower_bound=Decimal("90.00"),
        grid_levels=3,
        capital_per_order=Decimal("50.00"),  # Suficiente para superar min_notional
    )


def test_engine_strict_mode(test_config: SymbolConfig) -> None:
    """Verifica la simulación paso a paso en modo ESTRICTO (M5).

    Niveles calculados con spacing de 10:
      - Nivel 0: lower=90, upper=100, qty=0.555 (50/90 rounded)
      - Nivel 1: lower=100, upper=110, qty=0.500 (50/100 rounded)
      - Nivel 2: lower=110, upper=120, qty=0.454 (50/110 rounded)

    Camino del precio simulado (Spot inicial = 105):
      - Candle 0: Open=105, High=105, Low=105, Close=105 (Inicio)
        Niveles activos BUY inicialmente: Nivel 0 (lower=90) y Nivel 1 (lower=100) (ambos < 105)
      - Candle 1: Open=105, High=105, Low=95, Close=95
        Nivel 1 BUY ejecuta (Low 95 <= lower 100).
      - Candle 2: Open=95, High=95, Low=88, Close=88
        Nivel 0 BUY ejecuta (Low 88 <= lower 90).
      - Candle 3: Open=88, High=102, Low=88, Close=102
        Nivel 0 SELL ejecuta (High 102 >= upper 100) y Nivel 1 SELL ejecuta (High 102 >= upper 110? No, 102 < 110)
      - Candle 4: Open=102, High=115, Low=102, Close=115
        Nivel 1 SELL ejecuta (High 115 >= upper 110).
    """
    candles = [
        HistoricalCandle(
            timestamp=datetime(2024, 5, 14, 0, 0),
            open=Decimal("105.00"),
            high=Decimal("105.00"),
            low=Decimal("105.00"),
            close=Decimal("105.00"),
            volume=Decimal("1.0"),
        ),
        HistoricalCandle(
            timestamp=datetime(2024, 5, 14, 1, 0),
            open=Decimal("105.00"),
            high=Decimal("105.00"),
            low=Decimal("95.00"),
            close=Decimal("95.00"),
            volume=Decimal("1.0"),
        ),
        HistoricalCandle(
            timestamp=datetime(2024, 5, 14, 2, 0),
            open=Decimal("95.00"),
            high=Decimal("95.00"),
            low=Decimal("88.00"),
            close=Decimal("88.00"),
            volume=Decimal("1.0"),
        ),
        HistoricalCandle(
            timestamp=datetime(2024, 5, 14, 3, 0),
            open=Decimal("88.00"),
            high=Decimal("102.00"),
            low=Decimal("88.00"),
            close=Decimal("102.00"),
            volume=Decimal("1.0"),
        ),
        HistoricalCandle(
            timestamp=datetime(2024, 5, 14, 4, 0),
            open=Decimal("102.00"),
            high=Decimal("115.00"),
            low=Decimal("102.00"),
            close=Decimal("115.00"),
            volume=Decimal("1.0"),
        ),
    ]

    # Ejecutar en Modo Strict
    simulator = BacktestSimulator(
        config=test_config,
        candles=candles,
        initial_cash=Decimal("200.00"),
        fee_rate=Decimal("0.0"),
    )
    report = simulator.run(recreate_buy_on_sell_fill=False)

    # Validaciones generales del reporte
    assert report.symbol == "BTCUSDT"
    assert report.initial_cash == Decimal("200.00")
    assert report.recreate_buy_on_sell_fill is False
    assert len(report.trades) == 2  # Dos trades completados: nivel 0 y nivel 1

    # Validar trade de Nivel 0
    trade_0 = [t for t in report.trades if t.level_index == 0][0]
    assert trade_0.buy_price == Decimal("90.00")
    assert trade_0.sell_price == Decimal("100.00")
    # PnL = (100 - 90) * qty. qty = round_qty(50 / 90) = 0.555
    assert trade_0.pnl == Decimal("5.55")

    # Validar trade de Nivel 1
    trade_1 = [t for t in report.trades if t.level_index == 1][0]
    assert trade_1.buy_price == Decimal("100.00")
    assert trade_1.sell_price == Decimal("110.00")
    # qty = round_qty(50 / 100) = 0.500. PnL = (110 - 100) * 0.500 = 5.00
    assert trade_1.pnl == Decimal("5.00")

    # Verificar que no quedan posiciones abiertas (inventario es 0)
    assert report.final_cash == Decimal("210.55")  # 200 + 5.55 + 5.00
    assert report.final_equity == Decimal("210.55")
    assert report.total_return_pct == Decimal("5.275")  # (10.55 / 200) * 100


def test_engine_continuous_mode(test_config: SymbolConfig) -> None:
    """Verifica que el modo continuo re-coloque BUYs al vender.

    Nivel 1: lower=100, upper=110, qty=0.500
    Camino del precio:
      - Candle 0: Open=105 (Inicio)
      - Candle 1: Low=95 (Compra Nivel 1)
      - Candle 2: High=115 (Venta Nivel 1 -> Se crea nuevo BUY a 100)
      - Candle 3: Low=95 (Segunda Compra Nivel 1)
      - Candle 4: High=115 (Segunda Venta Nivel 1)
    """
    candles = [
        HistoricalCandle(
            timestamp=datetime(2024, 5, 14, 0, 0),
            open=Decimal("105.00"),
            high=Decimal("105.00"),
            low=Decimal("105.00"),
            close=Decimal("105.00"),
            volume=Decimal("1.0"),
        ),
        HistoricalCandle(
            timestamp=datetime(2024, 5, 14, 1, 0),
            open=Decimal("105.00"),
            high=Decimal("105.00"),
            low=Decimal("95.00"),
            close=Decimal("95.00"),
            volume=Decimal("1.0"),
        ),
        HistoricalCandle(
            timestamp=datetime(2024, 5, 14, 2, 0),
            open=Decimal("95.00"),
            high=Decimal("115.00"),
            low=Decimal("95.00"),
            close=Decimal("115.00"),
            volume=Decimal("1.0"),
        ),
        HistoricalCandle(
            timestamp=datetime(2024, 5, 14, 3, 0),
            open=Decimal("115.00"),
            high=Decimal("115.00"),
            low=Decimal("95.00"),
            close=Decimal("95.00"),
            volume=Decimal("1.0"),
        ),
        HistoricalCandle(
            timestamp=datetime(2024, 5, 14, 4, 0),
            open=Decimal("95.00"),
            high=Decimal("115.00"),
            low=Decimal("95.00"),
            close=Decimal("115.00"),
            volume=Decimal("1.0"),
        ),
    ]

    simulator = BacktestSimulator(
        config=test_config,
        candles=candles,
        initial_cash=Decimal("200.00"),
        fee_rate=Decimal("0.0"),
    )
    report = simulator.run(recreate_buy_on_sell_fill=True)

    # En este camino, el Nivel 1 ejecutó dos veces y el Nivel 0 ejecutó dos veces.
    # Nivel 1: dos compras/ventas
    # Nivel 0: lower=90, upper=100.
    # Candle 1 (Low 95): compra Nivel 1.
    # Candle 2 (Low 95 -> High 115): venta Nivel 1. Nivel 0 no compra porque Low es 95 (> 90).
    # Candle 3 (Low 95): compra Nivel 1.
    # Candle 4 (Low 95 -> High 115): venta Nivel 1.
    # Así, Nivel 1 completó 2 trades.
    n1_trades = [t for t in report.trades if t.level_index == 1]
    assert len(n1_trades) == 3
    for t in n1_trades:
        assert t.buy_price == Decimal("100.00")
        assert t.sell_price == Decimal("110.00")
        assert t.pnl == Decimal("5.00")


def test_engine_handles_commission_fees(test_config: SymbolConfig) -> None:
    """Verifica que se apliquen las comisiones en compras y ventas."""
    candles = [
        HistoricalCandle(
            timestamp=datetime(2024, 5, 14, 0, 0),
            open=Decimal("105.00"),
            high=Decimal("105.00"),
            low=Decimal("105.00"),
            close=Decimal("105.00"),
            volume=Decimal("1.0"),
        ),
        HistoricalCandle(
            timestamp=datetime(2024, 5, 14, 1, 0),
            open=Decimal("105.00"),
            high=Decimal("105.00"),
            low=Decimal("95.00"),
            close=Decimal("95.00"),
            volume=Decimal("1.0"),
        ),
        HistoricalCandle(
            timestamp=datetime(2024, 5, 14, 2, 0),
            open=Decimal("95.00"),
            high=Decimal("115.00"),
            low=Decimal("95.00"),
            close=Decimal("115.00"),
            volume=Decimal("1.0"),
        ),
    ]

    # fee_rate = 0.001 (0.1%)
    # Nivel 1: lower=100, upper=110, qty=0.500
    # Compra: costo = 50.00. Comisión = 50.00 * 0.001 = 0.05. Total costo = 50.05.
    # Venta: ingreso = 55.00. Comisión = 55.00 * 0.001 = 0.055. Total ingreso = 54.945.
    # Net PnL = 54.945 - 50.05 = 4.895
    simulator = BacktestSimulator(
        config=test_config,
        candles=candles,
        initial_cash=Decimal("200.00"),
        fee_rate=Decimal("0.001"),
    )
    report = simulator.run(recreate_buy_on_sell_fill=False)

    assert len(report.trades) == 1
    trade = report.trades[0]
    assert trade.pnl == Decimal("4.895")
    assert report.final_cash == Decimal("204.895")
