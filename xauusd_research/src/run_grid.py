"""Stage A: run every registered strategy variant on DEV and VALIDATION only (test stays locked).
Writes out/grid_dev_val.csv. Each row = one hypothesis (counted for multiple-testing)."""
import itertools, os, sys, time, json
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from strategies import REGISTRY
from sim import simulate
from metrics import by_split

OUT = os.path.join(os.path.dirname(__file__), "..", "out")
b = pd.read_pickle(os.path.join(OUT, "feat_M15.pkl"))
COST = os.environ.get("COST_BPS"); COST = float(COST) if COST else None
rows = []
t0 = time.time()
for name, (fn, grid) in REGISTRY.items():
    keys = list(grid)
    for vals in itertools.product(*[grid[k] for k in keys]):
        p = dict(zip(keys, vals))
        sig = fn(b, **p)
        sig = sig[sig.split != "test"]  # TEST LOCKED
        mpd = 1 if name in ("ARB", "NYORB", "ADRIFT") else 3
        tr = simulate(sig, cost_bps=COST, max_per_day=mpd)
        res = by_split(tr, b, ("dev", "val"))
        row = {"family": name, "params": json.dumps(p)}
        for sp in res:
            for k in ["trades", "days_traded", "days_wait", "win_rate", "exp_R", "exp_R_gross", "PF", "total_R", "maxDD_R",
                      "pct_win_days_of_all", "pct_win_days_of_traded", "day_mean_R", "t_day", "amb_share", "pct_pos_months"]:
                row[f"{sp}_{k}"] = res[sp].get(k)
        rows.append(row)
    print(name, len(rows), round(time.time() - t0, 1), flush=True)
g = pd.DataFrame(rows)
g.to_csv(os.path.join(OUT, f"grid_dev_val_cost{COST}.csv"), index=False)
pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 90)
cols = ["family", "params", "dev_trades", "dev_days_traded", "dev_win_rate", "dev_exp_R_gross", "dev_exp_R", "dev_PF", "dev_t_day", "val_trades", "val_exp_R", "val_PF", "val_t_day"]
print("variants:", len(g))
print(g.sort_values("dev_exp_R", ascending=False)[cols].head(40).round(3).to_string())
print(g.groupby("family")[["dev_exp_R", "val_exp_R", "dev_exp_R_gross"]].agg(["mean", "max"]).round(3))
