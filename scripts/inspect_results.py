"""Script auxiliar para analizar los resultados de optimización."""

import json
from decimal import Decimal
from pathlib import Path

def main():
    for file in sorted(Path("data/reports").glob("optimization_*.json")):
        data = json.loads(file.read_text("utf-8"))
        symbol = data["symbol"]
        interval = data["interval"]
        total_eval = data["total_combinations_evaluated"]
        winning = data.get("winning_results", [])
        all_res = data.get("all_results", [])

        print("=" * 90)
        print(f"{symbol} ({interval}) — Evaluated: {total_eval} | Winning (PF>=1.8, DD<=8%): {len(winning)}")
        print("=" * 90)

        # Multi-trades candidates (>= 2)
        multi_trade = [r for r in all_res if r["total_trades"] >= 2]
        multi_trade.sort(
            key=lambda r: (
                Decimal(str(r["profit_factor"])),
                Decimal(str(r["total_return_pct"])),
                -Decimal(str(r["max_drawdown_pct"])),
            ),
            reverse=True,
        )

        print("Top Robust Candidates (Trades >= 2):")
        for i, r in enumerate(multi_trade[:8], 1):
            p = r["params"]
            pf = float(r["profit_factor"])
            dd = float(r["max_drawdown_pct"])
            ret = float(r["total_return_pct"])
            net = float(r["net_profit_usd"])
            wr = float(r["win_rate_pct"])
            trades = r["total_trades"]
            wins = r["winning_trades"]
            losses = r["losing_trades"]
            sortino = float(r["sortino_ratio"])
            rsi_os = p.get("rsi_oversold_threshold")
            atr_sl = p.get("atr_sl_multiplier")
            rr = p.get("risk_reward_ratio")
            lb = p.get("lookback_bars")
            print(
                f"  {i}. PF={pf:6.2f} | DD={dd:5.2f}% | Ret={ret:+6.2f}% (${net:+5.2f}) | "
                f"Trades={trades:2d} (W:{wins}/L:{losses}) | WR={wr:5.1f}% | Sortino={sortino:5.2f} | "
                f"RSI_OS={rsi_os} ATR_SL={atr_sl} R:R={rr} LB={lb}"
            )

        print("\nBest Overall (First Ranked Candidate):")
        b = data.get("best_result")
        if b:
            p = b["params"]
            print(
                f"  PF={float(b['profit_factor']):.2f} | DD={float(b['max_drawdown_pct']):.2f}% | "
                f"Ret={float(b['total_return_pct']):+.2f}% (${float(b['net_profit_usd']):+.2f}) | "
                f"Trades={b['total_trades']} (W:{b['winning_trades']}/L:{b['losing_trades']}) | "
                f"WR={float(b['win_rate_pct']):.1f}% | "
                f"RSI_OS={p.get('rsi_oversold_threshold')} ATR_SL={p.get('atr_sl_multiplier')} R:R={p.get('risk_reward_ratio')} LB={p.get('lookback_bars')}"
            )
        print()

if __name__ == "__main__":
    main()
