"""Weekly Audit Reporting System para Chimuelo Prime.

Genera paquetes reproducibles de auditoría (JSON, Markdown y XLSX) con hashing criptográfico,
sin mutar el estado de la estrategia ni del portafolio.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from chimuelo_prime.exchange_config.logger import get_logger
from chimuelo_prime.paper_trading.decision_models import (
    DecisionAction,
    DecisionObject,
    PaperPosition,
)
from chimuelo_prime.paper_trading.drift_tracker import BacktestLiveDriftTracker
from chimuelo_prime.paper_trading.persistence import (
    BasePersistenceBackend,
    SQLitePersistenceBackend,
)
from chimuelo_prime.paper_trading.telemetry import PaperTelemetryCollector
from chimuelo_prime.paper_trading.virtual_broker import VirtualBroker
from chimuelo_prime.strategies.structural_breakout import StructuralBreakoutStrategy


def get_git_commit_sha() -> str:
    """Obtiene el SHA-1 del commit actual de Git."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return res.stdout.strip()
    except Exception:
        return "UNKNOWN_COMMIT"


class WeeklyAuditReportGenerator:
    """Generador canónico de reportes de auditoría semanal para Live Paper Trading."""

    def __init__(
        self,
        persistence: BasePersistenceBackend,
        telemetry: PaperTelemetryCollector | None = None,
        broker: VirtualBroker | None = None,
        output_base_dir: str = "reports/weekly",
    ) -> None:
        self._persistence = persistence
        self._telemetry = telemetry or PaperTelemetryCollector()
        self._broker = broker or VirtualBroker(persistence=persistence)
        self._drift_tracker = BacktestLiveDriftTracker()
        self._output_base_dir = Path(output_base_dir)
        self._log = get_logger(__name__)

    def build_report_data(
        self,
        week_number: int | None = None,
        year: int | None = None,
        initial_capital: Decimal = Decimal("100.00"),
    ) -> dict[str, Any]:
        """Construye el dataset completo, inmutable y reproducible de la auditoría semanal."""
        now = datetime.now(UTC)
        y = year or now.year
        w = week_number or now.isocalendar()[1]
        week_str = f"{y}_W{w:02d}"
        report_id = f"audit_{week_str}_{int(now.timestamp())}"

        period_end = now
        period_start = now - timedelta(days=7)

        config_hash = StructuralBreakoutStrategy.get_config_hash()
        git_sha = get_git_commit_sha()

        current_equity = self._broker.get_equity() if self._broker else initial_capital
        hwm = max(initial_capital, current_equity)

        telemetry_summary = self._telemetry.get_summary(current_equity=current_equity, hwm=hwm)
        drift_data = self._drift_tracker.compute_drift(telemetry_summary)

        # 1. Trade Ledger
        trades_ledger = []
        for p in self._telemetry.closed_positions:
            trades_ledger.append({
                "position_id": p.position_id,
                "symbol": p.symbol,
                "strategy_version": "v1.0.0-frozen",
                "entry_time": p.entry_time.isoformat(),
                "entry_signal_price": str(p.entry_signal_price),
                "fill_price": str(p.fill_price),
                "stop_loss": str(p.stop_loss),
                "take_profit": str(p.take_profit),
                "exit_time": p.exit_time.isoformat() if p.exit_time else None,
                "exit_price": str(p.exit_price) if p.exit_price else None,
                "exit_reason": p.exit_reason,
                "quantity": str(p.quantity),
                "gross_pnl": str(p.gross_pnl or Decimal("0")),
                "fee_entry": str(p.fee_entry),
                "fee_exit": str(p.fee_exit or Decimal("0")),
                "net_pnl": str(p.net_pnl or Decimal("0")),
                "r_multiple": str(p.r_multiple or Decimal("0")),
                "duration_hours": p.duration_hours,
            })

        # 2. Performance Metrics
        winning_trades = [p for p in self._telemetry.closed_positions if (p.net_pnl or Decimal("0")) > Decimal("0")]
        losing_trades = [p for p in self._telemetry.closed_positions if (p.net_pnl or Decimal("0")) <= Decimal("0")]
        win_pnls = [float(p.net_pnl) for p in winning_trades if p.net_pnl is not None]
        loss_pnls = [float(p.net_pnl) for p in losing_trades if p.net_pnl is not None]
        r_list = [float(p.r_multiple or 0) for p in self._telemetry.closed_positions]

        median_r = 0.0
        if r_list:
            sorted_r = sorted(r_list)
            mid = len(sorted_r) // 2
            median_r = (sorted_r[mid] if len(sorted_r) % 2 != 0 else (sorted_r[mid - 1] + sorted_r[mid]) / 2.0)

        # 3. Market Context
        trade_regimes = self._telemetry.trade_btc_regimes

        report_payload: dict[str, Any] = {
            "identity": {
                "report_id": report_id,
                "week_identifier": week_str,
                "week_number": w,
                "year": y,
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "generated_at": now.isoformat(),
                "strategy_version": "v1.0.0-frozen",
                "config_hash": config_hash,
                "code_version_git_sha": git_sha,
                "initial_capital_usd": str(initial_capital),
                "current_equity_usd": str(current_equity),
                "high_water_mark_usd": str(hwm),
            },
            "performance": {
                "total_signals_evaluated": telemetry_summary["total_evaluations"],
                "signals_approved": telemetry_summary["signals_generated"],
                "blocked_by_strategy": telemetry_summary["blocked_by_strategy"],
                "blocked_by_risk": telemetry_summary["blocked_by_risk"],
                "trades_closed_count": len(self._telemetry.closed_positions),
                "winning_trades_count": len(winning_trades),
                "losing_trades_count": len(losing_trades),
                "win_rate_pct": telemetry_summary["win_rate_pct"],
                "profit_factor": telemetry_summary["profit_factor"],
                "expectancy_usd": telemetry_summary["expectancy_usd"],
                "average_r": telemetry_summary["average_r"],
                "median_r": round(median_r, 4),
                "average_winner_usd": round(sum(win_pnls) / len(win_pnls), 4) if win_pnls else 0.0,
                "average_loser_usd": round(sum(loss_pnls) / len(loss_pnls), 4) if loss_pnls else 0.0,
                "largest_winner_usd": round(max(win_pnls), 4) if win_pnls else 0.0,
                "largest_loser_usd": round(min(loss_pnls), 4) if loss_pnls else 0.0,
                "total_net_pnl_usd": telemetry_summary["total_net_pnl_usd"],
                "max_drawdown_pct": telemetry_summary["max_drawdown_pct"],
                "open_positions_count": self._broker.get_open_positions_count() if self._broker else 0,
            },
            "trade_ledger": trades_ledger,
            "market_context": {
                "btc_regimes_at_entry": trade_regimes,
                "performance_by_symbol": telemetry_summary["by_symbol"],
            },
            "execution_quality": {
                "total_slippage_usd": telemetry_summary["total_slippage_usd"],
                "total_fees_usd": telemetry_summary["total_fees_usd"],
                "average_latency_ms": telemetry_summary["infrastructure"]["avg_latency_ms"],
            },
            "infrastructure": telemetry_summary["infrastructure"],
            "backtest_drift": drift_data,
        }

        # Calcular SHA256 canónico del contenido de datos
        raw_canonical = json.dumps(report_payload, sort_keys=True).encode("utf-8")
        report_payload["data_integrity_sha256"] = hashlib.sha256(raw_canonical).hexdigest()
        return report_payload

    def render_markdown(self, data: dict[str, Any]) -> str:
        """Renderiza el reporte legible para humanos en formato GitHub Markdown."""
        ident = data["identity"]
        perf = data["performance"]
        exec_q = data["execution_quality"]
        infra = data["infrastructure"]
        drift = data["backtest_drift"]
        symbols = data["market_context"]["performance_by_symbol"]

        md = rf"""# Chimuelo Prime — Reporte de Auditoría Semanal ({ident['week_identifier']})

> **ID de Reporte:** `{ident['report_id']}`  
> **Generado:** `{ident['generated_at']}` | **Git Commit SHA:** `{ident['code_version_git_sha'][:12]}`  
> **Estrategia:** `{ident['strategy_version']}` | **Config Hash:** `{ident['config_hash'][:16]}...`  
> **Hash de Integridad (SHA-256):** `{data['data_integrity_sha256']}`  

---

## 1. Resumen de Desempeño y Capital

| Métrica | Valor | Métrica | Valor |
| :--- | :--- | :--- | :--- |
| **Capital Inicial** | \${ident['initial_capital_usd']} USD | **Patrimonio Actual** | \${ident['current_equity_usd']} USD |
| **High-Water Mark** | \${ident['high_water_mark_usd']} USD | **Max Drawdown** | {perf['max_drawdown_pct']}% |
| **PnL Neto Acumulado** | \${perf['total_net_pnl_usd']} USD | **Profit Factor** | {perf['profit_factor']} |
| **Win Rate** | {perf['win_rate_pct']}% ({perf['winning_trades_count']}W / {perf['losing_trades_count']}L) | **Expectancy** | \${perf['expectancy_usd']} USD / trade |
| **Average R** | {perf['average_r']}R | **Median R** | {perf['median_r']}R |
| **Ganancia Media (Win)** | \${perf['average_winner_usd']} USD | **Pérdida Media (Loss)** | \${perf['average_loser_usd']} USD |
| **Mayor Ganancia** | \${perf['largest_winner_usd']} USD | **Mayor Pérdida** | \${perf['largest_loser_usd']} USD |

---

## 2. Auditoría de Señales y Riesgo

* **Velas / Barras Evaluadas:** `{perf['total_signals_evaluated']}`
* **Señales Aprobadas para Ejecución:** `{perf['signals_approved']}`
* **Bloqueos por Filtros de Estrategia:** `{perf['blocked_by_strategy']}`
* **Bloqueos por Risk Engine:** `{perf['blocked_by_risk']}`
* **Posiciones Abiertas Actualmente:** `{perf['open_positions_count']}`

---

## 3. Desempeño por Activo

| Símbolo | Trades | Win Rate | Profit Factor | PnL Neto | Average R |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **BTCUSDT** | {symbols['BTCUSDT']['trades']} | {symbols['BTCUSDT']['win_rate_pct']}% | {symbols['BTCUSDT']['profit_factor']} | \${symbols['BTCUSDT']['net_pnl']} USD | {symbols['BTCUSDT']['avg_r']}R |
| **SOLUSDT** | {symbols['SOLUSDT']['trades']} | {symbols['SOLUSDT']['win_rate_pct']}% | {symbols['SOLUSDT']['profit_factor']} | \${symbols['SOLUSDT']['net_pnl']} USD | {symbols['SOLUSDT']['avg_r']}R |

---

## 4. Comparativa de Desviación (Drift Tracker vs Backtest)

### A. vs Historical Full-Sample (2024–2026 Walk-Forward)
* **Frecuencia Mensual:** Observada `{drift['live_observed']['monthly_frequency']}` vs Esperada `{drift['comparison_vs_historical_full_sample_2024_2026']['drift_metrics']['monthly_frequency']['historical']}` (Delta: `{drift['comparison_vs_historical_full_sample_2024_2026']['drift_metrics']['monthly_frequency']['drift_delta']}`)
* **Profit Factor:** Observado `{drift['live_observed']['profit_factor']}` vs Esperado `{drift['comparison_vs_historical_full_sample_2024_2026']['drift_metrics']['profit_factor']['historical']}` (Delta: `{drift['comparison_vs_historical_full_sample_2024_2026']['drift_metrics']['profit_factor']['drift_delta']}`)
* **Win Rate:** Observado `{drift['live_observed']['win_rate_pct']}%` vs Esperado `{drift['comparison_vs_historical_full_sample_2024_2026']['drift_metrics']['win_rate_pct']['historical']}%`
* **Average R:** Observado `{drift['live_observed']['average_r']}R` vs Esperado `{drift['comparison_vs_historical_full_sample_2024_2026']['drift_metrics']['average_r']['historical']}R`

### B. vs Historical Out-of-Sample (2022–2024 True Unseen Holdout)
* **Profit Factor:** Observado `{drift['live_observed']['profit_factor']}` vs Esperado `{drift['comparison_vs_historical_oos_2022_2024']['drift_metrics']['profit_factor']['historical']}` (Delta: `{drift['comparison_vs_historical_oos_2022_2024']['drift_metrics']['profit_factor']['drift_delta']}`)
* **Win Rate:** Observado `{drift['live_observed']['win_rate_pct']}%` vs Esperado `{drift['comparison_vs_historical_oos_2022_2024']['drift_metrics']['win_rate_pct']['historical']}%`
* **Average R:** Observado `{drift['live_observed']['average_r']}R` vs Esperado `{drift['comparison_vs_historical_oos_2022_2024']['drift_metrics']['average_r']['historical']}R`

---

## 5. Calidad de Ejecución e Infraestructura

* **Slippage Acumulado:** `\${exec_q['total_slippage_usd']} USD`
* **Comisiones Simuladas (Fees):** `\${exec_q['total_fees_usd']} USD`
* **Latencia Media:** `{exec_q['average_latency_ms']} ms`
* **Reconexiones WebSocket:** `{infra['ws_reconnects']}`
* **Fallbacks a REST:** `{infra['rest_fallbacks']}`
* **Velas Duplicadas / Stale:** `{infra['duplicate_events']} / {infra['stale_candles']}`

---

## 6. Trade Ledger Completo de la Semana

"""
        if not data["trade_ledger"]:
            md += "_No se registraron cierres de operaciones durante el período auditado._\n"
        else:
            md += "| ID | Símbolo | Entrada | Salida | Razón | PnL Neto | R Multiple | Duración |\n"
            md += "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"
            for t in data["trade_ledger"]:
                md += rf"| `{t['position_id']}` | **{t['symbol']}** | \${t['fill_price']} | \${t['exit_price']} | `{t['exit_reason']}` | \${t['net_pnl']} USD | {t['r_multiple']}R | {t['duration_hours']}h |\n"

        md += "\n---\n_Reporte generado automáticamente por el Weekly Audit Reporting System de Chimuelo Prime. Inmutable y reproducible._\n"
        return md

    def export_excel(self, data: dict[str, Any], filepath: Path) -> None:
        """Genera el libro Excel (.xlsx) estructurado con múltiples pestañas."""
        import openpyxl
        from openpyxl.styles import Alignment, Font, PatternFill

        wb = openpyxl.Workbook()

        # Tab 1: Summary
        ws_sum = wb.active
        ws_sum.title = "Resumen Ejecutivo"
        ws_sum.append(["CHIMUELO PRIME — REPORTE DE AUDITORÍA SEMANAL", data["identity"]["week_identifier"]])
        ws_sum.append([])
        ws_sum.append(["Report ID", data["identity"]["report_id"]])
        ws_sum.append(["Generado", data["identity"]["generated_at"]])
        ws_sum.append(["Git Commit SHA", data["identity"]["code_version_git_sha"]])
        ws_sum.append(["Config Hash", data["identity"]["config_hash"]])
        ws_sum.append(["Integrity Hash SHA256", data["data_integrity_sha256"]])
        ws_sum.append([])
        ws_sum.append(["Capital Inicial (USD)", float(data["identity"]["initial_capital_usd"])])
        ws_sum.append(["Patrimonio Actual (USD)", float(data["identity"]["current_equity_usd"])])
        ws_sum.append(["PnL Neto Acumulado (USD)", float(data["performance"]["total_net_pnl_usd"])])
        ws_sum.append(["Profit Factor", data["performance"]["profit_factor"]])
        ws_sum.append(["Win Rate (%)", data["performance"]["win_rate_pct"]])
        ws_sum.append(["Average R", data["performance"]["average_r"]])
        ws_sum.append(["Max Drawdown (%)", data["performance"]["max_drawdown_pct"]])

        # Tab 2: Trades
        ws_trades = wb.create_sheet(title="Trade Ledger")
        ws_trades.append([
            "Position ID", "Symbol", "Entry Time", "Fill Price", "Stop Loss",
            "Take Profit", "Exit Time", "Exit Price", "Exit Reason", "Quantity",
            "Gross PnL", "Fees", "Net PnL", "R Multiple", "Duration (Hours)"
        ])
        for t in data["trade_ledger"]:
            ws_trades.append([
                t["position_id"], t["symbol"], t["entry_time"], float(t["fill_price"]),
                float(t["stop_loss"]), float(t["take_profit"]), t["exit_time"],
                float(t["exit_price"]) if t["exit_price"] else None, t["exit_reason"],
                float(t["quantity"]), float(t["gross_pnl"]), float(t["fee_entry"]) + float(t["fee_exit"]),
                float(t["net_pnl"]), float(t["r_multiple"]), t["duration_hours"],
            ])

        # Tab 3: Backtest Drift
        ws_drift = wb.create_sheet(title="Drift Tracker")
        ws_drift.append(["Métrica", "Live Observado", "Full-Sample Baseline", "Full-Sample Drift", "OOS Baseline", "OOS Drift"])
        fs_d = data["backtest_drift"]["comparison_vs_historical_full_sample_2024_2026"]["drift_metrics"]
        oos_d = data["backtest_drift"]["comparison_vs_historical_oos_2022_2024"]["drift_metrics"]

        ws_drift.append(["Profit Factor", data["performance"]["profit_factor"], fs_d["profit_factor"]["historical"], fs_d["profit_factor"]["drift_delta"], oos_d["profit_factor"]["historical"], oos_d["profit_factor"]["drift_delta"]])
        ws_drift.append(["Win Rate (%)", data["performance"]["win_rate_pct"], fs_d["win_rate_pct"]["historical"], fs_d["win_rate_pct"]["drift_delta"], oos_d["win_rate_pct"]["historical"], oos_d["win_rate_pct"]["drift_delta"]])
        ws_drift.append(["Average R", data["performance"]["average_r"], fs_d["average_r"]["historical"], fs_d["average_r"]["drift_delta"], oos_d["average_r"]["historical"], oos_d["average_r"]["drift_delta"]])
        ws_drift.append(["Monthly Frequency", data["backtest_drift"]["live_observed"]["monthly_frequency"], fs_d["monthly_frequency"]["historical"], fs_d["monthly_frequency"]["drift_delta"], oos_d["monthly_frequency"]["historical"], oos_d["monthly_frequency"]["drift_delta"]])
        ws_drift.append(["Max Drawdown (%)", data["performance"]["max_drawdown_pct"], fs_d["max_drawdown_pct"]["historical"], fs_d["max_drawdown_pct"]["drift_delta"], oos_d["max_drawdown_pct"]["historical"], oos_d["max_drawdown_pct"]["drift_delta"]])

        wb.save(filepath)

    def generate_and_save_package(
        self,
        week_number: int | None = None,
        year: int | None = None,
        initial_capital: Decimal = Decimal("100.00"),
    ) -> dict[str, Any]:
        """Genera el paquete completo (JSON, Markdown, XLSX) y lo archiva permanentemente."""
        report_data = self.build_report_data(
            week_number=week_number,
            year=year,
            initial_capital=initial_capital,
        )
        week_str = report_data["identity"]["week_identifier"]

        # 1. Carpeta de archivado permanente: reports/weekly/YYYY-WW/
        archive_dir = self._output_base_dir / week_str
        archive_dir.mkdir(parents=True, exist_ok=True)

        # 2. Rutas estándar en reports/weekly/
        json_file_arch = archive_dir / "report.json"
        md_file_arch = archive_dir / "report.md"
        xlsx_file_arch = archive_dir / "report.xlsx"

        json_file_named = self._output_base_dir / f"chimuelo_weekly_audit_{week_str}.json"
        md_file_named = self._output_base_dir / f"chimuelo_weekly_audit_{week_str}.md"
        xlsx_file_named = self._output_base_dir / f"chimuelo_weekly_audit_{week_str}.xlsx"

        # Guardar JSON
        json_str = json.dumps(report_data, indent=2, ensure_ascii=False)
        with open(json_file_arch, "w", encoding="utf-8") as f:
            f.write(json_str)
        with open(json_file_named, "w", encoding="utf-8") as f:
            f.write(json_str)

        # Guardar Markdown
        md_content = self.render_markdown(report_data)
        with open(md_file_arch, "w", encoding="utf-8") as f:
            f.write(md_content)
        with open(md_file_named, "w", encoding="utf-8") as f:
            f.write(md_content)

        # Guardar XLSX
        self.export_excel(report_data, xlsx_file_arch)
        self.export_excel(report_data, xlsx_file_named)

        self._log.info(
            "weekly_audit.package_generated",
            week=week_str,
            json_path=str(json_file_named),
            md_path=str(md_file_named),
            xlsx_path=str(xlsx_file_named),
            sha256=report_data["data_integrity_sha256"],
        )

        return {
            "week_identifier": week_str,
            "report_id": report_data["identity"]["report_id"],
            "sha256": report_data["data_integrity_sha256"],
            "files": {
                "json": str(json_file_named),
                "markdown": str(md_file_named),
                "excel": str(xlsx_file_named),
            },
            "archive_dir": str(archive_dir),
            "data": report_data,
        }
