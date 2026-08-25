"""Script CLI de optimización de hiperparámetros cuantitativos para Chimuelo Prime.

Ejecuta la búsqueda en rejilla sistemática sobre datos históricos de SOLUSDT / BTCUSDT,
identifica la combinación óptima que maximiza el Profit Factor con estricto control de Drawdown,
y exporta los reportes JSON y Markdown.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from chimuelo_prime.backtesting.data_loader import HistoricalDataLoader
from chimuelo_prime.strategies.optimizer import (
    OptimizationParamGrid,
    StrategyParameterOptimizer,
)


def run_grid_optimization(
    symbols: list[str] | None = None,
    intervals: list[str] | None = None,
    days: int = 60,
    initial_cash: Decimal = Decimal("25.00"),
    min_trades: int = 1,
    max_drawdown_limit: Decimal = Decimal("8.00"),
    target_profit_factor: Decimal = Decimal("1.80"),
    output_dir: Path = Path("data/reports"),
    cache_dir: str = "data/cache",
    force_download: bool = False,
) -> int:
    """Ejecuta la optimización sobre todos los símbolos e intervalos especificados."""
    if symbols is None:
        symbols = ["SOLUSDT", "BTCUSDT"]
    if intervals is None:
        intervals = ["1h", "15m"]

    grid = OptimizationParamGrid(
        rsi_oversold_thresholds=[
            Decimal("35.0"),
            Decimal("36.0"),
            Decimal("38.0"),
            Decimal("40.0"),
            Decimal("42.0"),
        ],
        atr_sl_multipliers=[
            Decimal("1.2"),
            Decimal("1.5"),
            Decimal("2.0"),
        ],
        risk_reward_ratios=[
            Decimal("2.0"),
            Decimal("2.5"),
            Decimal("3.0"),
            Decimal("3.5"),
        ],
        lookback_bars_list=[20, 30, 40],
    )

    print("\n" + "=" * 85)
    print(" OPTIMIZADOR DE HIPERPARÁMETROS CUANTITATIVOS — CHIMUELO PRIME ".center(85, "="))
    print("=" * 85)
    print(f"\n[+] Configuración de Optimización:")
    print(f"  • Símbolos:                {', '.join(symbols)}")
    print(f"  • Intervalos:              {', '.join(intervals)}")
    print(f"  • Ventana Histórica:       {days} días")
    print(f"  • Capital Inicial:         ${initial_cash:.2f} USDT")
    print(f"  • Total Combinaciones/Par: {grid.total_combinations}")
    print(f"  • Criterio Ganador:        Profit Factor >= {target_profit_factor} & Max Drawdown <= {max_drawdown_limit}%")
    print(f"  • Directorio de Salida:    {output_dir.resolve()}\n")

    loader = HistoricalDataLoader(
        base_url="https://api.binance.com",
        cache_dir=cache_dir,
    )

    end_time = datetime.now(UTC).replace(tzinfo=None)
    start_time = end_time - timedelta(days=days)
    output_dir.mkdir(parents=True, exist_ok=True)

    summary_list = []

    for symbol in symbols:
        for interval in intervals:
            print("-" * 85)
            print(f"[+] Evaluando Rejilla para {symbol} ({interval})...")
            try:
                candles = loader.get_candles(
                    symbol=symbol,
                    interval=interval,
                    start_time=start_time,
                    end_time=end_time,
                    force_download=force_download,
                )

                if not candles:
                    print(f"[!] Sin velas disponibles para {symbol} {interval}.")
                    continue

                print(f"[+] Velas cargadas: {len(candles)} | Rango: {candles[0].timestamp} -> {candles[-1].timestamp}")

                optimizer = StrategyParameterOptimizer(
                    candles=candles,
                    symbol=symbol,
                    interval=interval,
                    initial_cash=initial_cash,
                )

                summary = optimizer.run_optimization(
                    grid=grid,
                    min_trades=min_trades,
                    max_drawdown_limit=max_drawdown_limit,
                    target_profit_factor=target_profit_factor,
                )

                summary_list.append(summary)

                # Exportar JSON
                json_file = output_dir / f"optimization_{symbol.lower()}_{interval}.json"
                optimizer.export_summary_json(summary, json_file)
                print(f"[+] Resumen JSON guardado en: {json_file.resolve()}")

                # Mostrar informe en terminal
                report_md = optimizer.format_markdown_report(summary, top_n=5)
                print(f"\n{report_md}\n")

            except Exception as exc:
                print(f"[!] Error optimizando {symbol} ({interval}): {exc}")
                import traceback
                traceback.print_exc()

    print("=" * 85)
    print(" RESUMEN GLOBAL DE CONFIGURACIONES GANADORAS ".center(85, "="))
    print("=" * 85)
    for s in summary_list:
        b = s.best_result
        if b:
            p = b.params
            print(f"\n[{s.symbol} - {s.interval}]")
            print(f"  • Profit Factor: {b.profit_factor:.2f} | Max Drawdown: {b.max_drawdown_pct:.2f}% | Retorno: {b.total_return_pct:+.2f}% (${b.net_profit_usd:+.2f})")
            print(f"  • Trades: {b.total_trades} (W:{b.winning_trades} / L:{b.losing_trades}) | Win Rate: {b.win_rate_pct:.1f}% | Sortino: {b.sortino_ratio:.2f}")
            print(f"  • Parámetros: RSI_OS={p.get('rsi_oversold_threshold')} | ATR_SL={p.get('atr_sl_multiplier')} | R:R={p.get('risk_reward_ratio')} | Lookback={p.get('lookback_bars')}")
        else:
            print(f"\n[{s.symbol} - {s.interval}] Sin candidato ganador.")

    print("\n" + "=" * 85 + "\n")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Optimizador de Hiperparámetros Cuantitativos (Chimuelo Prime)"
    )
    parser.add_argument("--symbols", type=str, nargs="+", default=["SOLUSDT", "BTCUSDT"])
    parser.add_argument("--intervals", type=str, nargs="+", default=["1h", "15m"])
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--initial-cash", type=Decimal, default=Decimal("25.00"))
    parser.add_argument("--min-trades", type=int, default=1)
    parser.add_argument("--max-dd", type=Decimal, default=Decimal("8.00"))
    parser.add_argument("--target-pf", type=Decimal, default=Decimal("1.80"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/reports"))
    parser.add_argument("--force-download", action="store_true")

    args = parser.parse_args()
    code = run_grid_optimization(
        symbols=args.symbols,
        intervals=args.intervals,
        days=args.days,
        initial_cash=args.initial_cash,
        min_trades=args.min_trades,
        max_drawdown_limit=args.max_dd,
        target_profit_factor=args.target_pf,
        output_dir=args.output_dir,
        force_download=args.force_download,
    )
    sys.exit(code)


if __name__ == "__main__":
    main()
