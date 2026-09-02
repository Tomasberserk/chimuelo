"""Script de Backtesting Cuantitativo Comparativo: TP Ciego vs TP Estructural 75% + Salida RSI.

Compara el rendimiento sobre SOLUSDT, BTCUSDT y ETHUSDT en 1h y 15m (60 días, $100 USD capital inicial).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from chimuelo_prime.backtesting.data_loader import HistoricalCandle, HistoricalDataLoader
from chimuelo_prime.backtesting.strategy_engine import SignalStrategyBacktester
from chimuelo_prime.strategies.rsi_divergence import RSIDivergenceStrategy


def run_comparative_suite() -> dict[str, Any]:
    symbols = ["SOLUSDT", "BTCUSDT", "ETHUSDT"]
    intervals = ["1h", "15m"]
    initial_cash = Decimal("100.00")
    fee_rate = Decimal("0.001")
    slippage_pct = Decimal("0.0005")
    cache_dir = "data/cache"

    loader = HistoricalDataLoader(cache_dir=cache_dir)
    results: dict[str, Any] = {
        "metadata": {
            "initial_cash": float(initial_cash),
            "fee_rate": float(fee_rate),
            "slippage_pct": float(slippage_pct),
            "timestamp": datetime.now().isoformat(),
        },
        "comparisons": [],
    }

    print("=" * 90)
    print(" EJECUTANDO BACKTEST CUANTITATIVO COMPARATIVO: TP CIEGO VS TP ESTRUCTURAL 75% ".center(90, "="))
    print("=" * 90)

    for symbol in symbols:
        for interval in intervals:
            print(f"\n>>> Procesando {symbol} en temporalidad {interval}...")
            # Cargar desde caché
            cache_file = Path(cache_dir) / f"{symbol}_{interval}.json"
            if not cache_file.exists():
                print(f"[!] No existe archivo de caché: {cache_file}")
                continue

            with open(cache_file, encoding="utf-8") as f:
                raw_data = json.load(f)

            candles = [
                HistoricalCandle(
                    timestamp=datetime.fromtimestamp(item[0] / 1000.0),
                    open=Decimal(str(item[1])),
                    high=Decimal(str(item[2])),
                    low=Decimal(str(item[3])),
                    close=Decimal(str(item[4])),
                    volume=Decimal(str(item[5])),
                )
                for item in raw_data
            ]
            candles.sort(key=lambda c: c.timestamp)

            # Tomar los últimos 60 días
            end_dt = candles[-1].timestamp
            start_dt = end_dt - timedelta(days=60)
            eval_candles = [c for c in candles if c.timestamp >= start_dt]
            if len(eval_candles) < 210:
                eval_candles = candles  # Usar lo disponible si hay menos

            print(f"  Velas cargadas: {len(eval_candles)} (desde {eval_candles[0].timestamp} hasta {eval_candles[-1].timestamp})")

            # ------------------------------------------------------------- #
            # 1. SETUP A: Blind TP (TP Ciego anterior, R:R puro ATR)
            # ------------------------------------------------------------- #
            strat_blind = RSIDivergenceStrategy(
                symbol=symbol,
                rsi_period=14,
                rsi_oversold_threshold=Decimal("38.0"),
                ema_trend_period=200,
                ema_fast_period=20,
                atr_period=14,
                atr_sl_multiplier=Decimal("1.5"),
                risk_reward_ratio=Decimal("2.5"),
                volume_sma_period=20,
                volume_multiplier=Decimal("1.1"),
                lookback_bars=25,
                use_structural_tp=False,
                rsi_overbought_exit=None,
            )
            bt_blind = SignalStrategyBacktester(
                strategy=strat_blind,
                candles=eval_candles,
                symbol=symbol,
                interval=interval,
                initial_cash=initial_cash,
                fee_rate=fee_rate,
                slippage_pct=slippage_pct,
            )
            report_blind = bt_blind.run()

            # ------------------------------------------------------------- #
            # 2. SETUP B: Nuevo TP Estructural al 75% + Salida RSI >= 70
            # ------------------------------------------------------------- #
            strat_struct = RSIDivergenceStrategy(
                symbol=symbol,
                rsi_period=14,
                rsi_oversold_threshold=Decimal("38.0"),
                ema_trend_period=200,
                ema_fast_period=20,
                atr_period=14,
                atr_sl_multiplier=Decimal("1.5"),
                risk_reward_ratio=Decimal("2.5"),
                volume_sma_period=20,
                volume_multiplier=Decimal("1.1"),
                lookback_bars=25,
                use_structural_tp=True,
                structural_tp_ratio=Decimal("0.75"),
                rsi_overbought_exit=Decimal("70.0"),
            )
            bt_struct = SignalStrategyBacktester(
                strategy=strat_struct,
                candles=eval_candles,
                symbol=symbol,
                interval=interval,
                initial_cash=initial_cash,
                fee_rate=fee_rate,
                slippage_pct=slippage_pct,
            )
            report_struct = bt_struct.run()

            # Métricas
            item_comp = {
                "symbol": symbol,
                "interval": interval,
                "candle_count": len(eval_candles),
                "start_time": eval_candles[0].timestamp.isoformat(),
                "end_time": eval_candles[-1].timestamp.isoformat(),
                "blind_tp": {
                    "final_equity": float(report_blind.final_equity),
                    "net_profit_usd": float(report_blind.net_profit_usd),
                    "total_return_pct": float(report_blind.total_return_pct),
                    "total_trades": report_blind.total_trades,
                    "winning_trades": report_blind.winning_trades,
                    "losing_trades": report_blind.losing_trades,
                    "win_rate_pct": float(report_blind.win_rate_pct),
                    "profit_factor": float(report_blind.profit_factor),
                    "max_drawdown_pct": float(report_blind.max_drawdown_pct),
                    "sortino_ratio": float(report_blind.sortino_ratio),
                    "calmar_ratio": float(report_blind.calmar_ratio),
                    "avg_trade_pnl": float(report_blind.average_trade_pnl),
                    "exit_reasons": {
                        r.exit_reason: sum(1 for t in report_blind.trades if t.exit_reason == r.exit_reason)
                        for r in report_blind.trades
                    },
                },
                "structural_tp_75": {
                    "final_equity": float(report_struct.final_equity),
                    "net_profit_usd": float(report_struct.net_profit_usd),
                    "total_return_pct": float(report_struct.total_return_pct),
                    "total_trades": report_struct.total_trades,
                    "winning_trades": report_struct.winning_trades,
                    "losing_trades": report_struct.losing_trades,
                    "win_rate_pct": float(report_struct.win_rate_pct),
                    "profit_factor": float(report_struct.profit_factor),
                    "max_drawdown_pct": float(report_struct.max_drawdown_pct),
                    "sortino_ratio": float(report_struct.sortino_ratio),
                    "calmar_ratio": float(report_struct.calmar_ratio),
                    "avg_trade_pnl": float(report_struct.average_trade_pnl),
                    "exit_reasons": {
                        r.exit_reason: sum(1 for t in report_struct.trades if t.exit_reason == r.exit_reason)
                        for r in report_struct.trades
                    },
                },
            }
            results["comparisons"].append(item_comp)

            # Imprimir resumen de la fila
            b = item_comp["blind_tp"]
            s = item_comp["structural_tp_75"]
            print(f"  [+] BLIND TP:       Trades={b['total_trades']:2d} | WinRate={b['win_rate_pct']:5.1f}% | PF={b['profit_factor']:5.2f} | MaxDD={b['max_drawdown_pct']:5.2f}% | Retorno={b['total_return_pct']:+6.2f}% | PnL=${b['net_profit_usd']:+6.2f}")
            print(f"  [+] STRUCTURAL 75%: Trades={s['total_trades']:2d} | WinRate={s['win_rate_pct']:5.1f}% | PF={s['profit_factor']:5.2f} | MaxDD={s['max_drawdown_pct']:5.2f}% | Retorno={s['total_return_pct']:+6.2f}% | PnL=${s['net_profit_usd']:+6.2f}")

    output_path = Path("data/reports/tp_comparison_60d_100usd.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"\n[+] Resultados guardados en: {output_path.resolve()}\n")
    return results


if __name__ == "__main__":
    run_comparative_suite()
