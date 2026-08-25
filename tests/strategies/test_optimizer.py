"""Tests unitarios para el módulo de optimización de hiperparámetros (StrategyParameterOptimizer)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.strategies.optimizer import (
    OptimizationParamGrid,
    OptimizationSummary,
    OptimizationTrialResult,
    StrategyParameterOptimizer,
)


def _create_mock_candles(
    count: int, base_price: Decimal = Decimal("100.0")
) -> list[HistoricalCandle]:
    """Genera una serie cronológica sintética de velas históricas."""
    candles: list[HistoricalCandle] = []
    base_time = datetime(2024, 1, 1, 0, 0)
    for i in range(count):
        dt = base_time + timedelta(hours=i)
        price = base_price + Decimal(str((i % 10) * 0.5))
        candles.append(
            HistoricalCandle(
                timestamp=dt,
                open=price,
                high=price + Decimal("1.5"),
                low=price - Decimal("1.5"),
                close=price + Decimal("0.3"),
                volume=Decimal("1500.0"),
            )
        )
    return candles


class TestOptimizationParamGrid:
    """Pruebas para el modelo y validaciones de OptimizationParamGrid."""

    def test_default_grid_values_and_combinations(self) -> None:
        grid = OptimizationParamGrid()
        assert len(grid.rsi_oversold_thresholds) == 4  # [36.0, 38.0, 40.0, 42.0]
        assert len(grid.atr_sl_multipliers) == 3       # [1.2, 1.5, 2.0]
        assert len(grid.risk_reward_ratios) == 4       # [2.0, 2.5, 3.0, 3.5]
        assert len(grid.lookback_bars_list) == 3       # [20, 30, 40]
        assert grid.total_combinations == 4 * 3 * 4 * 3 * 1 * 1 * 1 * 1 * 1 * 1  # 144

    def test_custom_grid_values_and_decimal_coercion(self) -> None:
        grid = OptimizationParamGrid(
            rsi_oversold_thresholds=[Decimal("35.0"), Decimal("40.0")],
            atr_sl_multipliers=["1.5", "2.0"],  # Coerced from str
            risk_reward_ratios=[2, 3],          # Coerced from int
            lookback_bars_list=[25, 35],
        )
        assert grid.rsi_oversold_thresholds == [Decimal("35.0"), Decimal("40.0")]
        assert grid.atr_sl_multipliers == [Decimal("1.5"), Decimal("2.0")]
        assert grid.risk_reward_ratios == [Decimal("2"), Decimal("3")]
        assert grid.lookback_bars_list == [25, 35]
        assert grid.total_combinations == 2 * 2 * 2 * 2  # 16

    def test_rejects_floats_in_decimals(self) -> None:
        with pytest.raises(TypeError, match="Floats no permitidos"):
            OptimizationParamGrid(rsi_oversold_thresholds=[38.5])

    def test_rejects_floats_in_ints(self) -> None:
        with pytest.raises(TypeError, match="Floats no permitidos"):
            OptimizationParamGrid(lookback_bars_list=[25.5])  # type: ignore

    def test_rejects_empty_lists(self) -> None:
        with pytest.raises(ValueError, match="no puede estar vacía"):
            OptimizationParamGrid(rsi_oversold_thresholds=[])

        with pytest.raises(ValueError, match="no puede estar vacía"):
            OptimizationParamGrid(lookback_bars_list=[])

    def test_rejects_negative_or_zero_periods(self) -> None:
        with pytest.raises(ValueError, match="enteros positivos"):
            OptimizationParamGrid(lookback_bars_list=[-5])


class TestOptimizationModelsPurity:
    """Pruebas de inmutabilidad y pureza de modelos de optimización."""

    def test_trial_result_rejects_floats(self) -> None:
        with pytest.raises(TypeError, match="Floats no permitidos"):
            OptimizationTrialResult(
                trial_id=1,
                symbol="SOLUSDT",
                interval="15m",
                params={},
                total_trades=5,
                winning_trades=3,
                losing_trades=2,
                win_rate_pct=60.0,  # Float prohibited
                profit_factor=Decimal("2.1"),
                max_drawdown_pct=Decimal("4.5"),
                total_return_pct=Decimal("5.2"),
                net_profit_usd=Decimal("1.3"),
                sortino_ratio=Decimal("2.0"),
                calmar_ratio=Decimal("1.5"),
                initial_cash=Decimal("25.00"),
                final_equity=Decimal("26.30"),
            )

    def test_trial_result_frozen_immutability(self) -> None:
        res = OptimizationTrialResult(
            trial_id=1,
            symbol="SOLUSDT",
            interval="15m",
            params={"rsi_oversold_threshold": "38.0"},
            total_trades=5,
            winning_trades=3,
            losing_trades=2,
            win_rate_pct=Decimal("60.0"),
            profit_factor=Decimal("2.1"),
            max_drawdown_pct=Decimal("4.5"),
            total_return_pct=Decimal("5.2"),
            net_profit_usd=Decimal("1.3"),
            sortino_ratio=Decimal("2.0"),
            calmar_ratio=Decimal("1.5"),
            initial_cash=Decimal("25.00"),
            final_equity=Decimal("26.30"),
        )
        with pytest.raises(Exception):
            res.profit_factor = Decimal("3.0")  # type: ignore


class TestStrategyParameterOptimizer:
    """Pruebas unitarias de ejecución y algoritmos del optimizador."""

    def test_empty_candles_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="no puede estar vacía"):
            StrategyParameterOptimizer(candles=[])

    def test_generate_parameter_grid_cartesian_product(self) -> None:
        candles = _create_mock_candles(300)
        optimizer = StrategyParameterOptimizer(candles=candles, symbol="SOLUSDT", interval="1h")
        grid = OptimizationParamGrid(
            rsi_oversold_thresholds=[Decimal("36.0"), Decimal("40.0")],
            atr_sl_multipliers=[Decimal("1.2"), Decimal("1.5")],
            risk_reward_ratios=[Decimal("2.0"), Decimal("3.0")],
            lookback_bars_list=[20, 40],
        )
        combos = optimizer.generate_parameter_grid(grid)
        assert len(combos) == 16
        assert combos[0]["rsi_oversold_threshold"] == Decimal("36.0")
        assert combos[0]["atr_sl_multiplier"] == Decimal("1.2")
        assert combos[0]["risk_reward_ratio"] == Decimal("2.0")
        assert combos[0]["lookback_bars"] == 20

    def test_evaluate_single_trial(self) -> None:
        candles = _create_mock_candles(300)
        optimizer = StrategyParameterOptimizer(
            candles=candles,
            symbol="SOLUSDT",
            interval="1h",
            initial_cash=Decimal("25.00"),
        )
        params = {
            "rsi_oversold_threshold": Decimal("38.0"),
            "atr_sl_multiplier": Decimal("1.5"),
            "risk_reward_ratio": Decimal("2.5"),
            "lookback_bars": 25,
        }
        trial_res = optimizer.evaluate_trial(params, trial_id=42, include_report=True)
        assert trial_res.trial_id == 42
        assert trial_res.symbol == "SOLUSDT"
        assert trial_res.interval == "1h"
        assert trial_res.initial_cash == Decimal("25.00")
        assert trial_res.report is not None
        assert isinstance(trial_res.profit_factor, Decimal)
        assert isinstance(trial_res.max_drawdown_pct, Decimal)

    def test_run_optimization_summary_and_ranking(self) -> None:
        candles = _create_mock_candles(300)
        optimizer = StrategyParameterOptimizer(
            candles=candles,
            symbol="SOLUSDT",
            interval="1h",
            initial_cash=Decimal("25.00"),
        )
        small_grid = OptimizationParamGrid(
            rsi_oversold_thresholds=[Decimal("36.0"), Decimal("38.0")],
            atr_sl_multipliers=[Decimal("1.5")],
            risk_reward_ratios=[Decimal("2.5")],
            lookback_bars_list=[20],
        )
        summary = optimizer.run_optimization(
            grid=small_grid,
            min_trades=0,
            max_drawdown_limit=Decimal("8.00"),
            target_profit_factor=Decimal("1.80"),
        )

        assert summary.symbol == "SOLUSDT"
        assert summary.interval == "1h"
        assert summary.total_combinations_evaluated == 2
        assert summary.successful_trials == 2
        assert len(summary.all_results) == 2
        assert summary.best_result is not None
        assert summary.execution_duration_sec >= Decimal("0.0")

    def test_export_summary_json_and_markdown(self, tmp_path: Path) -> None:
        candles = _create_mock_candles(300)
        optimizer = StrategyParameterOptimizer(
            candles=candles,
            symbol="BTCUSDT",
            interval="15m",
            initial_cash=Decimal("25.00"),
        )
        small_grid = OptimizationParamGrid(
            rsi_oversold_thresholds=[Decimal("38.0")],
            atr_sl_multipliers=[Decimal("1.5")],
            risk_reward_ratios=[Decimal("2.5")],
            lookback_bars_list=[20],
        )
        summary = optimizer.run_optimization(grid=small_grid, min_trades=0)

        # 1. Export JSON
        json_file = tmp_path / "opt_summary.json"
        optimizer.export_summary_json(summary, json_file)
        assert json_file.exists()

        with open(json_file, encoding="utf-8") as f:
            data = json.load(f)
        assert data["symbol"] == "BTCUSDT"
        assert data["total_combinations_evaluated"] == 1

        # 2. Markdown Report
        md_text = optimizer.format_markdown_report(summary, top_n=5)
        assert "# Reporte Cuantitativo de Optimización" in md_text
        assert "BTCUSDT" in md_text
        assert "Profit Factor" in md_text


class TestRunParameterOptimizationCli:
    """Pruebas para el script CLI run_parameter_optimization.py."""

    def test_run_grid_optimization_success(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock, patch
        from run_parameter_optimization import run_grid_optimization

        mock_candles = _create_mock_candles(300)
        with patch("run_parameter_optimization.HistoricalDataLoader") as mock_loader_cls:
            mock_loader = MagicMock()
            mock_loader.get_candles.return_value = mock_candles
            mock_loader_cls.return_value = mock_loader

            exit_code = run_grid_optimization(
                symbols=["SOLUSDT"],
                intervals=["1h"],
                days=5,
                initial_cash=Decimal("25.00"),
                output_dir=tmp_path,
            )

            assert exit_code == 0
            json_out = tmp_path / "optimization_solusdt_1h.json"
            assert json_out.exists()

    def test_run_grid_optimization_no_candles(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock, patch
        from run_parameter_optimization import run_grid_optimization

        with patch("run_parameter_optimization.HistoricalDataLoader") as mock_loader_cls:
            mock_loader = MagicMock()
            mock_loader.get_candles.return_value = []
            mock_loader_cls.return_value = mock_loader

            exit_code = run_grid_optimization(
                symbols=["SOLUSDT"],
                intervals=["1h"],
                output_dir=tmp_path,
            )
            assert exit_code == 0

    def test_run_parameter_optimization_main(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock, patch
        from run_parameter_optimization import main

        mock_candles = _create_mock_candles(300)
        with patch("run_parameter_optimization.HistoricalDataLoader") as mock_loader_cls:
            mock_loader = MagicMock()
            mock_loader.get_candles.return_value = mock_candles
            mock_loader_cls.return_value = mock_loader

            test_args = [
                "run_parameter_optimization.py",
                "--symbols",
                "SOLUSDT",
                "--intervals",
                "1h",
                "--output-dir",
                str(tmp_path),
            ]
            with patch("sys.argv", test_args):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 0

