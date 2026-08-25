"""Script CLI y Ejecutor de Paper Trading en Vivo para Chimuelo Prime.

Conecta al API público de Binance para obtener velas en tiempo real (Klines),
evalúa la estrategia cuantitativa de reversión `RSIDivergenceStrategy`, ejecuta
operaciones simuladas con comisiones, slippage y gestión intrabarra en `VirtualBroker`,
y despacha alertas instantáneas y resúmenes periódicos de balance a Telegram
mediante `AlertManager` ($25.00 USDT iniciales).
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from typing import Any

# Asegurar soporte completo de caracteres UTF-8 (emojis) en consolas Windows
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass

from chimuelo_prime.orchestrator.monitoring import AlertManager
from chimuelo_prime.paper_trading.engine import (
    PaperTradingConfig,
    PaperTradingEngine,
)
from chimuelo_prime.paper_trading.virtual_broker import VirtualBroker
from chimuelo_prime.strategies.rsi_divergence import RSIDivergenceStrategy


def print_banner(config: PaperTradingConfig, max_iterations: int | None = None) -> None:
    """Imprime un banner informativo y estilizado al iniciar el motor."""
    print("\n" + "=" * 80)
    print(" MOTOR DE PAPER TRADING EN VIVO — CHIMUELO PRIME ".center(80, "="))
    print("=" * 80)
    print("\n[+] Configuración de Operación:")
    print(f"  • Símbolo:              {config.symbol.upper()}")
    print(f"  • Intervalo de Velas:   {config.interval}")
    print(f"  • Capital Inicial:      ${config.initial_balance:.2f} USDT")
    print(f"  • Tasa de Comisión:     {config.fee_rate * Decimal('100'):.2f}%")
    print(f"  • Slippage Simulado:    {config.slippage_pct * Decimal('100'):.3f}%")
    print(f"  • Notional Mínimo:      ${config.min_notional:.2f} USDT")
    print(f"  • Sondeo en Vivo:       cada {config.poll_interval_seconds:.1f}s")
    print(f"  • Reporte Telegram:     cada {config.report_interval_seconds:.1f}s")
    print(f"  • API Binance:          {config.base_url}")
    print(f"  • Límite de Velas:      {config.candle_limit}")
    if max_iterations:
        print(f"  • Ciclos Máximos:       {max_iterations}")
    print("\n[+] Conectando al feed público de Binance y monitoreando mercado...")
    print("[+] Presione Ctrl+C para detener la ejecución de forma segura.\n")


def run_paper_trading_service(
    symbol: str = "SOLUSDT",
    interval: str = "15m",
    initial_cash: Decimal = Decimal("25.00"),
    fee_rate: Decimal = Decimal("0.001"),
    slippage_pct: Decimal = Decimal("0.0005"),
    min_notional: Decimal = Decimal("5.00"),
    poll_interval: float = 10.0,
    report_interval: float = 3600.0,
    candle_limit: int = 300,
    base_url: str = "https://api.binance.com",
    max_iterations: int | None = None,
    alert_manager: AlertManager | None = None,
    engine: PaperTradingEngine | None = None,
) -> int:
    """Inicializa y ejecuta el servicio de Paper Trading en vivo."""
    config = PaperTradingConfig(
        symbol=symbol,
        interval=interval,
        initial_balance=initial_cash,
        fee_rate=fee_rate,
        slippage_pct=slippage_pct,
        min_notional=min_notional,
        poll_interval_seconds=poll_interval,
        report_interval_seconds=report_interval,
        candle_limit=candle_limit,
        base_url=base_url,
    )

    print_banner(config, max_iterations)

    if engine is None:
        mgr = alert_manager or AlertManager()
        broker = VirtualBroker(
            initial_balance=config.initial_balance,
            fee_rate=config.fee_rate,
            slippage_pct=config.slippage_pct,
            min_notional=config.min_notional,
            alert_manager=mgr,
        )
        strategy = RSIDivergenceStrategy(
            symbol=config.symbol,
            rsi_oversold_threshold=Decimal("38.0"),
            lookback_bars=30,
            volume_multiplier=Decimal("1.1"),
            atr_sl_multiplier=Decimal("1.2"),
            risk_reward_ratio=Decimal("2.0"),
        )
        engine = PaperTradingEngine(
            config=config,
            broker=broker,
            strategy=strategy,
            alert_manager=mgr,
        )

    try:
        engine.start(max_iterations=max_iterations)
    except KeyboardInterrupt:
        print("\n[!] Ejecución cancelada por el usuario.")
    except Exception as exc:
        print(f"\n[!] Error crítico en Paper Trading: {exc}")
        return 1

    state = engine.broker.get_state()
    print("\n" + "=" * 80)
    print(" RESUMEN FINAL DE PAPER TRADING ".center(80, "="))
    print("=" * 80)
    print(f"  • Saldo Efectivo Final:     ${state.cash:.2f} USDT")
    print(f"  • Patrimonio Total Final:   ${state.equity:.2f} USDT")
    print(f"  • PnL Realizado Acumulado:  ${state.total_realized_pnl:+.4f} USDT")
    print(f"  • Total Trades Cerrados:    {state.total_trades_count}")
    print("=" * 80 + "\n")

    return 0


def main(args_list: list[str] | None = None) -> None:
    """Punto de entrada CLI para Paper Trading en vivo."""
    parser = argparse.ArgumentParser(
        description="Ejecutor de Paper Trading en Vivo con Binance y Telegram (Chimuelo Prime)"
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default="SOLUSDT",
        help="Símbolo del par de trading a operar (default: SOLUSDT)",
    )
    parser.add_argument(
        "--interval",
        type=str,
        default="1h",
        help="Intervalo temporal de las velas (default: 1h)",
    )
    parser.add_argument(
        "--initial-cash",
        type=Decimal,
        default=Decimal("100.00"),
        help="Capital inicial simulado en USDT (default: 100.00)",
    )
    parser.add_argument(
        "--fee-rate",
        type=Decimal,
        default=Decimal("0.001"),
        help="Tasa de comisión simulada (default: 0.001 / 0.1%%)",
    )
    parser.add_argument(
        "--slippage",
        type=Decimal,
        default=Decimal("0.0005"),
        help="Slippage porcentual por orden (default: 0.0005 / 0.05%%)",
    )
    parser.add_argument(
        "--min-notional",
        type=Decimal,
        default=Decimal("5.00"),
        help="Notional mínimo en USD exigido por el exchange (default: 5.00)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=10.0,
        help="Segundos entre cada sondeo de mercado (default: 10.0)",
    )
    parser.add_argument(
        "--report-interval",
        type=float,
        default=3600.0,
        help="Segundos entre resúmenes periódicos de portafolio (default: 3600.0)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=300,
        help="Cantidad de velas históricas recientes a descargar (default: 300)",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default="https://api.binance.com",
        help="URL base de la API de Binance (default: https://api.binance.com)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Límite máximo de iteraciones antes de salir (default: None, bucle infinito)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Ejecutar exactamente un ciclo de sondeo y terminar (útil para dry runs/tests)",
    )

    parsed = parser.parse_args(args_list)

    max_iters = 1 if parsed.once else parsed.max_iterations

    exit_code = run_paper_trading_service(
        symbol=parsed.symbol,
        interval=parsed.interval,
        initial_cash=parsed.initial_cash,
        fee_rate=parsed.fee_rate,
        slippage_pct=parsed.slippage,
        min_notional=parsed.min_notional,
        poll_interval=parsed.poll_interval,
        report_interval=parsed.report_interval,
        candle_limit=parsed.limit,
        base_url=parsed.base_url,
        max_iterations=max_iters,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
