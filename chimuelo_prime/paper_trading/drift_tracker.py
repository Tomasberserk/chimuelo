"""Módulo de Tracking de Desviación (Backtest Baseline vs Live Paper Observed).

Contiene los baselines históricos canónicos y reproducibles derivados de los artefactos
de validación (Full-Sample 2024-2026 y True Unseen Holdout OOS 2022-2024) para Strategy C v1.0.0-frozen
en BTCUSDT y SOLUSDT (1h).
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any


class BacktestLiveDriftTracker:
    """Compara métricas observadas en tiempo real contra los baselines históricos reproducibles."""

    # 1. HISTORICAL FULL-SAMPLE BASELINE (2024-09 a 2026-08 — Walkforward / In-Sample + Validation)
    HISTORICAL_FULL_SAMPLE = {
        "metadata": {
            "strategy_version": "v1.0.0-frozen",
            "dataset": "Binance Spot Klines 1h",
            "period": "2024-09-01 a 2026-08-31 (24 meses)",
            "assets": ["BTCUSDT", "SOLUSDT"],
            "timeframe": "1h",
            "costs": "Fee 0.10% + Slippage 0.05% por lado",
            "trade_count": 135,
            "artifact_source": "data/reports/frozen_validation_results.json",
        },
        "metrics": {
            "monthly_trade_frequency": 5.63,
            "win_rate_pct": 37.04,
            "profit_factor": 1.03,
            "average_r": 0.10,
            "expectancy_usd": 0.058,
            "max_drawdown_pct": 17.13,
            "net_pnl_usd": 7.88,
            "by_symbol": {
                "BTCUSDT": {"trades": 62, "win_rate": 33.87, "profit_factor": 0.96, "avg_r": -0.02, "max_dd": 17.13},
                "SOLUSDT": {"trades": 73, "win_rate": 39.73, "profit_factor": 1.10, "avg_r": 0.20, "max_dd": 17.11},
            },
        },
    }

    # 2. HISTORICAL OUT-OF-SAMPLE (OOS) BASELINE (2022-09 a 2024-08 — True Unseen Holdout)
    HISTORICAL_OOS = {
        "metadata": {
            "strategy_version": "v1.0.0-frozen",
            "dataset": "Binance Spot Klines 1h (Completely Unseen Holdout)",
            "period": "2022-09-01 a 2024-08-31 (24 meses)",
            "assets": ["BTCUSDT", "SOLUSDT"],
            "timeframe": "1h",
            "costs": "Fee 0.10% + Slippage 0.05% por lado",
            "trade_count": 173,
            "artifact_source": "data/reports/holdout_unseen_results.json",
        },
        "metrics": {
            "monthly_trade_frequency": 7.21,
            "win_rate_pct": 41.62,
            "profit_factor": 1.16,
            "average_r": 0.26,
            "expectancy_usd": 0.237,
            "max_drawdown_pct": 20.66,
            "net_pnl_usd": 41.00,
            "by_symbol": {
                "BTCUSDT": {"trades": 81, "win_rate": 44.44, "profit_factor": 1.21, "avg_r": 0.33, "max_dd": 11.44},
                "SOLUSDT": {"trades": 92, "win_rate": 39.13, "profit_factor": 1.13, "avg_r": 0.20, "max_dd": 20.66},
            },
        },
    }

    def __init__(
        self,
        baseline_full_sample: dict[str, Any] | None = None,
        baseline_oos: dict[str, Any] | None = None,
    ) -> None:
        self._full_sample = baseline_full_sample or self.HISTORICAL_FULL_SAMPLE
        self._oos = baseline_oos or self.HISTORICAL_OOS

    def compute_drift(self, live_telemetry: dict[str, Any]) -> dict[str, Any]:
        """Calcula la desviación descriptiva de las métricas en vivo frente a ambos baselines históricos."""
        observed_pf = float(live_telemetry.get("profit_factor", 0.0))
        observed_wr = float(live_telemetry.get("win_rate_pct", 0.0))
        observed_avg_r = float(live_telemetry.get("average_r", 0.0))
        observed_dd = float(live_telemetry.get("max_drawdown_pct", 0.0))
        observed_exp = float(live_telemetry.get("expectancy_usd", 0.0))
        uptime_days = max(1.0, float(live_telemetry.get("uptime_hours", 0.0)) / 24.0)
        trades_count = float(live_telemetry.get("positions_closed", 0))
        monthly_trades_observed = round((trades_count / uptime_days) * 30.0, 2)

        fs_m = self._full_sample["metrics"]
        oos_m = self._oos["metrics"]

        drift_report = {
            "strategy_version": self._full_sample["metadata"]["strategy_version"],
            "live_observed": {
                "trades_closed": int(trades_count),
                "monthly_frequency": monthly_trades_observed,
                "win_rate_pct": round(observed_wr, 2),
                "profit_factor": round(observed_pf, 2),
                "average_r": round(observed_avg_r, 4),
                "expectancy_usd": round(observed_exp, 4),
                "max_drawdown_pct": round(observed_dd, 2),
            },
            "comparison_vs_historical_full_sample_2024_2026": {
                "metadata": self._full_sample["metadata"],
                "drift_metrics": {
                    "monthly_frequency": {
                        "historical": fs_m["monthly_trade_frequency"],
                        "live": monthly_trades_observed,
                        "drift_delta": round(monthly_trades_observed - fs_m["monthly_trade_frequency"], 2),
                    },
                    "win_rate_pct": {
                        "historical": fs_m["win_rate_pct"],
                        "live": round(observed_wr, 2),
                        "drift_delta": round(observed_wr - fs_m["win_rate_pct"], 2),
                    },
                    "profit_factor": {
                        "historical": fs_m["profit_factor"],
                        "live": round(observed_pf, 2),
                        "drift_delta": round(observed_pf - fs_m["profit_factor"], 2),
                    },
                    "average_r": {
                        "historical": fs_m["average_r"],
                        "live": round(observed_avg_r, 4),
                        "drift_delta": round(observed_avg_r - fs_m["average_r"], 4),
                    },
                    "max_drawdown_pct": {
                        "historical": fs_m["max_drawdown_pct"],
                        "live": round(observed_dd, 2),
                        "drift_delta": round(observed_dd - fs_m["max_drawdown_pct"], 2),
                    },
                },
            },
            "comparison_vs_historical_oos_2022_2024": {
                "metadata": self._oos["metadata"],
                "drift_metrics": {
                    "monthly_frequency": {
                        "historical": oos_m["monthly_trade_frequency"],
                        "live": monthly_trades_observed,
                        "drift_delta": round(monthly_trades_observed - oos_m["monthly_trade_frequency"], 2),
                    },
                    "win_rate_pct": {
                        "historical": oos_m["win_rate_pct"],
                        "live": round(observed_wr, 2),
                        "drift_delta": round(observed_wr - oos_m["win_rate_pct"], 2),
                    },
                    "profit_factor": {
                        "historical": oos_m["profit_factor"],
                        "live": round(observed_pf, 2),
                        "drift_delta": round(observed_pf - oos_m["profit_factor"], 2),
                    },
                    "average_r": {
                        "historical": oos_m["average_r"],
                        "live": round(observed_avg_r, 4),
                        "drift_delta": round(observed_avg_r - oos_m["average_r"], 4),
                    },
                    "max_drawdown_pct": {
                        "historical": oos_m["max_drawdown_pct"],
                        "live": round(observed_dd, 2),
                        "drift_delta": round(observed_dd - oos_m["max_drawdown_pct"], 2),
                    },
                },
            },
        }

        # Determinación de estado de muestra
        MIN_TRADES_FOR_DRIFT = 3
        if trades_count < MIN_TRADES_FOR_DRIFT:
            audit_status = "INSUFFICIENT_SAMPLE"
            sample_notes = (
                f"Muestra insuficiente ({int(trades_count)} trades cerrados de {MIN_TRADES_FOR_DRIFT} mínimos requeridos). "
                "Los cálculos de Profit Factor y Win Rate en cero no representan degradación estratégica, sino falta de observaciones iniciales."
            )
        else:
            audit_status = "DESCRIPTIVE_MONITORING_NO_RULES_MUTATION"
            sample_notes = (
                "No se modifican parámetros estratégicos en vivo independientemente de la magnitud de la desviación. "
                "Toda diferencia empírica se registra para la auditoría final de 60 días."
            )

        drift_report["audit_status"] = audit_status
        drift_report["sample_status_explanation"] = sample_notes
        drift_report["governance_rule"] = (
            "Inmutabilidad de Strategy C v1.0.0-frozen: Cero cambios de reglas o filtros durante Live Paper Trading."
        )
        return drift_report

    def export_drift_report(
        self, live_telemetry: dict[str, Any], file_path: str = "data/reports/backtest_live_drift.json"
    ) -> None:
        """Exporta el reporte de desviación a JSON en disco."""
        report = self.compute_drift(live_telemetry)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
