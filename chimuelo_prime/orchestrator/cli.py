"""Interfaz de Línea de Comandos (CLI) Premium para Chimuelo Prime (M7).

Provee los comandos:
    - start: Arranca el orquestador multi-activo en modo daemonizado/primer plano con PID tracking.
    - stop: Envía una señal de apagado graceful al orquestador activo leyendo el PID persistido.
    - status: Muestra un panel de control con el estado de salud, niveles de grid y patrimonio neto.
    - backtest: Ejecuta una simulación histórica con datos reales de Binance y reportes premium.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
import time
from pathlib import Path

from chimuelo_prime.backtesting.data_loader import HistoricalDataLoader
from chimuelo_prime.backtesting.engine import BacktestSimulator
from chimuelo_prime.backtesting.reporter import BacktestReporter
from chimuelo_prime.exchange_config.client import BinancePublicClient
from chimuelo_prime.exchange_config.service import ExchangeConfigService
from chimuelo_prime.orchestrator.config_manager import load_orchestrator_config
from chimuelo_prime.orchestrator.orchestrator import Orchestrator


def is_pid_alive(pid: int) -> bool:
    """Verifica si un proceso con el PID dado está activo.

    Funciona de forma nativa tanto en Windows (usando tasklist) como en Unix (usando os.kill).
    """
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            import subprocess

            output = subprocess.check_output(
                ["tasklist", "/FI", f"PID eq {pid}"],
                creationflags=subprocess.CREATE_NO_WINDOW
                if hasattr(subprocess, "CREATE_NO_WINDOW")
                else 0,
            ).decode("utf-8", errors="ignore")
            return str(pid) in output
        else:
            os.kill(pid, 0)
            return True
    except Exception:
        return False


def start_bot(config_path: Path, db_url: str) -> None:
    """Valida procesos anteriores, registra el PID y arranca el orquestador principal."""
    pid_file = Path("data/chimuelo.pid")
    pid_file.parent.mkdir(parents=True, exist_ok=True)

    if pid_file.exists():
        try:
            old_pid = int(pid_file.read_text().strip())
            if is_pid_alive(old_pid):
                print(
                    f"\n[!] ERROR: El orquestador ya se encuentra en ejecución con PID: {old_pid}."
                )
                print("    Detén el proceso existente antes de iniciar uno nuevo.\n")
                sys.exit(1)
        except ValueError:
            pass

    current_pid = os.getpid()
    pid_file.write_text(str(current_pid))
    print("\n[+] Iniciando orquestador de Grid Trading Chimuelo Prime...")
    print(f"    • PID del Proceso: {current_pid}")
    print(f"    • Archivo de Configuración: {config_path.resolve()}")
    print(f"    • Base de Datos SQLite: {db_url}")
    print("    Presiona Ctrl+C para detener ordenadamente.\n")

    try:
        config = load_orchestrator_config(config_path)
        orchestrator = Orchestrator(config, db_url)
        orchestrator.start()
    except KeyboardInterrupt:
        print("\n[+] Ctrl+C detectado. Iniciando shutdown graceful...")
    except Exception as exc:
        print(f"\n[!] ERROR CRÍTICO al iniciar el orquestador: {exc}\n")
        sys.exit(1)
    finally:
        if pid_file.exists():
            with contextlib.suppress(Exception):
                pid_file.unlink()
        print("[+] Orquestador apagado y PID tracking liberado.\n")


def stop_bot() -> None:
    """Solicita la detención graceful del orquestador mediante señales de interrupción."""
    pid_file = Path("data/chimuelo.pid")
    if not pid_file.exists():
        print(
            "\n[-] El orquestador no se encuentra en ejecución (no se encontró archivo PID en data/chimuelo.pid).\n"
        )
        return

    try:
        pid = int(pid_file.read_text().strip())
    except Exception:
        print("\n[-] Archivo PID inválido o corrupto. Limpiando tracking...\n")
        with contextlib.suppress(Exception):
            pid_file.unlink()
        return

    if not is_pid_alive(pid):
        print(
            f"\n[-] El proceso con PID: {pid} no se encuentra activo. Limpiando PID tracking...\n"
        )
        with contextlib.suppress(Exception):
            pid_file.unlink()
        return

    print(f"\n[+] Deteniendo el orquestador (PID: {pid})...")
    import signal

    try:
        if os.name == "nt":
            os.kill(pid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGINT)

        # Esperar con timeout para verificar cierre graceful
        for _ in range(15):
            time.sleep(1.0)
            if not is_pid_alive(pid):
                print("[+] Orquestador detenido exitosamente de manera limpia.")
                if pid_file.exists():
                    with contextlib.suppress(Exception):
                        pid_file.unlink()
                print()
                return

        print(
            "[!] ADVERTENCIA: El orquestador no se cerró en el tiempo esperado y podría continuar en ejecución.\n"
        )
    except Exception as exc:
        print(f"[!] Error al detener el proceso: {exc}\n")


def show_status(db_url: str, config_path: Path) -> None:
    """Renderiza un panel de control con el estado de salud, niveles activos y balances."""
    pid_file = Path("data/chimuelo.pid")
    is_active = False
    bot_pid = 0
    if pid_file.exists():
        try:
            bot_pid = int(pid_file.read_text().strip())
            is_active = is_pid_alive(bot_pid)
        except Exception:
            pass

    print("\n" + "=" * 80)
    print(" ESTADO DE OPERACIÓN — CHIMUELO PRIME ".center(80, "="))
    print("=" * 80)

    if is_active:
        print(f"🟢 ESTADO: ACTIVO (Ejecutándose bajo PID: {bot_pid})")
    else:
        print("🔴 ESTADO: INACTIVO (El bot no está en ejecución)")

    db_file_path = "chimuelo.db"
    if db_url.startswith("sqlite:///"):
        db_file_path = db_url[len("sqlite:///") :].split("?")[0]

    db_path = Path(db_file_path)
    if not db_path.exists():
        print("\n[-] Base de datos no encontrada. ¿Se ha iniciado el bot al menos una vez?")
        print("=" * 80 + "\n")
        return

    try:
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import Session

        from chimuelo_prime.grid_state.schema import GridLevel, Order, Snapshot

        # Conectar al engine. WAL permite lecturas concurrentes de forma segura.
        engine = create_engine(db_url)

        # Cargar símbolos de configuración, o deducirlos desde la base de datos si falla
        try:
            config = load_orchestrator_config(config_path)
            symbols = config.symbols
        except Exception:
            with Session(engine) as session:
                symbols = [
                    str(r) for r in session.scalars(select(GridLevel.symbol).distinct()).all()
                ]

        for symbol in symbols:
            print(f"\n📈 SÍMBOLO: {symbol}")
            print("-" * 80)

            with Session(engine) as session:
                # 1. Obtener niveles de grid
                levels = session.scalars(
                    select(GridLevel)
                    .where(GridLevel.symbol == symbol)
                    .order_by(GridLevel.lower_price.desc())
                ).all()

                # 2. Obtener último Snapshot de portafolio
                latest_snapshot = session.scalars(
                    select(Snapshot)
                    .where(Snapshot.symbol == symbol)
                    .order_by(Snapshot.snapshot_id.desc())
                    .limit(1)
                ).first()

                if latest_snapshot:
                    print("💰 RESUMEN DE SALDOS:")
                    print(f"  • Patrimonio Neto (Equity): {latest_snapshot.equity:>15} USDT")
                    print(
                        f"  • Inventario de Base:       {latest_snapshot.inventory:>15} {symbol[:-4]}"
                    )
                    print(f"  • Efectivo Disponible (Cash):{latest_snapshot.cash:>15} USDT")
                    print(f"  • Último Snapshot:          {latest_snapshot.created_at} UTC")
                else:
                    print("💰 RESUMEN DE SALDOS: No hay snapshots registrados aún.")

                print("\n📊 GEOMETRÍA Y NIVELES DE GRID:")
                if not levels:
                    print("  No hay niveles de grid persistidos en la base de datos.")
                else:
                    print(
                        f"  {'Nivel ID':<10} | {'Rango de Precio (USDT)':<28} | {'Compra ID':<12} | {'Venta ID':<12} | {'Estado Actual'}"
                    )
                    print("  " + "-" * 78)
                    for lvl in levels:
                        status = "Inactivo"
                        buy_status = ""
                        sell_status = ""

                        if lvl.buy_order_id:
                            b_order = session.get(Order, lvl.buy_order_id)
                            if b_order:
                                buy_status = b_order.status

                        if lvl.sell_order_id:
                            s_order = session.get(Order, lvl.sell_order_id)
                            if s_order:
                                sell_status = s_order.status

                        if sell_status == "FILLED":
                            status = "🟢 FILLED (SELL)"
                        elif sell_status in ("NEW", "PARTIALLY_FILLED"):
                            status = "🔵 ACTIVE (SELL)"
                        elif buy_status == "FILLED":
                            status = "🟡 FILLED (BUY) / NO SELL"
                        elif buy_status in ("NEW", "PARTIALLY_FILLED"):
                            status = "🔵 ACTIVE (BUY)"
                        elif buy_status in ("CANCELED", "EXPIRED", "REJECTED"):
                            status = "🔴 CANCELED (BUY)"
                        elif sell_status in ("CANCELED", "EXPIRED", "REJECTED"):
                            status = "🔴 CANCELED (SELL)"

                        price_range = f"{lvl.lower_price} - {lvl.upper_price}"
                        buy_cell = str(lvl.buy_order_id) if lvl.buy_order_id else "None"
                        sell_cell = str(lvl.sell_order_id) if lvl.sell_order_id else "None"
                        print(
                            f"  {lvl.level_id:<10} | {price_range:<28} | {buy_cell:<12} | {sell_cell:<12} | {status}"
                        )

        engine.dispose()
    except Exception as exc:
        print(f"\n[!] Error al leer el estado de la base de datos: {exc}")

    print("\n" + "=" * 80)
    print(" FIN DEL REPORTE ".center(80, "="))
    print("=" * 80 + "\n")


def run_backtest(config_path: Path, symbol: str, days: int, interval: str, strict: bool) -> None:
    """Descarga velas de Binance, inicializa el simulador y corre el backtest de la estrategia."""
    print(f"\n[+] Iniciando simulación de Backtesting para {symbol}...")
    try:
        from datetime import UTC, datetime, timedelta
        from decimal import Decimal

        from chimuelo_prime.exchange_config.models import SymbolConfig

        # 1. Cargar Configuración del Bot
        config = load_orchestrator_config(config_path)
        has_config_strategy = symbol in config.strategies

        # 2. Consultar filtros reales en Binance
        print("[+] Cargando configuración de exchange y filtros...")
        client = BinancePublicClient(
            base_url=config.active_env.base_url,
            timeout=config.active_env.http_timeout_seconds,
        )
        service = ExchangeConfigService(client)
        filters = service.fetch_symbol_filters(symbol)
        client.close()

        # 3. Descargar velas
        loader = HistoricalDataLoader(
            base_url=config.active_env.base_url,
            cache_dir="data/cache",
        )
        end_time = datetime.now(UTC).replace(tzinfo=None)
        start_time = end_time - timedelta(days=days)

        print(f"[+] Cargando velas históricas de {interval} ({days} días)...")
        candles = loader.get_candles(
            symbol=symbol,
            interval=interval,
            start_time=start_time,
            end_time=end_time,
        )

        if not candles:
            print("[!] ERROR: No se recuperaron velas históricas para simular.\n")
            return

        spot_inicial = candles[0].open
        print(f"[+] Precio spot inicial: {spot_inicial} USDT")

        # 4. Construir SymbolConfig
        if has_config_strategy:
            strategy = config.strategies[symbol]
            print(
                f"[+] Utilizando parámetros de estrategia definidos para {symbol} en '{config_path.name}'"
            )
            symbol_config = SymbolConfig(
                filters=filters,
                upper_bound=strategy.upper_bound,
                lower_bound=strategy.lower_bound,
                grid_levels=strategy.grid_levels,
                capital_per_order=strategy.capital_per_order,
                capital_weight=strategy.capital_weight,
            )
        else:
            print(
                f"[!] Símbolo {symbol} sin estrategia configurada. Usando grid defensivo +/- 10% alrededor del spot inicial."
            )
            lower_bound = filters.round_price_to_tick(spot_inicial * Decimal("0.90"))
            upper_bound = filters.round_price_to_tick(spot_inicial * Decimal("1.10"))
            grid_levels = 10
            capital_per_order = Decimal("20.00")
            symbol_config = SymbolConfig(
                filters=filters,
                upper_bound=upper_bound,
                lower_bound=lower_bound,
                grid_levels=grid_levels,
                capital_per_order=capital_per_order,
            )

        # 5. Ejecutar simulación
        initial_cash = symbol_config.capital_per_order * Decimal(symbol_config.grid_levels)
        simulator = BacktestSimulator(
            config=symbol_config,
            candles=candles,
            initial_cash=initial_cash,
            fee_rate=Decimal("0.001"),
        )

        recreate = not strict
        report = simulator.run(recreate_buy_on_sell_fill=recreate)

        # 6. Reportar y guardar resultados
        reporter = BacktestReporter(report)
        reporter.print_terminal_report()

        report_dir = Path("data/reports")
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = (
            report_dir / f"backtest_{symbol.lower()}_{'strict' if strict else 'continuous'}.json"
        )
        reporter.export_json(report_path)
        print(f"[+] Resultados del backtest exportados correctamente a: {report_path.resolve()}\n")

    except Exception as exc:
        print(f"\n[!] ERROR al ejecutar backtest: {exc}\n")


def run_gui(host: str, port: int, config_path: Path, db_url: str) -> None:
    """Arranca el servidor web FastAPI para el Dashboard de Chimuelo Prime."""
    print(f"\n[+] Iniciando Dashboard Web de Chimuelo Prime en http://{host}:{port} ...")
    try:
        import uvicorn

        from chimuelo_prime.orchestrator.web_server import BotManager, app

        # Guardar rutas iniciales en el BotManager
        manager = BotManager.get_instance()
        manager.config_path = config_path
        manager.db_url = db_url

        uvicorn.run(app, host=host, port=port)
    except Exception as exc:
        print(f"\n[!] ERROR al levantar la interfaz web: {exc}\n")


def main() -> None:
    """Punto de entrada de CLI: parsea argumentos y enruta subcomandos."""
    parser = argparse.ArgumentParser(
        description="CLI Premium de Chimuelo Prime - Operación y Simulación de Grid Trading"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/chimuelo.yaml"),
        help="Ruta al archivo de configuración YAML (default: config/chimuelo.yaml)",
    )
    parser.add_argument(
        "--db",
        type=str,
        default="sqlite:///chimuelo.db",
        help="URL de base de datos SQLite (default: sqlite:///chimuelo.db)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True, help="Subcomandos")

    # Comando start
    subparsers.add_parser("start", help="Arranca el orquestador multi-activo en primer plano")

    # Comando stop
    subparsers.add_parser("stop", help="Detiene de forma graceful el orquestador activo")

    # Comando status
    subparsers.add_parser("status", help="Muestra el panel de control de saldos y niveles de grid")

    # Comando backtest
    backtest_parser = subparsers.add_parser("backtest", help="Ejecuta simulación histórica offline")
    backtest_parser.add_argument(
        "--symbol",
        type=str,
        default="SOLUSDT",
        help="Símbolo a simular (default: SOLUSDT)",
    )
    backtest_parser.add_argument(
        "--days",
        type=int,
        default=15,
        help="Días de velas históricas a descargar (default: 15)",
    )
    backtest_parser.add_argument(
        "--interval",
        type=str,
        default="1h",
        help="Intervalo de velas (default: 1h)",
    )
    backtest_parser.add_argument(
        "--strict",
        action="store_true",
        help="Utiliza modo estricto de simulación (sin re-colocación ilimitada)",
    )

    # Comando gui
    gui_parser = subparsers.add_parser("gui", help="Levanta la interfaz gráfica web FastAPI")
    gui_parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host para el servidor web (default: 127.0.0.1)",
    )
    gui_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Puerto para el servidor web (default: 8000)",
    )

    args = parser.parse_args()

    if args.command == "start":
        start_bot(args.config, args.db)
    elif args.command == "stop":
        stop_bot()
    elif args.command == "status":
        show_status(args.db, args.config)
    elif args.command == "backtest":
        run_backtest(args.config, args.symbol, args.days, args.interval, args.strict)
    elif args.command == "gui":
        run_gui(args.host, args.port, args.config, args.db)


if __name__ == "__main__":
    main()
