"""Tests unitarios para el generador de reportes de backtesting (M6)."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from chimuelo_prime.backtesting.engine import BacktestReport, EquityPoint, TradeRecord
from chimuelo_prime.backtesting.reporter import BacktestReporter


def test_reporter_terminal_and_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verifica que el reporter imprima correctamente en consola y exporte a JSON."""
    report = BacktestReport(
        symbol="SOLUSDT",
        interval="1h",
        start_time=datetime(2024, 5, 14, 0, 0),
        end_time=datetime(2024, 5, 14, 2, 0),
        initial_cash=Decimal("100.00"),
        final_cash=Decimal("110.00"),
        initial_equity=Decimal("100.00"),
        final_equity=Decimal("110.00"),
        total_return_pct=Decimal("10.00"),
        max_drawdown_pct=Decimal("0.00"),
        profit_factor=Decimal("99.99"),
        sortino_ratio=Decimal("15.5"),
        calmar_ratio=Decimal("10.2"),
        win_rate_pct=Decimal("100.00"),
        total_trades=1,
        completed_trades=1,
        recreate_buy_on_sell_fill=False,
        timeseries=[
            EquityPoint(
                timestamp=datetime(2024, 5, 14, 0, 0),
                cash=Decimal("100.00"),
                inventory=Decimal("0.0"),
                inventory_value=Decimal("0.0"),
                equity=Decimal("100.00"),
                drawdown_pct=Decimal("0.0"),
            ),
            EquityPoint(
                timestamp=datetime(2024, 5, 14, 1, 0),
                cash=Decimal("110.00"),
                inventory=Decimal("0.0"),
                inventory_value=Decimal("0.0"),
                equity=Decimal("110.00"),
                drawdown_pct=Decimal("0.0"),
            ),
        ],
        trades=[
            TradeRecord(
                level_index=1,
                buy_price=Decimal("100.00"),
                sell_price=Decimal("110.00"),
                qty=Decimal("1.0"),
                buy_time=datetime(2024, 5, 14, 0, 0),
                sell_time=datetime(2024, 5, 14, 1, 0),
                pnl=Decimal("10.00"),
                pnl_pct=Decimal("10.00"),
            )
        ],
    )

    reporter = BacktestReporter(report)

    # 1. Probar reporte por consola
    reporter.print_terminal_report()
    captured = capsys.readouterr()
    assert "CHIMUELO PRIME" in captured.out
    assert "SOLUSDT" in captured.out
    assert "Modo de Operación:      ESTRICTO (M5)" in captured.out
    assert "10.0000 %" in captured.out

    # 2. Probar exportación a JSON
    file_path = tmp_path / "reports" / "report.json"
    reporter.export_json(file_path)

    assert file_path.exists()
    with open(file_path, encoding="utf-8") as f:
        data = json.load(f)

    assert data["symbol"] == "SOLUSDT"
    assert data["interval"] == "1h"
    assert data["total_return_pct"] == "10.00"
    assert len(data["trades"]) == 1
    assert data["trades"][0]["pnl"] == "10.00"
