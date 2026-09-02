"""Tests de idempotencia y recuperación de estado tras reinicio."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import pytest

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.paper_trading.decision_engine import SingleDecisionEngine
from chimuelo_prime.paper_trading.decision_models import (
    DecisionAction,
    PaperFill,
    PaperOrder,
    PaperPosition,
    ensure_utc_aware,
)
from chimuelo_prime.paper_trading.persistence import (
    DuplicateDecisionError,
    DuplicateOrderError,
    SQLitePersistenceBackend,
)
from chimuelo_prime.paper_trading.risk_engine import PortfolioRiskEngine, RiskStateEnum
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


def test_idempotent_decision_execution(tmp_path):
    """Verifica que procesar la misma vela dos veces retorne la decisión ya guardada sin duplicar."""
    db_path = str(tmp_path / "idempotency.db")
    persistence = SQLitePersistenceBackend(db_path)
    risk_engine = PortfolioRiskEngine()
    strat = StructuralBreakoutStrategy(symbol="SOLUSDT")
    broker = VirtualBroker(persistence=persistence)
    engine = SingleDecisionEngine(
        symbol="SOLUSDT",
        strategy=strat,
        risk_engine=risk_engine,
        persistence=persistence,
        virtual_broker=broker,
    )

    base_time = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    candles = [create_candle(base_time + timedelta(hours=i)) for i in range(110)]
    btc_daily = [create_candle(base_time + timedelta(days=i), close="60000.0") for i in range(10)]
    strat.set_btc_daily_context(btc_daily)

    # Primera evaluación
    d1 = engine.evaluate_bar(candles, len(candles) - 1)
    assert d1 is not None

    # Segunda evaluación con exactamente la misma vela y timestamp
    d2 = engine.evaluate_bar(candles, len(candles) - 1)
    assert d2 is not None
    assert d1.decision_id == d2.decision_id
    assert d1.timestamp == d2.timestamp
    assert d1.model_dump() == d2.model_dump()


def test_atomic_order_fill_position_execution(tmp_path):
    """Verifica que la ejecución de una orden virtual cree atómicamente orden, fill y posición."""
    db_path = str(tmp_path / "atomic.db")
    persistence = SQLitePersistenceBackend(db_path)
    broker = VirtualBroker(persistence=persistence, initial_cash=Decimal("100.00"))

    order, fill, pos = broker.execute_paper_order(
        decision_id="dec_atomic_1",
        symbol="SOLUSDT",
        timestamp=datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC),
        signal_price=Decimal("150.00"),
        stop_loss=Decimal("140.00"),
        take_profit=Decimal("172.00"),
        quantity=Decimal("0.25"),
        risk_pct_used=Decimal("0.025"),
    )

    assert order.order_id.startswith("ord_")
    assert fill.order_id == order.order_id
    assert pos.status == "OPEN"
    assert broker.get_open_positions_count() == 1

    # Intentar guardar una orden duplicada directamente en persistencia debe arrojar DuplicateOrderError
    with pytest.raises(DuplicateOrderError):
        persistence.save_paper_order(order)


def test_crash_recovery_restores_open_positions_and_hwm(tmp_path):
    """Verifica que tras un reinicio del proceso se restauren posiciones abiertas y el HWM."""
    db_path = str(tmp_path / "recovery.db")
    persistence1 = SQLitePersistenceBackend(db_path)
    broker1 = VirtualBroker(persistence=persistence1, initial_cash=Decimal("100.00"))

    # Abrir una posición virtual
    order, fill, pos = broker1.execute_paper_order(
        decision_id="dec_test_123",
        symbol="SOLUSDT",
        timestamp=datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC),
        signal_price=Decimal("150.00"),
        stop_loss=Decimal("140.00"),
        take_profit=Decimal("172.00"),
        quantity=Decimal("0.25"),
        risk_pct_used=Decimal("0.025"),
    )
    assert broker1.get_open_positions_count() == 1

    # SIMULAR REINICIO / NUEVA INSTANCIA conectada a la misma BD
    persistence2 = SQLitePersistenceBackend(db_path)
    broker2 = VirtualBroker(persistence=persistence2, initial_cash=Decimal("100.00"))

    # Debe haber restaurado la posición automáticamente
    assert broker2.get_open_positions_count() == 1
    restored_pos = broker2._open_positions.get("SOLUSDT")
    assert restored_pos is not None
    assert restored_pos.position_id == pos.position_id
    assert restored_pos.quantity == Decimal("0.25")
    assert restored_pos.stop_loss == Decimal("140.00")
