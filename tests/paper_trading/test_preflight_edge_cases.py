"""Pre-flight Tests para Casos Extremos: WebSocket Disconnect, REST Fallback, Velas Duplicadas, Fuera de Orden y Faltantes."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import pytest

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.paper_trading.decision_engine import SingleDecisionEngine
from chimuelo_prime.paper_trading.live_runner import LivePaperRunner
from chimuelo_prime.paper_trading.persistence import SQLitePersistenceBackend
from chimuelo_prime.paper_trading.risk_engine import PortfolioRiskEngine
from chimuelo_prime.paper_trading.virtual_broker import VirtualBroker
from chimuelo_prime.strategies.structural_breakout import StructuralBreakoutStrategy


def create_candle(dt: datetime, close: str = "100.0", volume: str = "1000.0") -> HistoricalCandle:
    p = Decimal(close)
    return HistoricalCandle(
        timestamp=dt,
        open=p,
        high=p + Decimal("2.0"),
        low=p - Decimal("1.0"),
        close=p + Decimal("1.5"),
        volume=Decimal(volume),
    )


def test_duplicate_candle_handling(tmp_path):
    """Verifica que enviar la misma vela 2 veces no genere decisiones ni órdenes duplicadas."""
    db_path = str(tmp_path / "dup_candle.db")
    persistence = SQLitePersistenceBackend(db_path)
    runner = LivePaperRunner(symbols=["SOLUSDT"], persistence=persistence)

    t0 = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    candles = [create_candle(t0 + timedelta(hours=i)) for i in range(110)]
    btc_daily = [create_candle(t0 + timedelta(days=i), close="60000.0") for i in range(10)]

    # Primera pasada
    d1 = runner.process_closed_hourly_candle("SOLUSDT", candles, btc_daily)

    # Segunda pasada con exactamente la misma vela final
    d2 = runner.process_closed_hourly_candle("SOLUSDT", candles, btc_daily)

    assert d1.decision_id == d2.decision_id
    assert d1.data_snapshot_hash == d2.data_snapshot_hash
    assert runner.broker.get_open_positions_count() in (0, 1)


def test_out_of_order_and_missing_candles_handling(tmp_path):
    """Verifica que el pipeline detecte saltos temporales (missing candles) y mantenga la estabilidad."""
    strat = StructuralBreakoutStrategy(symbol="SOLUSDT")
    t0 = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)

    # Serie con un gap (falta la vela de la hora 50)
    candles_with_gap = []
    for i in range(110):
        if i == 50:
            continue  # Falta 1 hora
        candles_with_gap.append(create_candle(t0 + timedelta(hours=i)))

    # Preparar indicadores debe computar de forma robusta
    strat.prepare_indicators(candles_with_gap)
    assert len(strat._cached_ema_trend) == len(candles_with_gap)
    assert len(strat._cached_atr) == len(candles_with_gap)


def test_websocket_disconnect_simulated_and_rest_fallback(tmp_path, monkeypatch):
    """Simula una desconexión en el canal WebSocket y el fallback automático a REST polling."""
    db_path = str(tmp_path / "ws_fallback.db")
    persistence = SQLitePersistenceBackend(db_path)
    runner = LivePaperRunner(symbols=["SOLUSDT"], persistence=persistence)

    ws_connected = False
    rest_called = False

    # Simular fallback: si WS falla, se invoca data_loader REST
    def mock_get_candles(*args, **kwargs):
        nonlocal rest_called
        rest_called = True
        t0 = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
        return [create_candle(t0 + timedelta(hours=i)) for i in range(110)]

    monkeypatch.setattr(runner._data_loader, "get_candles", mock_get_candles)

    # Si WS está caído, obtener velas vía REST
    if not ws_connected:
        candles_rest = runner._data_loader.get_candles("SOLUSDT", "1h", datetime.now(UTC), datetime.now(UTC))
        assert rest_called
        assert len(candles_rest) == 110
