"""Módulo de Optimización de Hiperparámetros Cuantitativos para Chimuelo Prime.

Implementa búsqueda en rejilla (Grid Search) determinista con aritmética Decimal pura,
diseñado específicamente para maximizar el Profit Factor manteniendo un estricto control
de Max Drawdown sobre micro-cuentas ($25.00 USDT) sin look-ahead bias ni coma flotante.
"""

from __future__ import annotations

import itertools
import json
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from chimuelo_prime.backtesting.data_loader import HistoricalCandle
from chimuelo_prime.exchange_config.logger import get_logger
from chimuelo_prime.strategies.rsi_divergence import RSIDivergenceStrategy

if TYPE_CHECKING:
    from chimuelo_prime.backtesting.strategy_engine import SignalBacktestReport


class OptimizationParamGrid(BaseModel):
    """Espacio de búsqueda de hiperparámetros para RSIDivergenceStrategy."""

    model_config = ConfigDict(frozen=True, strict=True)

    rsi_oversold_thresholds: list[Decimal] = Field(
        default_factory=lambda: [
            Decimal("36.0"),
            Decimal("38.0"),
            Decimal("40.0"),
            Decimal("42.0"),
        ],
        description="Umbrales de sobreventa RSI a evaluar",
    )
    atr_sl_multipliers: list[Decimal] = Field(
        default_factory=lambda: [
            Decimal("1.2"),
            Decimal("1.5"),
            Decimal("2.0"),
        ],
        description="Multiplicadores ATR para Stop Loss",
    )
    risk_reward_ratios: list[Decimal] = Field(
        default_factory=lambda: [
            Decimal("2.0"),
            Decimal("2.5"),
            Decimal("3.0"),
            Decimal("3.5"),
        ],
        description="Ratios Riesgo/Beneficio (Take Profit / Stop Loss)",
    )
    lookback_bars_list: list[int] = Field(
        default_factory=lambda: [20, 30, 40],
        description="Ventanas de búsqueda de pivotes pasados",
    )
    rsi_periods: list[int] = Field(
        default_factory=lambda: [14],
        description="Periodos del oscilador RSI",
    )
    ema_trend_periods: list[int] = Field(
        default_factory=lambda: [200],
        description="Periodos de la media de tendencia EMA",
    )
    ema_fast_periods: list[int] = Field(
        default_factory=lambda: [20],
        description="Periodos de la media rápida EMA",
    )
    atr_periods: list[int] = Field(
        default_factory=lambda: [14],
        description="Periodos del cálculo de volatilidad ATR",
    )
    volume_sma_periods: list[int] = Field(
        default_factory=lambda: [20],
        description="Periodos de la SMA de volumen",
    )
    volume_multipliers: list[Decimal] = Field(
        default_factory=lambda: [Decimal("1.1")],
        description="Multiplicadores mínimos de volumen",
    )

    @field_validator(
        "rsi_oversold_thresholds",
        "atr_sl_multipliers",
        "risk_reward_ratios",
        "volume_multipliers",
        mode="before",
    )
    @classmethod
    def validate_decimals(cls, v: Any) -> list[Decimal]:
        if isinstance(v, (list, tuple, set)):
            result: list[Decimal] = []
            for item in v:
                if isinstance(item, float):
                    raise TypeError(f"Floats no permitidos en modelos cuantitativos: {item!r}")
                if isinstance(item, Decimal):
                    result.append(item)
                else:
                    result.append(Decimal(str(item)))
            if not result:
                raise ValueError("La lista de parámetros no puede estar vacía.")
            return result
        raise TypeError(f"Se esperaba una lista/tupla de valores, recibido: {type(v)}")

    @field_validator(
        "lookback_bars_list",
        "rsi_periods",
        "ema_trend_periods",
        "ema_fast_periods",
        "atr_periods",
        "volume_sma_periods",
        mode="before",
    )
    @classmethod
    def validate_ints(cls, v: Any) -> list[int]:
        if isinstance(v, (list, tuple, set)):
            result: list[int] = []
            for item in v:
                if isinstance(item, float):
                    raise TypeError(f"Floats no permitidos para periodos enteros: {item!r}")
                int_val = int(item)
                if int_val <= 0:
                    raise ValueError(f"Los periodos deben ser enteros positivos: {int_val}")
                result.append(int_val)
            if not result:
                raise ValueError("La lista de periodos no puede estar vacía.")
            return result
        raise TypeError(f"Se esperaba una lista de enteros, recibido: {type(v)}")

    @property
    def total_combinations(self) -> int:
        """Calcula el número total de combinaciones del producto cartesiano."""
        return (
            len(self.rsi_oversold_thresholds)
            * len(self.atr_sl_multipliers)
            * len(self.risk_reward_ratios)
            * len(self.lookback_bars_list)
            * len(self.rsi_periods)
            * len(self.ema_trend_periods)
            * len(self.ema_fast_periods)
            * len(self.atr_periods)
            * len(self.volume_sma_periods)
            * len(self.volume_multipliers)
        )


