"""Stage C: the ONLY run on the locked 2026 test split, for the pre-registered finalists.
Exports trade logs + daily results (Beirut clock) and summary tables."""
import itertools, os, sys, json
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from strategies import REGISTRY, ny_orb, asia_breakout, asia_drift
from sim import simulate, recost
from metrics import by_split, summarize, market_days, SPLITS

OUT = os.path.join(os.path.dirname(__file__), "..", "out")
b = pd.read_pickle(os.path.join(OUT, "feat_M15.pkl"))
pre = json.load(open(os.path.join(OUT, "preregistration.json")))
FIN = {"F1_NYORB": (ny_orb, pre["F1_primary"]["params"]),
       "F2_ARB": (asia_breakout, pre["F2_baseline_london"]["params"]),
       "F3_ADRIFT": (asia_drift, pre["F3_asia_drift"]["params"])}
pd.set_option("display.width", 250)


def to_beirut(ts):
    from data import server_to_utc
    return server_to_utc(pd.DatetimeIndex(ts)).tz_convert("Asia/Beirut").tz_localize(None)


REASON = {1: "target", 2: "stop", 3: "time exit", 5: "breakeven stop"}
summary = {}
for name, (fn, p) in FIN.items():
    sig = fn(b, **p)
    tr = simulate(sig, max_per_day=1)
    summary[name] = by_split(tr, b)
    # cost scenarios on test
    tt = tr[tr.day >= "2026-01-01"]
    summary[name]["test_cost_scenarios_expR"] = {f"{c}bp": round(recost(tt, c).R.mean(), 4) for c in [0, 0.5, 1, 1.5, 2, 3]}
    summary[name]["test_by_side"] = {int(k): (len(v), round(v.R.mean(), 3)) for k, v in tt.groupby("side")}
    summary[name]["test_by_month_R"] = {str(k): round(v, 2) for k, v in tt.groupby(tt.day.dt.to_period("M")).R.sum().items()}
    # ---- logs
    log = pd.DataFrame({
        "trading_day": tr.day.dt.date, "split": np.where(tr.day < "2025-01-01", "dev", np.where(tr.day < "2026-01-01", "val", "test")),
        "signal_time_beirut": to_beirut(tr.dec), "entry_time_beirut": to_beirut(tr.entry_ts), "exit_time_beirut": to_beirut(tr.exit_ts),
        "side": np.where(tr.side == 1, "BUY", "SELL"), "order_type": tr.otype.map({0: "market", 1: "stop", 2: "limit"}),
        "order_price": tr.px.round(3), "entry": tr.entry.round(3), "stop": tr.sl.round(3), "target": tr.tp.round(3), "exit": tr.exit.round(3),
        "exit_reason": tr.reason.map(REASON), "exec_tf_min": tr.exec_tf, "ambiguous_bar": tr.amb,
        "risk_usd": tr.risk.round(3), "spread_paid_usd": np.where(tr.side == 1, tr.spread_entry, tr.spread_exit).round(3),
        "total_cost_usd": tr.cost.round(3), "gross_R": tr.R_gross.round(3), "net_R": tr.R.round(3),
    })
    log.to_csv(os.path.join(OUT, f"trades_{name}.csv"), index=False)
    # daily file incl. wait days
    rows = []
    for sp in ["dev", "val", "test"]:
        for d in market_days(b, sp):
            t = tr[tr.day == d]
            rows.append({"trading_day": d.date(), "split": sp, "decision": "TRADE" if len(t) else "WAIT", "trades": len(t),
                         "net_R": round(t.R.sum(), 3) if len(t) else 0.0,
                         "result": ("WIN" if t.R.sum() > 0 else "LOSS" if t.R.sum() < 0 else "FLAT") if len(t) else "NO SIGNAL"})
    pd.DataFrame(rows).to_csv(os.path.join(OUT, f"daily_{name}.csv"), index=False)
    tr.to_pickle(os.path.join(OUT, f"tr_all_{name}.pkl"))

# F1 plateau neighbours on test
nb = []
for R, mw in itertools.product([3.0, 4.0, 0], [0.15, 0.2]):
    s = ny_orb(b, or_start=8.5, R=R, min_w=mw); t = simulate(s, max_per_day=1)
    for sp in ["dev", "val", "test"]:
        lo, hi = SPLITS[sp]; x = t[(t.day >= lo) & (t.day < hi)]
        nb.append({"R": R or "time", "min_w": mw, "split": sp, "trades": len(x), "exp_R": round(x.R.mean(), 3), "total_R": round(x.R.sum(), 1)})
nb = pd.DataFrame(nb).pivot_table(index=["R", "min_w"], columns="split", values=["trades", "exp_R", "total_R"])
nb.to_csv(os.path.join(OUT, "F1_plateau_all_splits.csv"))
print(nb.to_string())

# walk-forward year 2026: best variant per family chosen on <=2025, all 161 variants
wf = []
best_global = None
for fam, (fn, grid) in REGISTRY.items():
    keys = list(grid); best = None
    for vals in itertools.product(*[grid[k] for k in keys]):
        p = dict(zip(keys, vals)); t = simulate(fn(b, **p), max_per_day=1 if fam in ("ARB", "NYORB", "NYORB2", "ADRIFT") else 3)
        past, fut = t[t.day < "2026-01-01"], t[t.day >= "2026-01-01"]
        if len(past) < 100: continue
        if best is None or past.R.mean() > best[0]:
            best = (past.R.mean(), p, len(fut), fut.R.mean(), fut.R.sum())
    wf.append({"family": fam, "chosen_on_2022_2025": json.dumps(best[1]), "is_exp_R": best[0], "test_trades": best[2], "test_exp_R": best[3], "test_total_R": best[4]})
wf = pd.DataFrame(wf); wf.to_csv(os.path.join(OUT, "walk_forward_2026.csv"), index=False)
print(wf.round(3).to_string())

json.dump(summary, open(os.path.join(OUT, "final_summary.json"), "w"), indent=1, default=str)
for n, s in summary.items():
    print("\n==", n)
    for sp in ["dev", "val", "test"]:
        print(sp, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in s[sp].items()})
    print("test cost scen", s["test_cost_scenarios_expR"], "side", s["test_by_side"])
    print("months", s["test_by_month_R"])
