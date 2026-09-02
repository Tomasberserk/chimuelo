"""Tests de validación de velas cerradas (Zero Unclosed Candles)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import pytest

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.paper_trading.decision_engine import (
    CandleNotClosedError,
    SingleDecisionEngine,
)
from chimuelo_prime.paper_trading.risk_engine import PortfolioRiskEngine
from chimuelo_prime.strategies.structural_breakout import StructuralBreakoutStrategy


def test_unclosed_candle_rejected_by_engine():
    """Verifica que una vela cuyo tiempo de cierre aún no ha ocurrido sea rechazada con CandleNotClosedError."""
    strat = StructuralBreakoutStrategy(symbol="SOLUSDT")
    risk = PortfolioRiskEngine()
    engine = SingleDecisionEngine(
        symbol="SOLUSDT",
        strategy=strat,
        risk_engine=risk,
        validate_closed=True,
    )

    # Crear una vela iniciada hace 10 minutos (aún en curso)
    now_utc = datetime.now(UTC)
    unclosed_time = now_utc - timedelta(minutes=10)

    # Generar 120 velas anteriores para que los indicadores no fallen por longitud
    candles = []
    for i in range(120):
        t = unclosed_time - timedelta(hours=(120 - i))
        candles.append(
            HistoricalCandle(
                timestamp=t,
                open=Decimal("100.0"),
                high=Decimal("105.0"),
                low=Decimal("95.0"),
                close=Decimal("102.0"),
                volume=Decimal("1000.0"),
            )
        )
    # Agregar la vela no cerrada como última barra
    candles.append(
        HistoricalCandle(
            timestamp=unclosed_time,
            open=Decimal("102.0"),
            high=Decimal("106.0"),
            low=Decimal("101.0"),
            close=Decimal("105.0"),
            volume=Decimal("500.0"),
        )
    )

    with pytest.raises(CandleNotClosedError, match="no ha cerrado"):
        engine.evaluate_bar(candles, len(candles) - 1)