class OptimizationTrialResult(BaseModel):
    """Resultado cuantitativo inmutable de una prueba individual de la rejilla."""

    model_config = ConfigDict(frozen=True, strict=True)

    trial_id: int = Field(description="Identificador correlativo del ensayo")
    symbol: str = Field(description="Símbolo del par simulado")
    interval: str = Field(description="Temporalidad analizada")
    params: dict[str, Any] = Field(description="Configuración de hiperparámetros probada")
    total_trades: int = Field(description="Operaciones totales completadas")
    winning_trades: int = Field(description="Operaciones con PnL neto positivo")
    losing_trades: int = Field(description="Operaciones con PnL neto perdedor")
    win_rate_pct: Decimal = Field(description="Win Rate porcentual")
    profit_factor: Decimal = Field(description="Profit Factor (Gross Profits / Gross Losses)")
    max_drawdown_pct: Decimal = Field(description="Máximo Drawdown porcentual desde el pico")
    total_return_pct: Decimal = Field(description="Rendimiento porcentual sobre capital inicial")
    net_profit_usd: Decimal = Field(description="Beneficio neto total en USD")
    sortino_ratio: Decimal = Field(description="Ratio de Sortino anualizado")
    calmar_ratio: Decimal = Field(description="Ratio de Calmar anualizado")
    initial_cash: Decimal = Field(description="Capital inicial de la prueba")
    final_equity: Decimal = Field(description="Patrimonio neto final")
    report: Any | None = Field(
        default=None, description="Reporte detallado opcional del backtest"
    )

    @field_validator(
        "win_rate_pct",
        "profit_factor",
        "max_drawdown_pct",
        "total_return_pct",
        "net_profit_usd",
        "sortino_ratio",
        "calmar_ratio",
        "initial_cash",
        "final_equity",
        mode="before",
    )
    @classmethod
    def reject_floats(cls, v: Any) -> Any:
        if isinstance(v, float):
            raise TypeError(f"Floats no permitidos en modelos financieros: {v!r}")
        if v is not None and not isinstance(v, Decimal):
            return Decimal(str(v))
        return v


class OptimizationSummary(BaseModel):
    """Resumen consolidado del proceso de optimización de hiperparámetros."""

    model_config = ConfigDict(frozen=True, strict=True)

    symbol: str = Field(description="Símbolo del par optimizado")
    interval: str = Field(description="Temporalidad de las velas")
    total_combinations_evaluated: int = Field(description="Cantidad de combinaciones evaluadas")
    successful_trials: int = Field(description="Ensayos ejecutados con éxito")
    best_result: OptimizationTrialResult | None = Field(
        default=None, description="Mejor resultado según la función objetivo"
    )
    winning_results: list[OptimizationTrialResult] = Field(
        default_factory=list,
        description="Combinaciones que satisfacen todos los umbrales de seguridad",
    )
    all_results: list[OptimizationTrialResult] = Field(
        default_factory=list, description="Lista completa de resultados ordenados por ranking"
    )
    execution_duration_sec: Decimal = Field(
        default=Decimal("0.0"), description="Tiempo total de optimización en segundos"
    )
    criteria: dict[str, Any] = Field(
        default_factory=dict, description="Criterios y filtros de selección aplicados"
    )

    @field_validator("execution_duration_sec", mode="before")
    @classmethod
    def reject_floats_duration(cls, v: Any) -> Any:
        if isinstance(v, float):
            raise TypeError(f"Floats no permitidos: {v!r}")
        if v is not None and not isinstance(v, Decimal):
            return Decimal(str(v))
        return v


