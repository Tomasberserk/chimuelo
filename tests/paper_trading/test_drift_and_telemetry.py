"""Tests para BacktestLiveDriftTracker y PaperTelemetryCollector con snapshots semanales."""

from datetime import UTC, datetime
from decimal import Decimal
import pytest

from chimuelo_prime.paper_trading.drift_tracker import BacktestLiveDriftTracker
from chimuelo_prime.paper_trading.telemetry import PaperTelemetryCollector


def test_drift_tracker_reproducible_baselines():
    """Verifica que el Drift Tracker contenga los baselines históricos exactos Full-Sample y OOS."""
    tracker = BacktestLiveDriftTracker()

    fs = tracker._full_sample
    assert fs["metadata"]["strategy_version"] == "v1.0.0-frozen"
    assert fs["metadata"]["trade_count"] == 135
    assert fs["metrics"]["win_rate_pct"] == 37.04
    assert fs["metrics"]["profit_factor"] == 1.03
    assert fs["metrics"]["average_r"] == 0.10
    assert fs["metrics"]["max_drawdown_pct"] == 17.13

    oos = tracker._oos
    assert oos["metadata"]["strategy_version"] == "v1.0.0-frozen"
    assert oos["metadata"]["trade_count"] == 173
    assert oos["metrics"]["win_rate_pct"] == 41.62
    assert oos["metrics"]["profit_factor"] == 1.16
    assert oos["metrics"]["average_r"] == 0.26
    assert oos["metrics"]["max_drawdown_pct"] == 20.66


def test_drift_computation_and_weekly_snapshot():
    """Verifica el cálculo de desviación descriptiva y la exportación de snapshot semanal."""
    telemetry = PaperTelemetryCollector()
    telemetry.record_network_event("RECONNECT", latency_ms=45.2)
    telemetry.record_network_event("REST_FALLBACK", latency_ms=52.8)

    summary = telemetry.get_summary()
    assert summary["infrastructure"]["ws_reconnects"] == 1
    assert summary["infrastructure"]["rest_fallbacks"] == 1

    weekly_snap = telemetry.generate_weekly_snapshot(week_number=1)
    assert weekly_snap["week_number"] == 1
    assert "backtest_drift" in weekly_snap
    drift = weekly_snap["backtest_drift"]
    assert "comparison_vs_historical_full_sample_2024_2026" in drift
    assert "comparison_vs_historical_oos_2022_2024" in drift
    assert drift["audit_status"] == "DESCRIPTIVE_MONITORING_NO_RULES_MUTATION"
