"""Phase 3 runner: every pre-registered configuration × cost scenario on DEV and VAL.

Selection rule (fixed before running):
  DEV screen  : n >= 100, avg_R(C1) > 0, t_stat(C1) >= 2.0, PF(C1) >= 1.10
  VAL confirm : avg_R(C1) > 0 for the SAME configuration (no re-optimisation on VAL)
Everything is logged to reports/tables/p3_experiment_log.csv (one row per config × cost × split).
"""
from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

from engine import Market, simulate, stats
from features import load_research
import sys
from hypotheses import REGISTRY, REGISTRY_B, context, grid
from load import ROOT

TAB = ROOT / "reports" / "tables"
TR = ROOT / "reports" / "trades"
TR.mkdir(parents=True, exist_ok=True)


def run_orders(mkt, orders, cost):
    trades = []
    busy_until = -1
    for o in orders:
        if isinstance(o, list):            # OCO group: earliest fill wins; same-bar double trigger -> skipped
            res = [simulate(mkt, x, cost) for x in o]
            res = [r for r in res if r and r.get("status") == "filled"]
            if not res:
                continue
            res.sort(key=lambda r: r["i_entry"])
            if len(res) > 1 and res[0]["i_entry"] == res[1]["i_entry"]:
                continue
            r = res[0]
        else:
            r = simulate(mkt, o, cost)
            if not r or r.get("status") != "filled":
                continue
        if r["i_entry"] <= busy_until:     # one position at a time per hypothesis
            continue
        busy_until = r["i_exit"]
        trades.append(r)
    return pd.DataFrame(trades)


def main():
    t0 = time.time()
    m = load_research(("dev", "val"))
    mkt = Market(m)
    ctx = context(mkt)
    split_of_day = m.groupby(m.ts.dt.normalize()).split.first()
    ndays = split_of_day.value_counts().to_dict()
    rows = []
    n_configs = 0
    phase_b = "--b" in sys.argv
    reg = REGISTRY_B if phase_b else REGISTRY
    for hname, (fn, params) in reg.items():
        for p in grid(params):
            n_configs += 1
            cid = hname + "|" + ",".join(f"{k}={v}" for k, v in p.items())
            orders = fn(mkt, ctx, **p)
            for cost in ["C0", "C1", "C2"]:
                tr = run_orders(mkt, orders, cost)
                if len(tr):
                    tr["split"] = pd.to_datetime(tr.t_entry).dt.normalize().map(split_of_day).values
                    tr["config"] = cid
                    if cost == "C1":
                        tr.to_csv(TR / f"{cid.replace('|', '__').replace(',', '_').replace('=', '-')}.csv", index=False)
                for sp in ["dev", "val"]:
                    x = tr[tr.split == sp] if len(tr) else tr
                    st = stats(x, ndays[sp])
                    rows.append({"hypothesis": hname, "config": cid, **p, "cost": cost, "split": sp, **st})
            print(f"{cid}  ({time.time() - t0:.0f}s)", flush=True)
    log = pd.DataFrame(rows)
    sfx = "b" if phase_b else ""
    log.to_csv(TAB / f"p3{sfx}_experiment_log.csv", index=False)
    json.dump({"n_configs": n_configs, "seconds": round(time.time() - t0)}, open(ROOT / "reports" / f"p3{sfx}_meta.json", "w"))
    print("configs:", n_configs)


if __name__ == "__main__":
    main()
