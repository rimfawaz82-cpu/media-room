"""Phase 3b — walk-forward selection over every Phase 3 / 3b configuration (C1 trades).

Folds: train = trailing 12 months, test = next 3 months, step 3 months, over DEV+VAL (2022-03 → 2025-06).
In each fold, inside each family, pick the configuration with the best TRAIN avg R (n_train >= 40, avg R > 0;
otherwise stay flat). The selected configuration's TEST-quarter trades are collected → out-of-sample record.
Also a 'lab' track that picks the single best configuration across ALL families each fold.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from audit import md_table
from engine import stats
from load import ROOT

TAB = ROOT / "reports" / "tables"
TR = ROOT / "reports" / "trades"


def load_trades():
    logs = pd.concat([pd.read_csv(TAB / "p3_experiment_log.csv"), pd.read_csv(TAB / "p3b_experiment_log.csv")])
    cfgs = logs.drop_duplicates("config")[["hypothesis", "config"]]
    out = []
    for r in cfgs.itertuples():
        f = TR / f"{r.config.replace('|', '__').replace(',', '_').replace('=', '-')}.csv"
        if not f.exists():
            continue
        t = pd.read_csv(f, usecols=["t_entry", "R", "pnl", "minutes", "ambiguous"], parse_dates=["t_entry"])
        t["config"], t["family"] = r.config, r.hypothesis
        out.append(t)
    return pd.concat(out, ignore_index=True)


def main():
    T = load_trades()
    T = T[T.family != "H00_random_baseline"]
    starts = pd.date_range("2023-04-01", "2025-04-01", freq="3MS")
    rows, oos = [], []
    for ts in starts:
        te = ts + pd.DateOffset(months=3)
        tr0 = ts - pd.DateOffset(months=12)
        train = T[(T.t_entry >= tr0) & (T.t_entry < ts)]
        test = T[(T.t_entry >= ts) & (T.t_entry < te)]
        g = train.groupby(["family", "config"]).R.agg(["mean", "size"]).reset_index()
        g = g[(g["size"] >= 40) & (g["mean"] > 0)]
        for fam in T.family.unique():
            c = g[g.family == fam].sort_values("mean", ascending=False)
            if len(c):
                cfg = c.iloc[0].config
                x = test[test.config == cfg]
                oos.append(x.assign(track=fam, fold=str(ts.date())))
                rows.append({"fold": str(ts.date()), "track": fam, "chosen": cfg.split("|")[1], "train_avgR": c.iloc[0]["mean"], "test_n": len(x), "test_avgR": x.R.mean() if len(x) else np.nan})
            else:
                rows.append({"fold": str(ts.date()), "track": fam, "chosen": "FLAT (no positive config)", "train_avgR": np.nan, "test_n": 0, "test_avgR": np.nan})
        if len(g):
            best = g.sort_values("mean", ascending=False).iloc[0]
            x = test[test.config == best.config]
            oos.append(x.assign(track="LAB (best of all)", fold=str(ts.date())))
            rows.append({"fold": str(ts.date()), "track": "LAB (best of all)", "chosen": best.config, "train_avgR": best["mean"], "test_n": len(x), "test_avgR": x.R.mean() if len(x) else np.nan})
    F = pd.DataFrame(rows)
    O = pd.concat(oos, ignore_index=True)
    ndays = len(pd.bdate_range(starts[0], starts[-1] + pd.DateOffset(months=3))) * 0.97
    summ = []
    for tr, x in O.groupby("track"):
        st = stats(x.sort_values("t_entry"), ndays)
        yrs = x.groupby(x.t_entry.dt.year).R.mean().round(3).to_dict()
        summ.append({"track": tr, **{k: st[k] for k in ["n", "trades_per_day", "win_rate", "avg_R", "t_stat", "PF", "total_R", "maxDD_R", "longest_losing_streak"]},
                     "avg_R_by_year": yrs, "folds_traded": int(x.fold.nunique())})
    S = pd.DataFrame(summ).sort_values("avg_R", ascending=False)
    F.to_csv(TAB / "wf_folds.csv", index=False)
    S.to_csv(TAB / "wf_summary.csv", index=False)
    O.to_csv(TAB / "wf_oos_trades.csv", index=False)
    print(S.round(3).to_string())
    return S, F


if __name__ == "__main__":
    main()
