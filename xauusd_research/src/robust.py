"""Stage B (still no test data): walk-forward selection + robustness of the pre-registered finalists on dev+val."""
import itertools, os, sys, json
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from strategies import REGISTRY, ny_orb, asia_breakout, asia_drift
from sim import simulate, recost
from metrics import by_split, summarize, market_days, SPLITS

OUT = os.path.join(os.path.dirname(__file__), "..", "out")
b = pd.read_pickle(os.path.join(OUT, "feat_M15.pkl"))
pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 80)
dv = b[b.split != "test"]
FIN = {"F1_NYORB": (ny_orb, dict(or_start=8.5, R=3.0, min_w=0.15), 1),
       "F2_ARB": (asia_breakout, dict(sl_mode="opp", R=1.5, width="all", trend="none"), 1),
       "F3_ADRIFT": (asia_drift, dict(trend="none", exit_ldn=7.0, start_ny=20.0), 1)}
report = {}

# ---- 1. walk-forward: each year, pick the best variant (net exp) of each family using ALL prior data, trade next year
def yearly(tr):
    return tr.groupby(tr.day.dt.year).R.agg(["count", "mean", "sum"])
wf_rows = []
cache = {}
for fam, (fn, grid) in REGISTRY.items():
    keys = list(grid)
    for vals in itertools.product(*[grid[k] for k in keys]):
        p = dict(zip(keys, vals))
        sig = fn(b, **p); sig = sig[sig.split != "test"]
        tr = simulate(sig, max_per_day=1 if fam in ("ARB", "NYORB", "NYORB2", "ADRIFT") else 3)
        cache[(fam, json.dumps(p))] = tr
for Y in [2024, 2025]:
    best = {}
    for (fam, p), tr in cache.items():
        past = tr[tr.day < f"{Y}-01-01"]
        if len(past) < 100: continue
        e = past.R.mean()
        if fam not in best or e > best[fam][0]:
            best[fam] = (e, p)
    for fam, (e, p) in best.items():
        nxt = cache[(fam, p)]; nxt = nxt[nxt.day.dt.year == Y]
        wf_rows.append({"oos_year": Y, "family": fam, "chosen_params": p, "in_sample_exp_R": e, "oos_trades": len(nxt), "oos_exp_R": nxt.R.mean(), "oos_total_R": nxt.R.sum()})
    # global best across all families
    g = max(((tr[tr.day < f"{Y}-01-01"].R.mean(), k) for k, tr in cache.items() if (tr.day < f"{Y}-01-01").sum() >= 100))
    nxt = cache[g[1]]; nxt = nxt[nxt.day.dt.year == Y]
    wf_rows.append({"oos_year": Y, "family": "GLOBAL_BEST:" + g[1][0], "chosen_params": g[1][1], "in_sample_exp_R": g[0], "oos_trades": len(nxt), "oos_exp_R": nxt.R.mean(), "oos_total_R": nxt.R.sum()})
wf = pd.DataFrame(wf_rows)
wf.to_csv(os.path.join(OUT, "walk_forward_dev_val.csv"), index=False)
print("WALK-FORWARD (dev/val only)\n", wf.round(3).to_string())

# ---- 2. robustness of finalists on dev+val
rob = []
for name, (fn, p, mpd) in FIN.items():
    sig = fn(b, **p); sig = sig[sig.split != "test"]
    tr = simulate(sig, max_per_day=mpd)
    tr.to_pickle(os.path.join(OUT, f"tr_devval_{name}.pkl"))
    base = tr.R.mean()
    rec = {"name": name, "trades": len(tr), "exp_R_realistic": base, "exp_R_gross": tr.R_gross.mean(),
           "avg_cost_R": (tr.cost / tr.risk).mean(), "avg_cost_usd": tr.cost.mean(), "amb_share": tr.amb.mean()}
    for c in [0, 0.5, 1.0, 1.5, 2.0, 3.0]:
        rec[f"exp_R_cost{c}bp"] = recost(tr, c).R.mean()
    # break-even fixed cost (bp) by bisection
    lo, hi = 0.0, 10.0
    for _ in range(30):
        mid = (lo + hi) / 2
        if recost(tr, mid).R.mean() > 0: lo = mid
        else: hi = mid
    rec["breakeven_cost_bp_incl_0.5bp_stop_slip"] = lo
    rec["breakeven_cost_usd_at_4000"] = lo * 4000 / 1e4
    # delayed entry: decision 15 min later
    s2 = sig.copy(); s2["dec"] = s2.dec + pd.Timedelta(minutes=15)
    rec["exp_R_delay15m"] = simulate(s2, max_per_day=mpd).R.mean()
    s3 = sig.copy(); s3["dec"] = s3.dec + pd.Timedelta(minutes=5)
    rec["exp_R_delay5m"] = simulate(s3, max_per_day=mpd).R.mean()
    # optimistic ambiguity (target first) for sensitivity
    rec["R_lost_to_conservative_ambiguity"] = float(tr.amb.sum())
    yr = yearly(tr); rec["by_year"] = {int(k): (int(v["count"]), round(v["mean"], 3)) for k, v in yr.iterrows()}
    rec["by_side"] = {int(k): (int(len(v)), round(v.R.mean(), 3)) for k, v in tr.groupby("side")}
    rec["by_dow"] = {int(k): (int(len(v)), round(v.R.mean(), 3)) for k, v in tr.groupby(tr.day.dt.dayofweek)}
    rec["by_D1_trend_aligned"] = {str(k): (int(len(v)), round(v.R.mean(), 3)) for k, v in tr.groupby(np.sign(tr.side) == np.sign(b.D1_trend.reindex(tr.dec - pd.Timedelta(minutes=15)).values))}
    days = tr.groupby("day").R.sum().sort_values(ascending=False)
    rec["total_R"] = tr.R.sum(); rec["total_R_minus_best10_days"] = tr.R.sum() - days.iloc[:10].sum()
    rob.append(rec)
    print(name, json.dumps({k: (round(v, 3) if isinstance(v, float) else v) for k, v in rec.items()}, default=str))

# ---- 3. target study for F1 (does 1:2 help?) on dev+val
tgt = []
for R in [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 0]:
    for be in [0.0, 1.0]:
        s = ny_orb(b, or_start=8.5, R=R, min_w=0.15); s = s[s.split != "test"]; s["be_r"] = be
        t = simulate(s, max_per_day=1)
        tgt.append({"target_R": R if R else "time-exit 15:00 NY", "breakeven_after_1R": bool(be), "trades": len(t), "win_rate": t.R.gt(0).mean(), "exp_R": t.R.mean(), "exp_R_gross": t.R_gross.mean(), "PF": t.R[t.R > 0].sum() / -t.R[t.R < 0].sum()})
tgt = pd.DataFrame(tgt); tgt.to_csv(os.path.join(OUT, "F1_target_study_devval.csv"), index=False)
print(tgt.round(3).to_string())
json.dump(rob, open(os.path.join(OUT, "robustness_devval.json"), "w"), indent=1, default=str)
