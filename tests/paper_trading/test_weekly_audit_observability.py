"""Tests para observabilidad avanzada del Weekly Audit Reporting System.

Verifica:
- Determinación de Git Commit SHA y marcado de CODE_VERSION_STATUS = ERROR si es desconocido.
- Fronteras canónicas de semana ISO (period_start / period_end).
- Explicación de período inicial sin actividad (INITIAL_OBSERVATION_WINDOW / NO_TRADING_ACTIVITY_YET).
- Detección de frescura / datos obsoletos (Runner Health & Data Freshness).
- Estado de muestra insuficiente en el Drift Tracker (INSUFFICIENT_SAMPLE).
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
import pytest

from chimuelo_prime.paper_trading.drift_tracker import BacktestLiveDriftTracker
from chimuelo_prime.paper_trading.persistence import SQLitePersistenceBackend
from chimuelo_prime.paper_trading.telemetry import PaperTelemetryCollector
from chimuelo_prime.paper_trading.virtual_broker import VirtualBroker
from chimuelo_prime.paper_trading.weekly_audit import (
    WeeklyAuditReportGenerator,
    get_canonical_week_bounds,
    get_git_commit_sha_and_status,
)


def test_canonical_week_boundaries():
    """Verifica que el cálculo de semanas ISO genere fronteras canónicas de Lunes 00:00 a Domingo 23:59:59 UTC."""
    # Semana 36 de 2026 (del Lunes 31 de Agosto al Domingo 6 de Septiembre de 2026)
    p_start, p_end = get_canonical_week_bounds(2026, 36)

    assert p_start.isoweekday() == 1  # Lunes
    assert p_start.hour == 0 and p_start.minute == 0 and p_start.second == 0
    assert p_start.tzinfo == UTC

    assert p_end.isoweekday() == 7  # Domingo
    assert p_end.hour == 23 and p_end.minute == 59 and p_end.second == 59
    assert p_end.tzinfo == UTC


def test_git_commit_sha_and_error_status(monkeypatch):
    """Verifica que si no se puede determinar el Git SHA, se marque CODE_VERSION_STATUS = ERROR."""
    # Simular entorno sin git ni variables de entorno
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
    monkeypatch.delenv("GIT_COMMIT_SHA", raising=False)
    monkeypatch.delenv("COMMIT_SHA", raising=False)
    monkeypatch.delenv("GITHUB_SHA", raising=False)

    def mock_subprocess_error(*args, **kwargs):
        raise FileNotFoundError("git not found")

    monkeypatch.setattr("subprocess.run", mock_subprocess_error)

    sha, status = get_git_commit_sha_and_status()
    assert status == "ERROR"
    assert sha == "ERROR_UNDETERMINED"


def test_zero_trading_activity_and_initial_observation_window(tmp_path):
    """Verifica que cuando candles = 0 y trades = 0, el reporte muestre INITIAL_OBSERVATION_WINDOW y NO_TRADING_ACTIVITY_YET."""
    db_path = str(tmp_path / "zero_act.db")
    persistence = SQLitePersistenceBackend(db_path)
    broker = VirtualBroker(persistence=persistence, initial_cash=Decimal("100.00"))
    telemetry = PaperTelemetryCollector()

    generator = WeeklyAuditReportGenerator(
        persistence=persistence,
        telemetry=telemetry,
        broker=broker,
        output_base_dir=str(tmp_path / "reports"),
    )

    report = generator.build_report_data(week_number=36, year=2026)

    assert report["identity"]["observation_status"] == "INITIAL_OBSERVATION_WINDOW"
    assert report["identity"]["activity_status"] == "NO_TRADING_ACTIVITY_YET"
    assert "Período inicial de observación" in report["performance"]["metrics_interpretation"]
    assert report["runner_health"]["runner_status"] == "RUNNING"


def test_stale_data_detection(tmp_path):
    """Verifica que si los datos tienen retraso se reporte STALE en data_freshness."""
    db_path = str(tmp_path / "stale_test.db")
    persistence = SQLitePersistenceBackend(db_path)
    broker = VirtualBroker(persistence=persistence, initial_cash=Decimal("100.00"))
    telemetry = PaperTelemetryCollector()

    generator = WeeklyAuditReportGenerator(
        persistence=persistence,
        telemetry=telemetry,
        broker=broker,
        output_base_dir=str(tmp_path / "reports"),
    )

    # Simular que pasaron 2 horas (7200s) desde el último market data
    override = {
        "seconds_since_last_market_data": 7200.0,
        "seconds_since_last_processed_candle": 7200.0,
        "stale_data_status": "STALE",
    }
    report = generator.build_report_data(week_number=36, year=2026, runner_health_override=override)

    assert report["runner_health"]["stale_data_status"] == "STALE"
    assert report["runner_health"]["seconds_since_last_market_data"] == 7200.0


def test_drift_tracker_insufficient_sample_status():
    """Verifica que con 0 o pocos trades el Drift Tracker reporte INSUFFICIENT_SAMPLE y no alertas negativas."""
    drift_tracker = BacktestLiveDriftTracker()

    telemetry_zero = {
        "profit_factor": 0.0,
        "win_rate_pct": 0.0,
        "average_r": 0.0,
        "max_drawdown_pct": 0.0,
        "expectancy_usd": 0.0,
        "uptime_hours": 2.0,
        "positions_closed": 0,
    }

    drift_report = drift_tracker.compute_drift(telemetry_zero)

    assert drift_report["audit_status"] == "INSUFFICIENT_SAMPLE"
    assert "Muestra insuficiente" in drift_report["sample_status_explanation"]
