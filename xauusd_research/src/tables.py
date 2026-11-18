"""Assemble the final comparison table of finalists across dev / val / test."""
import json, os, pandas as pd
OUT = os.path.join(os.path.dirname(__file__), "..", "out")
s = json.load(open(os.path.join(OUT, "final_summary.json")))
K = ["market_days", "trades", "days_traded", "days_wait", "days_win", "days_loss", "pct_win_days_of_all", "pct_win_days_of_traded",
     "win_rate", "avg_win_R", "avg_loss_R", "exp_R_gross", "exp_R", "PF", "total_R", "maxDD_R", "day_mean_R", "day_median_R_traded",
     "worst_day_R", "worst_week_R", "worst_month_R", "max_losing_day_streak", "pct_pos_months", "t_day", "exp_R_ci90", "R_without_top5pct_days"]
rows = []
for n, v in s.items():
    for sp in ["dev", "val", "test"]:
        rows.append({"strategy": n, "split": sp, **{k: v[sp].get(k) for k in K}})
t = pd.DataFrame(rows)
for c in t.columns:
    if t[c].dtype == float: t[c] = t[c].round(3)
t.to_csv(os.path.join(OUT, "finalists_dev_val_test.csv"), index=False)
print(t.T.to_string())
