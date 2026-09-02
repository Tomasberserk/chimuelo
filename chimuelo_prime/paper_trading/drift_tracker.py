"""Módulo de Tracking de Desviación (Backtest Expected vs Live Paper Observed)."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any


class BacktestLiveDriftTracker:
    """Compara métricas observadas en tiempo real contra los baselines históricos esperados."""

    # Baseline histórico congelado derivado de los 2 años de validación / holdout
    EXPECTED_BASELINE = {
        "monthly_trades_expected": 2.5,  # ~2-3 trades por mes
        "expected_win_rate_pct": 45.0,   # ~42% - 48%
        "expected_profit_factor": 1.20,  # ~1.15 - 1.25
        "expected_avg_r": 0.40,          # ~0.35R - 0.45R
        "expected_max_drawdown_pct": 18.0,  # < 20%
        "expected_slippage_pct": 0.05,   # 0.05% por trade
        "expected_fee_drag_pct": 0.20,   # 0.20% roundtrip
    }

    def __init__(self, baseline: dict[str, Any] | None = None) -> None:
        self._baseline = baseline or self.EXPECTED_BASELINE

    def compute_drift(self, live_telemetry: dict[str, Any]) -> dict[str, Any]:
        """Calcula la desviación porcentual y absoluta entre lo esperado y lo observado."""
        observed_pf = float(live_telemetry.get("profit_factor", 0.0))
        observed_wr = float(live_telemetry.get("win_rate_pct", 0.0))
        observed_avg_r = float(live_telemetry.get("average_r", 0.0))
        observed_dd = float(live_telemetry.get("max_drawdown_pct", 0.0))
        uptime_days = max(1.0, float(live_telemetry.get("uptime_hours", 0.0)) / 24.0)
        trades_count = float(live_telemetry.get("positions_closed", 0))
        monthly_trades_observed = (trades_count / uptime_days) * 30.0

        drift_report = {
            "comparison": {
                "profit_factor": {
                    "expected": self._baseline["expected_profit_factor"],
                    "observed": observed_pf,
                    "drift_delta": round(observed_pf - self._baseline["expected_profit_factor"], 2),
                },
                "win_rate_pct": {
                    "expected": self._baseline["expected_win_rate_pct"],
                    "observed": observed_wr,
                    "drift_delta": round(observed_wr - self._baseline["expected_win_rate_pct"], 2),
                },
                "average_r": {
                    "expected": self._baseline["expected_avg_r"],
                    "observed": observed_avg_r,
                    "drift_delta": round(observed_avg_r - self._baseline["expected_avg_r"], 4),
                },
                "max_drawdown_pct": {
                    "expected": self._baseline["expected_max_drawdown_pct"],
                    "observed": observed_dd,
                    "drift_delta": round(observed_dd - self._baseline["expected_max_drawdown_pct"], 2),
                },
                "monthly_trade_frequency": {
                    "expected": self._baseline["monthly_trades_expected"],
                    "observed": round(monthly_trades_observed, 2),
                    "drift_delta": round(monthly_trades_observed - self._baseline["monthly_trades_expected"], 2),
                },
            },
            "status": "MONITORING_NO_ACTION_REQUIRED",
            "notes": (
                "Las diferencias observadas se auditan pasivamente sin aplicar auto-correcciones ni modificaciones "
                "de parámetros durante el período de prueba de 60 días."
            ),
        }
        return drift_report

    def export_drift_report(
        self, live_telemetry: dict[str, Any], file_path: str = "data/reports/backtest_live_drift.json"
    ) -> None:
        """Exporta el reporte de desviación a JSON."""
        report = self.compute_drift(live_telemetry)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
