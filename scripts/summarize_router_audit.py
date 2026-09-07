import json

with open("data/reports/router_empirical_validation_v0.1.0.json", "r", encoding="utf-8") as f:
    data = json.load(f)

for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "PORTFOLIO"]:
    print(f"\n==================== {sym} ====================")
    for strat, d in data["state_separation_delta_e"][sym].items():
        arm_l = d["LONG"]["armed"]
        dis_l = d["LONG"]["disabled"]
        delta_l = d["LONG"]["delta_expectancy_r"]
        delta_hit_l = d["LONG"]["delta_hit_rate_pct"]
        print(f"  [LONG]  {strat:<30}: ARMED N={arm_l['n']:>5} (E={arm_l['mean_return_r']:>+6.3f}R, Hit={arm_l['hit_rate_pct']:>4.1f}%) | DIS N={dis_l['n']:>5} (E={dis_l['mean_return_r']:>+6.3f}R, Hit={dis_l['hit_rate_pct']:>4.1f}%) | Delta={delta_l:>+6.3f}R ({delta_hit_l:>+4.1f}%)")
        arm_s = d["SHORT"]["armed"]
        dis_s = d["SHORT"]["disabled"]
        delta_s = d["SHORT"]["delta_expectancy_r"]
        delta_hit_s = d["SHORT"]["delta_hit_rate_pct"]
        print(f"  [SHORT] {strat:<30}: ARMED N={arm_s['n']:>5} (E={arm_s['mean_return_r']:>+6.3f}R, Hit={arm_s['hit_rate_pct']:>4.1f}%) | DIS N={dis_s['n']:>5} (E={dis_s['mean_return_r']:>+6.3f}R, Hit={dis_s['hit_rate_pct']:>4.1f}%) | Delta={delta_s:>+6.3f}R ({delta_hit_s:>+4.1f}%)")

    print(f"  --- Abstention ---")
    abs_d = data["value_of_abstention"]
    if sym == "PORTFOLIO":
        nt = abs_d["no_trade"]
        tp = abs_d["trade_permitted"]
        print(f"  NO_TRADE: N={nt['n']} ({abs_d['pct_time_no_trade']}%), E[R]={nt['mean_return_r']:+.3f}R, Hit={nt['hit_rate_pct']}%, MAE={nt['mean_mae_pct']}%")
        print(f"  TRADE_PERMITTED: N={tp['n']} ({abs_d['pct_time_trade_permitted']}%), E[R]={tp['mean_return_r']:+.3f}R, Hit={tp['hit_rate_pct']}%, MFE={tp['mean_mfe_pct']}%")
