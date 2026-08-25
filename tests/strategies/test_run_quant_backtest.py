"""Tests unitarios para el script CLI run_quant_backtest.py."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from run_quant_backtest import main, run_quant_simulation


def _create_mock_candles(count: int = 100) -> list[HistoricalCandle]:
    candles = []
    base_time = datetime(2024, 1, 1, 0, 0)
    for i in range(count):
        candles.append(
            HistoricalCandle(
                timestamp=base_time + timedelta(hours=i),
                open=Decimal("100.0"),
                high=Decimal("105.0"),
                low=Decimal("95.0"),
                close=Decimal("102.0"),
                volume=Decimal("1000.0"),
            )
        )
    return candles


def test_run_quant_simulation_success(tmp_path: Path) -> None:
    mock_candles = _create_mock_candles(60)

    with patch("run_quant_backtest.HistoricalDataLoader") as mock_loader_cls:
        mock_loader = MagicMock()
        mock_loader.get_candles.return_value = mock_candles
        mock_loader_cls.return_value = mock_loader

        exit_code = run_quant_simulation(
            symbol="SOLUSDT",
            intervals=["1h"],
            days=5,
            initial_cash=Decimal("25.00"),
            output_dir=tmp_path,
        )

        assert exit_code == 0
        expected_json = tmp_path / "quant_backtest_solusdt_1h.json"
        assert expected_json.exists()


def test_run_quant_simulation_no_candles(tmp_path: Path) -> None:
    with patch("run_quant_backtest.HistoricalDataLoader") as mock_loader_cls:
        mock_loader = MagicMock()
        mock_loader.get_candles.return_value = []
        mock_loader_cls.return_value = mock_loader

        exit_code = run_quant_simulation(
            symbol="SOLUSDT",
            intervals=["15m"],
            days=5,
            output_dir=tmp_path,
        )

        # Retorna 1 cuando no se procesó ningún intervalo con éxito
        assert exit_code == 1


def test_run_quant_backtest_cli_main(tmp_path: Path) -> None:
    mock_candles = _create_mock_candles(60)

    with patch("run_quant_backtest.HistoricalDataLoader") as mock_loader_cls:
        mock_loader = MagicMock()
        mock_loader.get_candles.return_value = mock_candles
        mock_loader_cls.return_value = mock_loader

        test_args = [
            "run_quant_backtest.py",
            "--symbol",
            "SOLUSDT",
            "--intervals",
            "1h",
            "--days",
            "5",
            "--initial-cash",
            "25.00",
            "--output-dir",
            str(tmp_path),
        ]

        with patch("sys.argv", test_args):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0
