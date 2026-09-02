"""Tests de la Máquina de Estados y Circuit Breakers del Portfolio Risk Engine."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import pytest

from chimuelo_prime.paper_trading.decision_models import RiskStateEnum
from chimuelo_prime.paper_trading.risk_engine import PortfolioRiskEngine


def test_consecutive_losses_triggers_reduced_sizing():
    """Verifica que 4 pérdidas consecutivas activen REDUCED_SIZING."""
    risk = PortfolioRiskEngine(initial_equity=Decimal("100.00"))
    assert risk.current_state == RiskStateEnum.NORMAL
    assert risk.get_effective_risk_pct() == Decimal("0.025")

    t = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
    # Registrar 3 pérdidas
    risk.record_trade_result(Decimal("-0.50"), t)
    risk.record_trade_result(Decimal("-0.50"), t)
    risk.record_trade_result(Decimal("-0.50"), t)
    assert risk.consecutive_losses == 3
    assert risk.current_state == RiskStateEnum.NORMAL

    # 4ª pérdida activa reducción de riesgo
    risk.record_trade_result(Decimal("-0.50"), t)
    assert risk.consecutive_losses == 4
    assert risk.current_state == RiskStateEnum.REDUCED_SIZING
    assert risk.get_effective_risk_pct() == Decimal("0.0125")  # 1.25%

    # 1 victoria resetea el estado a NORMAL
    risk.record_trade_result(Decimal("2.00"), t)
    assert risk.consecutive_losses == 0
    assert risk.current_state == RiskStateEnum.NORMAL
    assert risk.get_effective_risk_pct() == Decimal("0.025")


def test_daily_drawdown_circuit_breaker():
    """Verifica que una pérdida diaria >= 3.0% active CIRCUIT_BREAKER_DAILY."""
    risk = PortfolioRiskEngine(initial_equity=Decimal("100.00"))
    t1 = datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)

    # Pérdida de $3.50 USD en el mismo día (3.5% DD)
    risk.record_trade_result(Decimal("-3.50"), t1)
    snapshot = risk.get_snapshot(t1)

    assert snapshot.current_state == RiskStateEnum.CIRCUIT_BREAKER_DAILY
    assert not snapshot.risk_allowed
    assert "Circuit Breaker" in (snapshot.rejection_reason or "")

    # Avanzar a las 00:00 UTC del día siguiente debe resetear el daily drawdown
    t2 = datetime(2026, 9, 2, 0, 0, 0, tzinfo=UTC)
    snapshot2 = risk.get_snapshot(t2)
    assert snapshot2.current_state == RiskStateEnum.NORMAL
    assert snapshot2.risk_allowed


def test_max_portfolio_drawdown_circuit_breaker():
    """Verifica que un Peak-to-Trough Drawdown >= 15.0% active CIRCUIT_BREAKER_MAX_DD."""
    risk = PortfolioRiskEngine(initial_equity=Decimal("100.00"))
    t = datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)

    # Pérdida acumulada del 16% ($16 USD)
    risk.record_trade_result(Decimal("-16.00"), t)
    snapshot = risk.get_snapshot(t)

    assert snapshot.current_state == RiskStateEnum.CIRCUIT_BREAKER_MAX_DD
    assert not snapshot.risk_allowed
    assert snapshot.peak_to_trough_drawdown_pct >= Decimal("15.0")
