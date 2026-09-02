"""Tests de aislamiento estricto de salidas y ejecuciones concurrentes multi-símbolo."""

from datetime import UTC, datetime
from decimal import Decimal
import pytest

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.paper_trading.persistence import SQLitePersistenceBackend
from chimuelo_prime.paper_trading.virtual_broker import VirtualBroker


def create_candle(
    dt: datetime,
    low_p: str,
    high_p: str,
    close_p: str = "100.0",
) -> HistoricalCandle:
    return HistoricalCandle(
        timestamp=dt,
        open=Decimal("100.0"),
        high=Decimal(high_p),
        low=Decimal(low_p),
        close=Decimal(close_p),
        volume=Decimal("1000.0"),
    )


def test_two_symbol_concurrent_positions_and_exit_isolation(tmp_path):
    """Verifica que teniendo BTC y SOL abiertos, una vela de SOL JAMÁS cierre la posición de BTC."""
    db_file = str(tmp_path / "isolation_test.db")
    persistence = SQLitePersistenceBackend(db_path=db_file)
    broker = VirtualBroker(initial_cash=Decimal("200.00"), persistence=persistence)

    t0 = datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)

    # 1. Abrir posición en BTCUSDT (SL: 55,000, TP: 65,000)
    broker.execute_paper_order(
        decision_id="dec_btc_1",
        symbol="BTCUSDT",
        timestamp=t0,
        signal_price=Decimal("60000.00"),
        stop_loss=Decimal("55000.00"),
        take_profit=Decimal("65000.00"),
        quantity=Decimal("0.001"),
        risk_pct_used=Decimal("0.025"),
    )

    # 2. Abrir posición en SOLUSDT (SL: 90.00, TP: 120.00)
    broker.execute_paper_order(
        decision_id="dec_sol_1",
        symbol="SOLUSDT",
        timestamp=t0,
        signal_price=Decimal("100.00"),
        stop_loss=Decimal("90.00"),
        take_profit=Decimal("120.00"),
        quantity=Decimal("0.5"),
        risk_pct_used=Decimal("0.025"),
    )

    assert broker.get_open_positions_count() == 2
    assert "BTCUSDT" in broker._open_positions
    assert "SOLUSDT" in broker._open_positions

    # 3. Enviar una vela de SOL que toca el Stop Loss de SOL (Low = $85)
    t1 = datetime(2026, 9, 1, 11, 0, 0, tzinfo=UTC)
    sol_candle_crash = create_candle(t1, low_p="85.00", high_p="101.00", close_p="88.00")

    # Procesar salida específicamente para SOLUSDT
    closed_sol = broker.process_candle_for_exits("SOLUSDT", sol_candle_crash)

    # 4. Validar que SOL se cerró y BTC permanezca estrictamente abierta
    assert closed_sol is not None
    assert closed_sol.symbol == "SOLUSDT"
    assert closed_sol.exit_reason == "STOP_LOSS"
    assert "SOLUSDT" not in broker._open_positions

    # BTCUSDT DEBE SEGUIR ABIERTA
    assert "BTCUSDT" in broker._open_positions
    assert broker.get_open_positions_count() == 1

    # 5. Procesar vela normal de BTC no debe cerrar BTC
    btc_candle_normal = HistoricalCandle(
        timestamp=t1,
        open=Decimal("60000.00"),
        high=Decimal("61000.00"),
        low=Decimal("58000.00"),
        close=Decimal("59500.00"),
        volume=Decimal("500.0"),
    )
    closed_btc = broker.process_candle_for_exits("BTCUSDT", btc_candle_normal)
    assert closed_btc is None
    assert "BTCUSDT" in broker._open_positions
    assert broker.get_open_positions_count() == 1

    # 6. Procesar símbolo no abierto (ej. ETHUSDT) retorna None de forma segura
    assert broker.process_candle_for_exits("ETHUSDT", btc_candle_normal) is None
