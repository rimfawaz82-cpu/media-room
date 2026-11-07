"""FINAL HOLDOUT — single run of the frozen XAE-Swing v1 rules (rules/xae_swing_v1.json) on 2025-07-01 → 2026-11-06.

Run once. Nothing in the rules is changed after seeing this output.
* Indicators are warmed up on earlier data (past information only).
* 'continuous': the system runs from 2020-12 as in research; only P&L dated in the holdout is counted
  (a position open on 2025-06-30 is carried in, as it would be in real life).
* 'fresh start': system forced flat until 2025-07-01.
Benchmarks: buy-and-hold over the holdout; random long timing with the same trade lengths.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

import swing
from audit import md_table
from load import ROOT
from robust import sig_donchian_gen

H0, H1 = "2025-07-01", "2026-11-06"
OUT = ROOT / "reports"


def run(d, target, cost, swap, start, stop_atr=2.0):
    swing.COST_SIDE = cost
    pnl, tr = swing.simulate_daily(d, target, stop_atr, swap, start)
    swing.COST_SIDE = 0.50
    return pnl, tr


def main():
    swing.END = H1
    d = swing.daily_series()
    tg = sig_donchian_gen(d, 20, 10)
    pref = d[(d.day >= H0)].close.mean()
    res, by_year, trades_out = [], [], None
    scen = [("base: $0.50/side, CFI swap", 0.50, swing.SWAP["W_CFI"]),
            ("stress: $1.00/side, swap 8%", 1.00, 0.08)]
    for mode in ["continuous", "fresh start"]:
        t2 = tg.copy()
        if mode == "fresh start":
            t2[d.day < H0] = 0
        for lbl, cost, sw in scen:
            pnl, tr = run(d, t2, cost, sw, swing.START if mode == "continuous" else H0)
            ph = pnl[pnl.index >= H0]
            trh = tr[pd.to_datetime(tr.exit_day) >= pd.Timestamp(H0)] if len(tr) else tr
            mt = swing.metrics(ph, trh, pref)
            res.append({"mode": mode, "scenario": lbl, **{k: mt[k] for k in ["total_return_%", "annual_return_%", "annual_vol_%", "sharpe", "maxDD_%", "trades", "win_rate", "exposure_%"]}})
            if mode == "continuous" and lbl.startswith("base"):
                trades_out = trh
                eq = (ph / pref).cumsum() * 100
                by_year = ph.groupby(ph.index.to_period("Q")).sum().div(pref).mul(100).round(2)
                eq_base = eq
    # buy & hold over the holdout with the same costs and CFI swap
    bh = pd.Series(1, index=d.index)
    bh[d.day < H0] = 0
    pnl, tr = run(d, bh, 0.50, swing.SWAP["W_CFI"], H0, stop_atr=np.nan)
    ph = pnl[pnl.index >= H0]
    mt = swing.metrics(ph, tr, pref)
    res.append({"mode": "benchmark", "scenario": "buy & hold (CFI swap)", **{k: mt[k] for k in ["total_return_%", "annual_return_%", "annual_vol_%", "sharpe", "maxDD_%", "trades", "win_rate", "exposure_%"]}})
    eq_bh = (ph / pref).cumsum() * 100
    R = pd.DataFrame(res)
    # random-timing null inside the holdout (same lengths, CFI swap, no stop)
    dh = d[d.day >= H0].reset_index(drop=True)
    o, c = dh.open.values, dh.close.values
    nights = np.r_[np.diff(dh.day.values).astype("timedelta64[D]").astype(int), 1]
    idx = {pd.Timestamp(x): i for i, x in enumerate(dh.day)}
    lens = [max(1, idx.get(pd.Timestamp(r.exit_day), len(dh) - 1) - idx.get(pd.Timestamp(r.entry_day), 0)) for r in trades_out.itertuples()]
    rng = np.random.default_rng(20261107)
    actual = R[(R["mode"] == "continuous") & R.scenario.str.startswith("base")]["total_return_%"].iloc[0]
    sims = []
    lr = swing.SWAP["W_CFI"][0]
    for _ in range(5000):
        occ = np.zeros(len(dh), bool); tot = 0.0
        for L in rng.permutation(lens):
            L = min(L, len(dh) - 2)
            for _t in range(50):
                s = int(rng.integers(0, len(dh) - L - 1))
                if not occ[s:s + L + 1].any():
                    break
            occ[s:s + L + 1] = True
            tot += (o[s + L] - o[s] - 1.0 - (c[s:s + L] * nights[s:s + L]).sum() * lr / 365) / pref
        sims.append(tot * 100)
    sims = np.array(sims)
    null = {"trades": len(lens), "actual_total_%": float(actual), "random_median_%": float(np.median(sims)),
            "random_p95_%": float(np.quantile(sims, .95)), "p_value": float((sims >= actual).mean())}
    trades_out.to_csv(OUT / "tables" / "holdout_trades.csv", index=False)
    R.to_csv(OUT / "tables" / "holdout_summary.csv", index=False)
    pd.DataFrame({"xae_swing_%": eq_base, "buy_hold_%": eq_bh}).to_csv(OUT / "tables" / "holdout_equity.csv")
    json.dump({"null": null, "by_quarter_%": {str(k): v for k, v in by_year.items()}, "price_ref": pref,
               "holdout": [H0, H1], "rules": "rules/xae_swing_v1.json"}, open(OUT / "holdout_results.json", "w"), indent=1, default=float)
    pd.set_option("display.width", 250)
    print(R.round(2).to_string())
    print(null)
    print(by_year)
    print(trades_out.to_string())


if __name__ == "__main__":
    main()
