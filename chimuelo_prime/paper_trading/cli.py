"""CLI para la ejecución y control de Live Paper Trading, Shadow Mode y Replay."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from chimuelo_prime.backtesting.data_loader import HistoricalCandle, HistoricalDataLoader
from chimuelo_prime.exchange_config.logger import get_logger
from chimuelo_prime.paper_trading.live_runner import LivePaperRunner
from chimuelo_prime.paper_trading.persistence import SQLitePersistenceBackend
from chimuelo_prime.paper_trading.replay_harness import ReplayHarness


def print_banner(mode: str) -> None:
    print("=" * 80)
    print(f" CHIMUELO PRIME — ENGINE [{mode.upper()}] ".center(80, "="))
    print(" Strategy C v1.0.0-frozen | Timeframe: 1H | Activos: BTCUSDT, SOLUSDT ".center(80))
    print(" Reglas: Breakout 20 + BTC EMA50 1D + Vol P70 + Rango >= 4 ATR ".center(80))
    print("=" * 80)


def run_replay(symbol: str, count: int = 200) -> None:
    print_banner("REPLAY DETERMINISTA")
    loader = HistoricalDataLoader(cache_dir="data/cache_extended")
    end_dt = datetime(2026, 9, 1, 0, 0, 0)
    start_dt = end_dt - timedelta(hours=count)
    candles_1h = loader.get_candles(symbol, interval="1h", start_time=start_dt, end_time=end_dt)
    btc_raw_1h = loader.get_candles("BTCUSDT", interval="1h", start_time=start_dt - timedelta(days=60), end_time=end_dt)

    candles_1h_utc = [
        HistoricalCandle(
            timestamp=c.timestamp.replace(tzinfo=UTC) if c.timestamp.tzinfo is None else c.timestamp,
            open=c.open,
            high=c.high,
            low=c.low,
            close=c.close,
            volume=c.volume,
        )
        for c in candles_1h
    ]

    # Convertir a diarias para BTC
    btc_daily_utc: list[HistoricalCandle] = []
    curr: list[HistoricalCandle] = []
    for c in btc_raw_1h:
        c_utc = HistoricalCandle(
            timestamp=c.timestamp.replace(tzinfo=UTC) if c.timestamp.tzinfo is None else c.timestamp,
            open=c.open,
            high=c.high,
            low=c.low,
            close=c.close,
            volume=c.volume,
        )
        if not curr:
            curr.append(c_utc)
        elif c_utc.timestamp.date() == curr[0].timestamp.date():
            curr.append(c_utc)
        else:
            btc_daily_utc.append(
                HistoricalCandle(
                    timestamp=curr[0].timestamp.replace(hour=0, minute=0, second=0),
                    open=curr[0].open,
                    high=max(x.high for x in curr),
                    low=min(x.low for x in curr),
                    close=curr[-1].close,
                    volume=sum(x.volume for x in curr),
                )
            )
            curr = [c_utc]

    harness = ReplayHarness(symbol=symbol, db_path="data/replay_cli.db")
    print(f"[+] Iniciando Replay para {symbol} ({len(candles_1h_utc)} velas 1h)...")
    decisions = harness.run_replay(
        candles_1h=candles_1h_utc,
        btc_daily_candles=btc_daily_utc,
        execute_paper=True,
    )
    signals = [d for d in decisions if d.action.value == "SIGNAL_GENERATED"]
    print(f"[+] Replay completado: {len(decisions)} evaluaciones | {len(signals)} señales aprobadas.")


def run_live(shadow_only: bool) -> None:
    mode_name = "SHADOW MODE" if shadow_only else "LIVE PAPER TRADING"
    print_banner(mode_name)
    runner = LivePaperRunner(
        symbols=["BTCUSDT", "SOLUSDT"],
        initial_cash=Decimal("100.00"),
        persistence=SQLitePersistenceBackend("data/live_paper.db"),
        shadow_only=shadow_only,
    )
    print(f"[+] Modo {mode_name} iniciado correctamente. Esperando cierre de vela horaria (:00:05 UTC)...")


def main() -> None:
    parser = argparse.ArgumentParser(description="Chimuelo Prime Paper & Shadow Runner")
    parser.add_argument(
        "--mode",
        choices=["shadow", "paper", "replay"],
        default="shadow",
        help="Modo de ejecución: shadow, paper o replay",
    )
    parser.add_argument("--symbol", default="SOLUSDT", help="Símbolo para modo replay")
    parser.add_argument("--count", type=int, default=200, help="Cantidad de velas para replay")

    args = parser.parse_args()

    if args.mode == "replay":
        run_replay(args.symbol, args.count)
    elif args.mode == "shadow":
        run_live(shadow_only=True)
    elif args.mode == "paper":
        run_live(shadow_only=False)


if __name__ == "__main__":
    main()
