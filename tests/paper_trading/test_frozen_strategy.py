"""Tests de validación para StructuralBreakoutStrategy (v1.0.0-frozen)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import pytest

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.paper_trading.decision_models import ensure_utc_aware
from chimuelo_prime.strategies.structural_breakout import StructuralBreakoutStrategy


def create_mock_candle(
    dt: datetime,
    open_p: str = "100.0",
    high_p: str = "105.0",
    low_p: str = "98.0",
    close_p: str = "104.0",
    volume: str = "1000.0",
) -> HistoricalCandle:
    return HistoricalCandle(
        timestamp=dt,
        open=Decimal(open_p),
        high=Decimal(high_p),
        low=Decimal(low_p),
        close=Decimal(close_p),
        volume=Decimal(volume),
    )


def test_timestamp_naive_rejection():
    """Verifica que los timestamps naive sean estrictamente rechazados."""
    naive_dt = datetime(2026, 9, 1, 12, 0, 0)
    with pytest.raises(ValueError, match="Timestamp naive no permitido"):
        ensure_utc_aware(naive_dt)

    aware_dt = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
    result = ensure_utc_aware(aware_dt)
    assert result.tzinfo == UTC


def test_config_hash_determinism():
    """Verifica que el hash de configuración sea determinista e inmutable."""
    h1 = StructuralBreakoutStrategy.get_config_hash()
    h2 = StructuralBreakoutStrategy.get_config_hash()
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex length


def test_zero_daily_lookahead():
    """Verifica que las decisiones del día D utilicen exclusivamente la vela diaria D-1."""
    strat = StructuralBreakoutStrategy(symbol="SOLUSDT")

    # Crear velas diarias para BTC
    d1 = datetime(2026, 8, 30, 0, 0, 0, tzinfo=UTC)
    d2 = datetime(2026, 8, 31, 0, 0, 0, tzinfo=UTC)
    d3 = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)

    btc_daily = [
        create_mock_candle(d1, close_p="60000.0"),
        create_mock_candle(d2, close_p="65000.0"),  # D-1 para 1 de Septiembre
        create_mock_candle(d3, close_p="50000.0"),  # Día actual (Aún abierto/en curso)
    ]
    strat.set_btc_daily_context(btc_daily)

    # Una vela horaria de las 14:00 del 1 de Septiembre debe consultar la fecha 2026-08-31
    info = strat._btc_daily_map.get(d2.date())
    assert info is not None
    assert info[0] == Decimal("65000.0")  # Cierre de D-1


def test_gate_rejection_when_btc_bearish():
    """Verifica que la estrategia rechace señales si BTC está en régimen bajista (Gate 5)."""
    strat = StructuralBreakoutStrategy(symbol="SOLUSDT")

    base_time = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    # Generar 120 velas horarias alcistas
    candles = []
    for i in range(120):
        t = base_time + timedelta(hours=i)
        p = Decimal("100.0") + Decimal(str(i * 0.5))
        candles.append(
            create_mock_candle(
                t,
                open_p=str(p - Decimal("1.0")),
                high_p=str(p + Decimal("2.0")),
                low_p=str(p - Decimal("1.0")),
                close_p=str(p + Decimal("1.8")),
                volume="2000.0",
            )
        )

    # Contexto BTC bajista
    btc_daily = [
        create_mock_candle(datetime(2026, 8, 31, 0, 0, 0, tzinfo=UTC), close_p="10000.0")  # Muy por debajo de EMA50
    ]
    strat.set_btc_daily_context(btc_daily)

    filters, signal = strat.evaluate_gates(candles, len(candles) - 1)
    assert not filters.btc_macro_bullish
    assert signal is None


def test_config_hash_mutation_detection(monkeypatch):
    """Verifica que modificar cualquier parámetro de Strategy C altere el config_hash."""
    original_hash = StructuralBreakoutStrategy.get_config_hash()

    # Mutar LOOKBACK_RESISTANCE
    monkeypatch.setattr(StructuralBreakoutStrategy, "LOOKBACK_RESISTANCE", 21)
    mutated_hash_1 = StructuralBreakoutStrategy.get_config_hash()
    assert mutated_hash_1 != original_hash

    # Mutar VOLUME_SMA_MULT
    monkeypatch.setattr(StructuralBreakoutStrategy, "LOOKBACK_RESISTANCE", 20)
    monkeypatch.setattr(StructuralBreakoutStrategy, "VOLUME_SMA_MULT", Decimal("1.25"))
    mutated_hash_2 = StructuralBreakoutStrategy.get_config_hash()
    assert mutated_hash_2 != original_hash

    # Mutar TAKE_PROFIT_RATIO
    monkeypatch.setattr(StructuralBreakoutStrategy, "VOLUME_SMA_MULT", Decimal("1.20"))
    monkeypatch.setattr(StructuralBreakoutStrategy, "TAKE_PROFIT_RATIO", Decimal("2.50"))
    mutated_hash_3 = StructuralBreakoutStrategy.get_config_hash()
    assert mutated_hash_3 != original_hash
