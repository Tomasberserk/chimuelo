"""Tests para el Portfolio Risk Engine, Exposición Proyectada y Recuperación Real."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import pytest

from chimuelo_prime.paper_trading.decision_models import (
    DecisionAction,
    RiskStateEnum,
    RiskStateSnapshot,
)
from chimuelo_prime.paper_trading.live_runner import LivePaperRunner
from chimuelo_prime.paper_trading.persistence import SQLitePersistenceBackend
from chimuelo_prime.paper_trading.risk_engine import PortfolioRiskEngine


def test_consecutive_losses_triggers_reduced_sizing():
    """Verifica que 4 pérdidas consecutivas activen REDUCED_SIZING sin sobrepasar el Daily DD."""
    risk = PortfolioRiskEngine(initial_equity=Decimal("100.00"))
    assert risk.current_state == RiskStateEnum.NORMAL
    assert risk.get_effective_risk_pct() == Decimal("0.025")

    t = datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)
    for _ in range(3):
        risk.record_trade_result(Decimal("-0.50"), t)
        assert risk.current_state == RiskStateEnum.NORMAL

    # Cuarta pérdida
    risk.record_trade_result(Decimal("-0.50"), t)
    assert risk.current_state == RiskStateEnum.REDUCED_SIZING
    assert risk.get_effective_risk_pct() == Decimal("0.0125")

    # Un trade ganador restablece el estado NORMAL
    risk.record_trade_result(Decimal("+5.00"), t)
    assert risk.current_state == RiskStateEnum.NORMAL
    assert risk.consecutive_losses == 0


def test_daily_drawdown_circuit_breaker():
    """Verifica que un drawdown diario >= 3% bloquee operaciones."""
    risk = PortfolioRiskEngine(initial_equity=Decimal("100.00"))
    t = datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)

    # Pérdida de $3.50 (3.5% del capital del día)
    risk.record_trade_result(Decimal("-3.50"), t)
    assert risk.current_state == RiskStateEnum.CIRCUIT_BREAKER_DAILY

    snap = risk.get_snapshot(current_time=t)
    assert not snap.risk_allowed
    assert "Circuit Breaker" in (snap.rejection_reason or "")


def test_max_portfolio_drawdown_circuit_breaker():
    """Verifica que un drawdown acumulado desde HWM >= 15% active CIRCUIT_BREAKER_MAX_DD."""
    risk = PortfolioRiskEngine(initial_equity=Decimal("100.00"))
    t = datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)

    # Capital cae a $84 (16% DD desde HWM $100)
    risk.record_trade_result(Decimal("-16.00"), t)
    assert risk.current_state == RiskStateEnum.CIRCUIT_BREAKER_MAX_DD

    snap = risk.get_snapshot(current_time=t)
    assert not snap.risk_allowed
    assert "CIRCUIT_BREAKER_MAX_DD" in (snap.rejection_reason or "")


def test_projected_exposure_blocks_new_trade():
    """Verifica que si exposición actual (40%) + nueva orden (25%) = 65% > 60%, sea bloqueada."""
    risk = PortfolioRiskEngine(initial_equity=Decimal("100.00"))
    t = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)

    # Exposición actual: $40 USD (40%)
    # Nueva orden propuesta: $25 USD (25%)
    # Total proyectado: $65 USD (65%) -> Debe bloquearse porque 65% > 60%
    snapshot = risk.get_snapshot(
        current_time=t,
        open_positions_count=1,
        total_exposure_usd=Decimal("40.00"),
        proposed_trade_notional=Decimal("25.00"),
    )

    assert not snapshot.risk_allowed
    assert "Límite de exposición total proyectada excedido" in (snapshot.rejection_reason or "")
    assert snapshot.total_exposure_pct == Decimal("65.00")


def test_risk_engine_recovery_real(tmp_path):
    """Verifica que un RiskEngine en estado crítico se guarde y recupere fielmente tras destruir la instancia."""
    db_file = str(tmp_path / "recovery_test.db")
    persistence = SQLitePersistenceBackend(db_path=db_file)

    # 1. Crear instancia y forzar estado REDUCED_SIZING con HWM y rachas
    risk_original = PortfolioRiskEngine(initial_equity=Decimal("100.00"))
    t = datetime(2026, 9, 1, 14, 0, 0, tzinfo=UTC)
    risk_original.record_trade_result(Decimal("+10.00"), t)  # Equity $110, HWM $110
    risk_original.record_trade_result(Decimal("-2.00"), t)
    risk_original.record_trade_result(Decimal("-2.00"), t)
    risk_original.record_trade_result(Decimal("-2.00"), t)
    risk_original.record_trade_result(Decimal("-2.00"), t)  # 4 pérdidas -> REDUCED_SIZING

    assert risk_original.current_state == RiskStateEnum.REDUCED_SIZING
    assert risk_original.consecutive_losses == 4
    assert risk_original.high_water_mark == Decimal("110.00")
    assert risk_original.current_equity == Decimal("102.00")

    # 2. Persistir snapshot
    snap = risk_original.get_snapshot(t)
    persistence.save_risk_state(
        snapshot=snap,
        timestamp=t,
        daily_start_equity=risk_original.daily_start_equity,
        current_day=risk_original.current_day,
        cooldown_until=risk_original.cooldown_until,
    )

    # 3. Destruir instancia original
    del risk_original

    # 4. Iniciar nueva instancia de LivePaperRunner conectada a la misma persistencia
    runner = LivePaperRunner(
        symbols=["BTCUSDT", "SOLUSDT"],
        initial_cash=Decimal("100.00"),
        persistence=persistence,
    )

    # 5. Verificar igualdad exacta del estado recuperado
    recovered_risk = runner.risk_engine
    assert recovered_risk.current_state == RiskStateEnum.REDUCED_SIZING
    assert recovered_risk.consecutive_losses == 4
    assert recovered_risk.high_water_mark == Decimal("110.00")
    assert recovered_risk.current_equity == Decimal("102.00")
    assert recovered_risk.current_day == date(2026, 9, 1)
