"""Lanzador del Servidor Web FastAPI del Dashboard de Chimuelo Prime.

Inicia el servidor Uvicorn en http://localhost:8000 (o el host/puerto configurado)
proporcionando acceso a la API REST de mercado, endpoints de Paper Trading,
WebSockets de telemetría en tiempo real y la interfaz visual del Dashboard.
"""

from __future__ import annotations

import argparse
import sys

# Asegurar soporte de encoding UTF-8 en consolas Windows
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass

import uvicorn


def print_banner(host: str, port: int, reload: bool) -> None:
    """Imprime un banner estilizado al levantar el servidor de dashboard."""
    display_host = "localhost" if host in ("127.0.0.1", "0.0.0.0") else host
    print("\n" + "=" * 80)
    print(" CHIMUELO PRIME — DASHBOARD SERVER (FASTAPI + WEBSOCKETS) ".center(80, "="))
    print("=" * 80)
    print(f"\n[+] Servidor Dashboard Activo:")
    print(f"  • URL Dashboard:        http://{display_host}:{port}/")
    print(f"  • Documentación API:    http://{display_host}:{port}/docs")
    print(f"  • Endpoint Klines:      http://{display_host}:{port}/api/market/klines?symbol=SOLUSDT&interval=1h")
    print(f"  • Endpoint Ticker:      http://{display_host}:{port}/api/market/ticker?symbol=SOLUSDT")
    print(f"  • Paper Trading Status: http://{display_host}:{port}/api/paper/status")
    print(f"  • Stream WebSocket:     ws://{display_host}:{port}/ws/live")
    print(f"  • Auto-Reload:          {'Activado' if reload else 'Desactivado'}")
    print("\n[+] Presione Ctrl+C para detener el servidor.\n")
    print("=" * 80 + "\n")


def main(args_list: list[str] | None = None) -> None:
    """Punto de entrada principal CLI para iniciar el servidor de Dashboard."""
    parser = argparse.ArgumentParser(
        description="Lanzador Uvicorn para el Dashboard Web de Chimuelo Prime"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Dirección IP de escucha (default: 0.0.0.0)",
    )
    import os
    default_port = int(os.getenv("PORT", 8000))
    parser.add_argument(
        "--port",
        type=int,
        default=default_port,
        help=f"Puerto HTTP de escucha (default: {default_port})",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Habilitar auto-reload para desarrollo",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Número de procesos worker para Uvicorn (default: 1)",
    )

    args = parser.parse_args(args_list)

    print_banner(host=args.host, port=args.port, reload=args.reload)

    try:
        uvicorn.run(
            "chimuelo_prime.orchestrator.dashboard_server:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
            workers=args.workers if not args.reload else 1,
            log_level="info",
        )
    except KeyboardInterrupt:
        print("\n[!] Servidor detenido por el usuario.")
    except Exception as exc:
        print(f"\n[!] Error crítico iniciando el servidor Uvicorn: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