class StrategyParameterOptimizer:
    """Optimizador cuantitativo de hiperparámetros para RSIDivergenceStrategy."""

    def __init__(
        self,
        candles: list[HistoricalCandle],
        symbol: str = "SOLUSDT",
        interval: str = "15m",
        initial_cash: Decimal = Decimal("25.00"),
        fee_rate: Decimal = Decimal("0.001"),
        slippage_pct: Decimal = Decimal("0.0005"),
        risk_per_trade_pct: Decimal = Decimal("0.025"),
        min_notional: Decimal = Decimal("5.00"),
    ) -> None:
        if not candles:
            raise ValueError("La serie de velas históricas no puede estar vacía.")

        self._candles = sorted(candles, key=lambda c: c.timestamp)
        self._symbol = symbol
        self._interval = interval
        self._initial_cash = initial_cash
        self._fee_rate = fee_rate
        self._slippage_pct = slippage_pct
        self._risk_per_trade = risk_per_trade_pct
        self._min_notional = min_notional
        self._log = get_logger(__name__)

    def generate_parameter_grid(
        self, grid: OptimizationParamGrid | None = None
    ) -> list[dict[str, Any]]:
        """Genera la lista exhaustiva de combinaciones de parámetros."""
        target_grid = grid or OptimizationParamGrid()

        combinations: list[dict[str, Any]] = []
        product_iter = itertools.product(
            target_grid.rsi_oversold_thresholds,
            target_grid.atr_sl_multipliers,
            target_grid.risk_reward_ratios,
            target_grid.lookback_bars_list,
            target_grid.rsi_periods,
            target_grid.ema_trend_periods,
            target_grid.ema_fast_periods,
            target_grid.atr_periods,
            target_grid.volume_sma_periods,
            target_grid.volume_multipliers,
        )

        for item in product_iter:
            params = {
                "rsi_oversold_threshold": item[0],
                "atr_sl_multiplier": item[1],
                "risk_reward_ratio": item[2],
                "lookback_bars": item[3],
                "rsi_period": item[4],
                "ema_trend_period": item[5],
                "ema_fast_period": item[6],
                "atr_period": item[7],
                "volume_sma_period": item[8],
                "volume_multiplier": item[9],
            }
            combinations.append(params)

        return combinations

    def evaluate_trial(
        self,
        params: dict[str, Any],
        trial_id: int = 1,
        include_report: bool = False,
    ) -> OptimizationTrialResult:
        from chimuelo_prime.backtesting.strategy_engine import SignalStrategyBacktester

        strategy = RSIDivergenceStrategy(
            symbol=self._symbol,
            rsi_period=params.get("rsi_period", 14),
            rsi_oversold_threshold=params.get("rsi_oversold_threshold", Decimal("38.0")),
            ema_trend_period=params.get("ema_trend_period", 200),
            ema_fast_period=params.get("ema_fast_period", 20),
            atr_period=params.get("atr_period", 14),
            atr_sl_multiplier=params.get("atr_sl_multiplier", Decimal("1.5")),
            risk_reward_ratio=params.get("risk_reward_ratio", Decimal("2.5")),
            volume_sma_period=params.get("volume_sma_period", 20),
            volume_multiplier=params.get("volume_multiplier", Decimal("1.1")),
            lookback_bars=params.get("lookback_bars", 25),
        )

        backtester = SignalStrategyBacktester(
            strategy=strategy,
            candles=self._candles,
            symbol=self._symbol,
            interval=self._interval,
            initial_cash=self._initial_cash,
            fee_rate=self._fee_rate,
            slippage_pct=self._slippage_pct,
            risk_per_trade_pct=self._risk_per_trade,
            min_notional=self._min_notional,
        )

        report = backtester.run()

        # Serializar parámetros de forma limpia
        serializable_params = {
            k: (str(v) if isinstance(v, Decimal) else v) for k, v in params.items()
        }

        return OptimizationTrialResult(
            trial_id=trial_id,
            symbol=self._symbol,
            interval=self._interval,
            params=serializable_params,
            total_trades=report.total_trades,
            winning_trades=report.winning_trades,
            losing_trades=report.losing_trades,
            win_rate_pct=report.win_rate_pct,
            profit_factor=report.profit_factor,
            max_drawdown_pct=report.max_drawdown_pct,
            total_return_pct=report.total_return_pct,
            net_profit_usd=report.net_profit_usd,
            sortino_ratio=report.sortino_ratio,
            calmar_ratio=report.calmar_ratio,
            initial_cash=self._initial_cash,
            final_equity=report.final_equity,
            report=report if include_report else None,
        )

    def run_optimization(
        self,
        grid: OptimizationParamGrid | None = None,
        min_trades: int = 1,
        max_drawdown_limit: Decimal = Decimal("8.00"),
        target_profit_factor: Decimal = Decimal("1.80"),
        include_reports: bool = False,
    ) -> OptimizationSummary:
        """Ejecuta la búsqueda completa en rejilla y retorna el resumen con el candidato óptimo."""
        target_grid = grid or OptimizationParamGrid()
        combinations = self.generate_parameter_grid(target_grid)

        t_start = time.perf_counter()
        results: list[OptimizationTrialResult] = []

        self._log.info(
            "optimizer.started",
            symbol=self._symbol,
            interval=self._interval,
            total_combinations=len(combinations),
        )

        for i, params in enumerate(combinations, start=1):
            trial_result = self.evaluate_trial(
                params=params,
                trial_id=i,
                include_report=include_reports,
            )
            results.append(trial_result)

        t_end = time.perf_counter()
        duration_sec = Decimal(str(round(t_end - t_start, 4)))

        # Filtrar combinaciones que cumplen con los criterios robustos
        winning_results = [
            r
            for r in results
            if r.total_trades >= min_trades
            and r.max_drawdown_pct <= max_drawdown_limit
            and r.profit_factor >= target_profit_factor
        ]

        # Criterio de ordenación: Profit Factor DESC, Retorno Total DESC, Menor Drawdown ASC
        def sort_key(r: OptimizationTrialResult) -> tuple[Decimal, Decimal, Decimal, int]:
            return (
                r.profit_factor,
                r.total_return_pct,
                -r.max_drawdown_pct,
                r.total_trades,
            )

        winning_results.sort(key=sort_key, reverse=True)
        results.sort(key=sort_key, reverse=True)

        best_result: OptimizationTrialResult | None = None
        if winning_results:
            best_result = winning_results[0]
        elif results:
            # Si ninguna cumplió todos los filtros estrictos, seleccionamos la mejor disponible con trades
            with_trades = [r for r in results if r.total_trades >= min_trades]
            if with_trades:
                with_trades.sort(key=sort_key, reverse=True)
                best_result = with_trades[0]
            else:
                best_result = results[0]

        criteria = {
            "min_trades": min_trades,
            "max_drawdown_limit": str(max_drawdown_limit),
            "target_profit_factor": str(target_profit_factor),
            "initial_cash": str(self._initial_cash),
        }

        self._log.info(
            "optimizer.completed",
            symbol=self._symbol,
            interval=self._interval,
            evaluated=len(results),
            winning_count=len(winning_results),
            duration_sec=str(duration_sec),
        )

        return OptimizationSummary(
            symbol=self._symbol,
            interval=self._interval,
            total_combinations_evaluated=len(combinations),
            successful_trials=len(results),
            best_result=best_result,
            winning_results=winning_results,
            all_results=results,
            execution_duration_sec=duration_sec,
            criteria=criteria,
        )

    def export_summary_json(self, summary: OptimizationSummary, filepath: Path | str) -> None:
        """Exporta el reporte consolidado de optimización en formato JSON."""
        target_path = Path(filepath)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        payload = summary.model_dump(mode="json")
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    def format_markdown_report(self, summary: OptimizationSummary, top_n: int = 10) -> str:
        """Genera un reporte ejecutivo en formato Markdown con formato tabular profesional."""
        lines: list[str] = [
            f"# Reporte Cuantitativo de Optimización de Hiperparámetros — {summary.symbol} ({summary.interval})",
            "",
            "## 1. Parámetros de la Simulación",
            f"- **Símbolo:** `{summary.symbol}`",
            f"- **Temporalidad:** `{summary.interval}`",
            f"- **Combinaciones Evaluadas:** `{summary.total_combinations_evaluated}`",
            f"- **Tiempo de Ejecución:** `{summary.execution_duration_sec}s`",
            f"- **Capital Inicial:** `${self._initial_cash:.2f} USDT`",
            f"- **Criterios de Seguridad:** Profit Factor >= {summary.criteria.get('target_profit_factor', '1.80')}, Max Drawdown <= {summary.criteria.get('max_drawdown_limit', '8.00')}%",
            f"- **Combinaciones Ganadoras Encontradas:** `{len(summary.winning_results)}`",
            "",
        ]

        if summary.best_result:
            b = summary.best_result
            lines.extend(
                [
                    "## 2. Configuración Matemática Ganadora",
                    "",
                    "| Hiperparámetro | Valor Óptimo |",
                    "| :--- | :--- |",
                    f"| **RSI Oversold Threshold** | `{b.params.get('rsi_oversold_threshold')}` |",
                    f"| **ATR Stop Loss Multiplier** | `{b.params.get('atr_sl_multiplier')}` |",
                    f"| **Risk-to-Reward Ratio (R:R)** | `1:{b.params.get('risk_reward_ratio')}` |",
                    f"| **Lookback Bars** | `{b.params.get('lookback_bars')}` |",
                    f"| **EMA Tendencia / Rápida** | `EMA {b.params.get('ema_trend_period')} / EMA {b.params.get('ema_fast_period')}` |",
                    f"| **Volumen Multiplier** | `{b.params.get('volume_multiplier')}x` |",
                    "",
                    "### Métricas de Rendimiento del Candidato Óptimo",
                    "| Métrica | Valor Obtenido | Requisito Objetivo | Estado |",
                    "| :--- | :---: | :---: | :---: |",
                    f"| **Profit Factor** | **{b.profit_factor:.2f}** | > 1.80 | {'[OK - SUPERADO]' if b.profit_factor >= Decimal('1.80') else '[WARNING - REVISAR]'} |",
                    f"| **Máximo Drawdown** | **{b.max_drawdown_pct:.2f}%** | < 8.00% | {'[OK - SEGURO]' if b.max_drawdown_pct <= Decimal('8.00') else '[FAIL - EXCEDIDO]'} |",
                    f"| **Retorno Total** | **{b.total_return_pct:+.2f}%** | > 0.00% | {'[OK - POSITIVO]' if b.total_return_pct > Decimal('0') else '[FAIL - NEGATIVO]'} |",
                    f"| **Beneficio Neto (USD)** | **${b.net_profit_usd:+.2f}** | - | - |",
                    f"| **Win Rate** | **{b.win_rate_pct:.1f}%** | >= 40.0% | - |",
                    f"| **Operaciones (Trades)** | **{b.total_trades}** (W: {b.winning_trades} / L: {b.losing_trades}) | >= 1 | - |",
                    f"| **Ratio de Sortino** | **{b.sortino_ratio:.2f}** | > 1.50 | - |",
                    f"| **Ratio de Calmar** | **{b.calmar_ratio:.2f}** | > 1.00 | - |",
                    f"| **Patrimonio Final** | **${b.final_equity:.2f} USDT** | - | - |",
                    "",
                ]
            )

        # Top N combinaciones
        target_list = summary.winning_results if summary.winning_results else summary.all_results
        top_candidates = target_list[:top_n]

        lines.extend(
            [
                f"## 3. Top {len(top_candidates)} Configuraciones Evaluadas",
                "",
                "| # | RSI OS | ATR SL | R:R | Lookback | Trades | Win Rate | Profit Factor | Max DD | Retorno | PnL ($) |",
                "| :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: |",
            ]
        )

        for i, res in enumerate(top_candidates, start=1):
            p = res.params
            lines.append(
                f"| {i} | {p.get('rsi_oversold_threshold')} | {p.get('atr_sl_multiplier')} | {p.get('risk_reward_ratio')} | {p.get('lookback_bars')} | {res.total_trades} | {res.win_rate_pct:.1f}% | **{res.profit_factor:.2f}** | {res.max_drawdown_pct:.2f}% | {res.total_return_pct:+.2f}% | ${res.net_profit_usd:+.2f} |"
            )

        return "\n".join(lines)
