"""Script de demostración del Módulo 6: Backtesting Engine.

Carga la configuración de `config/chimuelo.yaml`, obtiene filtros de Binance,
descarga velas históricas reales de SOLUSDT, realiza la simulación en ambos
modos (Estricto y Continuo) y genera un reporte comparativo premium.

Ejecución:
    python demo_m6.py
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from chimuelo_prime.backtesting.data_loader import HistoricalDataLoader
from chimuelo_prime.backtesting.engine import BacktestSimulator
from chimuelo_prime.backtesting.reporter import BacktestReporter
from chimuelo_prime.exchange_config import (
    BinancePublicClient,
    ExchangeConfigService,
    configure_logging,
)
from chimuelo_prime.exchange_config.config_loader import load_config
from chimuelo_prime.exchange_config.models import SymbolConfig

_CONFIG_PATH = Path("config/chimuelo.yaml")
SEP = "=" * 80


def main() -> None:
    print("\n" + SEP)
    print(f" INICIANDO DEMOSTRACIÓN — MÓDULO 6: BACKTESTING ENGINE ".center(80, " "))
    print(SEP + "\n")

    # 1. Cargar Configuración del Bot
    config = load_config(_CONFIG_PATH)
    configure_logging(level=config.logging.level, fmt="console")

    print("[+] Cargando configuración de exchange...")
    client = BinancePublicClient(
        base_url=config.active_env.base_url,
        timeout=config.active_env.http_timeout_seconds,
    )
    service = ExchangeConfigService(client)

    symbol = "SOLUSDT"
    print(f"[+] Consultando filtros de trading reales para {symbol}...")
    filters = service.fetch_symbol_filters(symbol)
    client.close()

    # 2. Descargar Velas Históricas
    # Descargamos los últimos 15 días de velas de 1h
    loader = HistoricalDataLoader(
        base_url=config.active_env.base_url,
        cache_dir="data/cache",
    )
    end_time = datetime.now(UTC).replace(tzinfo=None)
    start_time = end_time - timedelta(days=15)

    print(f"[+] Descargando/Cargando velas históricas de 1h para {symbol}...")
    print(f"    Rango: {start_time.date()} al {end_time.date()} (15 días)")
    candles = loader.get_candles(
        symbol=symbol,
        interval="1h",
        start_time=start_time,
        end_time=end_time,
    )

    if not candles:
        print("[!] Error: No se recibieron velas históricas. Saliendo.")
        return

    # 3. Configuración Dinámica de la Estrategia (Grid centrado en spot inicial)
    spot_inicial = candles[0].open
    print(f"\n[+] Precio spot al inicio del backtest: {spot_inicial} USDT")

    # Configurar límites: +/- 10% alrededor del spot inicial
    lower_bound = filters.round_price_to_tick(spot_inicial * Decimal("0.90"))
    upper_bound = filters.round_price_to_tick(spot_inicial * Decimal("1.10"))
    grid_levels = 10
    capital_per_order = Decimal("20.00")  # Garantiza superar min_notional de 5 USDT

    print(f"[+] Creando SymbolConfig dinámico:")
    print(f"    • Rango del Grid: [{lower_bound} - {upper_bound}] USDT")
    print(f"    • Niveles: {grid_levels}")
    print(f"    • Capital por orden: {capital_per_order} USDT")

    symbol_config = SymbolConfig(
        filters=filters,
        upper_bound=upper_bound,
        lower_bound=lower_bound,
        grid_levels=grid_levels,
        capital_per_order=capital_per_order,
    )

    # 4. Simulación 1: Modo Estricto (M5)
    print(f"\n" + "-" * 80)
    print(f" SIMULACIÓN 1: MODO ESTRICTO (GridEngine M5 standard) ".center(80, " "))
    print("-" * 80)

    # El capital inicial total es capital_per_order * grid_levels
    initial_cash = capital_per_order * Decimal(grid_levels)
    simulator_strict = BacktestSimulator(
        config=symbol_config,
        candles=candles,
        initial_cash=initial_cash,
        fee_rate=Decimal("0.001"),  # 0.1% de comisión Binance estándar
    )
    report_strict = simulator_strict.run(recreate_buy_on_sell_fill=False)
    reporter_strict = BacktestReporter(report_strict)
    reporter_strict.print_terminal_report()

    # 5. Simulación 2: Modo Continuo
    print(f"\n" + "-" * 80)
    print(f" SIMULACIÓN 2: MODO CONTINUO (Re-colocación ilimitada) ".center(80, " "))
    print("-" * 80)

    simulator_continuous = BacktestSimulator(
        config=symbol_config,
        candles=candles,
        initial_cash=initial_cash,
        fee_rate=Decimal("0.001"),
    )
    report_continuous = simulator_continuous.run(recreate_buy_on_sell_fill=True)
    reporter_continuous = BacktestReporter(report_continuous)
    reporter_continuous.print_terminal_report()

    # 6. Guardar reportes locales en JSON
    print("[+] Exportando reportes consolidados a 'data/reports/'...")
    reporter_strict.export_json("data/reports/backtest_strict_solusdt.json")
    reporter_continuous.export_json("data/reports/backtest_continuous_solusdt.json")

    # Comparación sintética final
    print("\n" + "=" * 80)
    print(f" COMPARATIVA FINAL ".center(80, "="))
    print("=" * 80)
    print(f"  Métrica                       | Modo Estricto   | Modo Continuo")
    print(f"  " + "-" * 76)
    print(f"  Retorno Total (%)             | {report_strict.total_return_pct:>13.4f} % | {report_continuous.total_return_pct:>13.4f} %")
    print(f"  Máximo Drawdown (%)           | {report_strict.max_drawdown_pct:>13.4f} % | {report_continuous.max_drawdown_pct:>13.4f} %")
    print(f"  Profit Factor                 | {str(report_strict.profit_factor):>15} | {str(report_continuous.profit_factor):>15}")
    print(f"  Ratio de Sortino              | {str(report_strict.sortino_ratio):>15} | {str(report_continuous.sortino_ratio):>15}")
    print(f"  Operaciones Completadas       | {report_strict.completed_trades:>15} | {report_continuous.completed_trades:>15}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
