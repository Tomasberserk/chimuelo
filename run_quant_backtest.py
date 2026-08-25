"""Script CLI para ejecución de Backtesting Cuantitativo de Chimuelo Prime.

Descarga datos históricos de Binance para pares configurados (default: SOLUSDT en 15m y 1h),
ejecuta la estrategia cuantitativa de divergencia RSI (RSIDivergenceStrategy) mediante
el simulador de señales (SignalStrategyBacktester) sobre micro-cuentas ($25.00 USDT),
imprime reportes de rendimiento y exporta los resultados en formato JSON a data/reports/.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from chimuelo_prime.backtesting.data_loader import HistoricalDataLoader
from chimuelo_prime.backtesting.reporter import SignalBacktestReporter
from chimuelo_prime.backtesting.strategy_engine import SignalStrategyBacktester
from chimuelo_prime.strategies.rsi_divergence import RSIDivergenceStrategy


def run_quant_simulation(
    symbol: str = "SOLUSDT",
    intervals: list[str] | None = None,
    days: int = 60,
    initial_cash: Decimal = Decimal("25.00"),
    fee_rate: Decimal = Decimal("0.001"),
    slippage_pct: Decimal = Decimal("0.0005"),
    output_dir: Path = Path("data/reports"),
    cache_dir: str = "data/cache",
    force_download: bool = False,
) -> int:
    """Ejecuta el ciclo completo de backtest cuantitativo para las temporalidades dadas."""
    if intervals is None:
        intervals = ["15m", "1h"]

    print("\n" + "=" * 80)
    print(" MOTOR DE BACKTESTING CUANTITATIVO — CHIMUELO PRIME ".center(80, "="))
    print("=" * 80)
    print(f"\n[+] Configuración de Simulación:")
    print(f"  • Símbolo:              {symbol}")
    print(f"  • Intervalos:           {', '.join(intervals)}")
    print(f"  • Ventana Histórica:    {days} días")
    print(f"  • Capital Inicial:      ${initial_cash:.2f} USDT")
    print(f"  • Tasa de Comisión:     {fee_rate * Decimal('100'):.2f}%")
    print(f"  • Slippage Simulado:    {slippage_pct * Decimal('100'):.3f}%")
    print(f"  • Directorio de Salida: {output_dir.resolve()}\n")

    loader = HistoricalDataLoader(
        base_url="https://api.binance.com",
        cache_dir=cache_dir,
    )

    end_time = datetime.now(UTC).replace(tzinfo=None)
    start_time = end_time - timedelta(days=days)
    output_dir.mkdir(parents=True, exist_ok=True)

    success_count = 0

    for interval in intervals:
        print(f"\n[+] Descargando / Cargando velas históricas de {symbol} ({interval}, {days} días)...")
        try:
            candles = loader.get_candles(
                symbol=symbol,
                interval=interval,
                start_time=start_time,
                end_time=end_time,
                force_download=force_download,
            )

            if not candles:
                print(f"[!] ADVERTENCIA: No se obtuvieron velas para {symbol} en {interval}. Omitiendo.")
                continue

            print(f"[+] Total de velas cargadas: {len(candles)} | Primera: {candles[0].timestamp} | Última: {candles[-1].timestamp}")

            # Instanciar estrategia e inicializar backtester con parámetros calibrados
            strategy = RSIDivergenceStrategy(
                symbol=symbol,
                rsi_oversold_threshold=Decimal("42.0"),
                lookback_bars=35,
                volume_multiplier=Decimal("0.9"),
                risk_reward_ratio=Decimal("2.5"),
            )
            backtester = SignalStrategyBacktester(
                strategy=strategy,
                candles=candles,
                symbol=symbol,
                interval=interval,
                initial_cash=initial_cash,
                fee_rate=fee_rate,
                slippage_pct=slippage_pct,
            )

            print(f"[+] Ejecutando simulación para {strategy.name} en {interval}...")
            report = backtester.run()

            # Reportar en consola
            reporter = SignalBacktestReporter(report)
            reporter.print_terminal_report()

            # Exportar archivo JSON
            json_filename = f"quant_backtest_{symbol.lower()}_{interval}.json"
            json_path = output_dir / json_filename
            reporter.export_json(json_path)
            print(f"[+] Reporte exportado exitosamente a: {json_path.resolve()}")
            success_count += 1

        except Exception as exc:
            print(f"\n[!] ERROR durante la simulación de {symbol} ({interval}): {exc}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 80)
    print(f" SIMULACIÓN FINALIZADA: {success_count}/{len(intervals)} intervalos completados exitosamente. ".center(80, "="))
    print("=" * 80 + "\n")

    return 0 if success_count > 0 else 1


def main() -> None:
    """Punto de entrada CLI para ejecutar backtests cuantitativos."""
    parser = argparse.ArgumentParser(
        description="Backtester Cuantitativo de Estrategias Direccionales (Chimuelo Prime)"
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default="SOLUSDT",
        help="Símbolo del par a simular (default: SOLUSDT)",
    )
    parser.add_argument(
        "--intervals",
        type=str,
        nargs="+",
        default=["15m", "1h"],
        help="Lista de intervalos de velas (default: 15m 1h)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=60,
        help="Días de historial a descargar (default: 60)",
    )
    parser.add_argument(
        "--initial-cash",
        type=Decimal,
        default=Decimal("25.00"),
        help="Capital inicial en USD (default: 25.00)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/reports"),
        help="Directorio donde guardar los reportes JSON (default: data/reports)",
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Forzar descarga desde Binance ignorando caché local",
    )

    args = parser.parse_args()

    exit_code = run_quant_simulation(
        symbol=args.symbol,
        intervals=args.intervals,
        days=args.days,
        initial_cash=args.initial_cash,
        output_dir=args.output_dir,
        force_download=args.force_download,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
