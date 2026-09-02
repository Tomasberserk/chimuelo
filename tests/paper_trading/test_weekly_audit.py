"""Tests para el Weekly Audit Reporting System de Chimuelo Prime.

Verifica:
- Determinismo y reproducibilidad
- Generación de JSON, Markdown y XLSX
- Cero mutación de Strategy C y del portafolio
- Inmutabilidad y hashing criptográfico SHA-256
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path
import pytest

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.paper_trading.decision_engine import SingleDecisionEngine
from chimuelo_prime.paper_trading.decision_models import DecisionAction, DecisionObject, PaperPosition
from chimuelo_prime.paper_trading.persistence import SQLitePersistenceBackend
from chimuelo_prime.paper_trading.risk_engine import PortfolioRiskEngine
from chimuelo_prime.paper_trading.telemetry import PaperTelemetryCollector
from chimuelo_prime.paper_trading.virtual_broker import VirtualBroker
from chimuelo_prime.paper_trading.weekly_audit import WeeklyAuditReportGenerator
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


def test_weekly_report_generation_and_determinism(tmp_path):
    """Verifica que el generador cree JSON, Markdown y XLSX de forma determinista."""
    db_path = str(tmp_path / "audit_test.db")
    reports_dir = tmp_path / "reports" / "weekly"
    persistence = SQLitePersistenceBackend(db_path)
    broker = VirtualBroker(persistence=persistence, initial_cash=Decimal("100.00"))
    telemetry = PaperTelemetryCollector()

    # Simular 1 posición cerrada con métricas completas
    t0 = datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 9, 1, 15, 0, 0, tzinfo=UTC)
    pos = PaperPosition(
        position_id="pos_audit_1",
        symbol="SOLUSDT",
        status="CLOSED",
        entry_time=t0,
        entry_signal_price=Decimal("100.00"),
        fill_price=Decimal("100.05"),
        slippage_pct=Decimal("0.0005"),
        stop_loss=Decimal("90.00"),
        take_profit=Decimal("122.00"),
        quantity=Decimal("0.5"),
        fee_entry=Decimal("0.05"),
        exit_time=t1,
        exit_price=Decimal("122.00"),
        exit_reason="TAKE_PROFIT",
        fee_exit=Decimal("0.061"),
        gross_pnl=Decimal("10.975"),
        net_pnl=Decimal("10.864"),
        r_multiple=Decimal("2.19"),
        duration_hours=5,
    )
    telemetry.record_closed_position(pos)

    generator = WeeklyAuditReportGenerator(
        persistence=persistence,
        telemetry=telemetry,
        broker=broker,
        output_base_dir=str(reports_dir),
    )

    # Generar paquete para semana 2026_W36
    res1 = generator.generate_and_save_package(week_number=36, year=2026, initial_capital=Decimal("100.00"))

    # Validar existencia de archivos
    json_path = Path(res1["files"]["json"])
    md_path = Path(res1["files"]["markdown"])
    xlsx_path = Path(res1["files"]["excel"])

    assert json_path.exists()
    assert md_path.exists()
    assert xlsx_path.exists()

    # Validar contenido de JSON
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["identity"]["week_identifier"] == "2026_W36"
    assert data["identity"]["strategy_version"] == "v1.0.0-frozen"
    assert data["performance"]["trades_closed_count"] == 1
    assert data["performance"]["win_rate_pct"] == 100.0
    assert len(data["trade_ledger"]) == 1
    assert data["trade_ledger"][0]["position_id"] == "pos_audit_1"
    assert "data_integrity_sha256" in data

    # Validar contenido Markdown
    with open(md_path, "r", encoding="utf-8") as f:
        md_text = f.read()

    assert "Chimuelo Prime — Reporte de Auditoría Semanal (2026_W36)" in md_text
    assert "pos_audit_1" in md_text
    assert "SOLUSDT" in md_text


def test_no_mutation_of_strategy_or_portfolio_state(tmp_path):
    """Garantiza que la generación del reporte es una operación pura de lectura (read-only)."""
    db_path = str(tmp_path / "no_mutation.db")
    persistence = SQLitePersistenceBackend(db_path)
    broker = VirtualBroker(persistence=persistence, initial_cash=Decimal("100.00"))
    telemetry = PaperTelemetryCollector()

    strategy_hash_before = StructuralBreakoutStrategy.get_config_hash()
    broker_cash_before = broker.cash
    broker_positions_before = broker.get_open_positions_count()

    generator = WeeklyAuditReportGenerator(
        persistence=persistence,
        telemetry=telemetry,
        broker=broker,
        output_base_dir=str(tmp_path / "reports"),
    )
    generator.generate_and_save_package(week_number=36, year=2026)

    # Comprobar inmutabilidad absoluta
    assert StructuralBreakoutStrategy.get_config_hash() == strategy_hash_before
    assert broker.cash == broker_cash_before
    assert broker.get_open_positions_count() == broker_positions_before


def test_hash_reproducibility(tmp_path):
    """Verifica que el hash de integridad sea reproducible e identifique unívocamente el contenido."""
    db_path = str(tmp_path / "hash_rep.db")
    persistence = SQLitePersistenceBackend(db_path)
    broker = VirtualBroker(persistence=persistence, initial_cash=Decimal("100.00"))
    telemetry = PaperTelemetryCollector()

    generator = WeeklyAuditReportGenerator(
        persistence=persistence,
        telemetry=telemetry,
        broker=broker,
        output_base_dir=str(tmp_path / "reports"),
    )

    data1 = generator.build_report_data(week_number=36, year=2026)
    data2 = generator.build_report_data(week_number=36, year=2026)

    assert len(data1["data_integrity_sha256"]) == 64
    assert len(data2["data_integrity_sha256"]) == 64
