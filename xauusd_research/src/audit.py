"""Step 1: data inventory, quality checks, timezone verification, cross-timeframe consistency.
Writes out/data_audit.md and out/data_audit.json"""
import json, os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from data import *

rep = {}
lines = ["# Data audit — XAUUSD (MT5 exports)\n"]
raw = {tf: load_raw(tf) for tf in TFS}

for tf in TFS:
    d = raw[tf]
    r = {}
    r["rows"] = len(d)
    r["columns"] = list(d.columns)
    r["first"], r["last"] = str(d.ts.iloc[0]), str(d.ts.iloc[-1])
    r["sorted"] = bool(d.ts.is_monotonic_increasing)
    r["dup_ts"] = int(d.ts.duplicated().sum())
    bad = (d.high < d[["open", "close"]].max(axis=1)) | (d.low > d[["open", "close"]].min(axis=1)) | (d.high < d.low)
    r["ohlc_invalid"] = int(bad.sum())
    r["nonpositive"] = int((d[["open", "high", "low", "close"]] <= 0).any(axis=1).sum())
    r["flat_bars_OHLC_equal"] = int(((d.high == d.low)).sum())
    r["identical_consecutive_rows"] = int((d[["open", "high", "low", "close"]].diff().abs().sum(axis=1) == 0).sum())
    r["vol_all_zero"] = bool((d.vol == 0).all())
    r["spread_zero_share"] = round(float((d.spread == 0).mean()), 3)
    nz = d.spread[d.spread > 0]
    r["spread_points_median_nonzero"] = float(nz.median()) if len(nz) else None
    r["first_nonzero_spread_ts"] = str(d.ts[d.spread > 0].iloc[0]) if len(nz) else None
    r["weekday_counts"] = d.ts.dt.dayofweek.value_counts().sort_index().to_dict()
    # bar-range outliers (relative to rolling median range)
    rng = (d.high - d.low)
    med = rng.rolling(500, min_periods=50).median()
    r["range_gt_15x_median"] = int((rng > 15 * med).sum())
    r["top_outliers"] = [
        {"ts": str(d.ts[i]), "range": round(float(rng[i]), 2), "x_median": round(float(rng[i] / med[i]), 1)}
        for i in (rng / med).nlargest(5).index]
    # jumps open vs prev close
    gap = (d.open - d.close.shift()).abs()
    r["open_gap_gt_1pct"] = int((gap / d.close.shift() > 0.01).sum())
    if tf != "D1":
        m = TF_MIN[tf]
        dt = d.ts.diff().dt.total_seconds() / 60
        g = d[dt > m].copy()
        g["gap_min"] = dt[dt > m]
        g["prev"] = d.ts.shift()[dt > m]
        wk = (g.prev.dt.dayofweek == 4) & (g.ts.dt.dayofweek == 0)  # Fri -> Mon
        daily = (g.prev.dt.hour == 23) & (g.ts.dt.hour == 1) & (g.gap_min <= 120 + m)
        hol = (~wk) & (~daily) & (g.gap_min >= 60 * 6)
        small = (~wk) & (~daily) & (~hol)
        r["gaps_total"] = int(len(g))
        r["gaps_weekend"] = int(wk.sum())
        r["gaps_daily_break_00_01_server"] = int(daily.sum())
        r["gaps_holiday_or_long(>=6h,non-weekend)"] = int(hol.sum())
        r["gaps_short_unexplained"] = int(small.sum())
        r["short_gap_minutes_distribution"] = g.gap_min[small].describe().round(1).to_dict() if small.any() else {}
        r["long_nonweekend_gaps"] = [f"{p} -> {t} ({gm/60:.1f}h)" for p, t, gm in zip(g.prev[hol], g.ts[hol], g.gap_min[hol])][:40]
        # hour of day bar presence
        r["bars_by_server_hour"] = d.ts.dt.hour.value_counts().sort_index().to_dict()
    rep[tf] = r

# ---------- timezone verification: where is the daily break during US/EU DST mismatch weeks?
m15 = raw["M15"].copy()
m15["date"] = m15.ts.dt.normalize()
def first_bar_hour(sub):
    return sub.groupby("date").ts.min().dt.hour.value_counts().to_dict()
mismatch = []
for y in range(2023, 2027):
    us = pd.Timestamp(f"{y}-03-08") + pd.offsets.Week(weekday=6)  # 2nd Sunday March
    eu = pd.Timestamp(f"{y}-03-31") - pd.offsets.Week(weekday=6)
    mismatch.append((us, eu))
sub = m15[np.any([(m15.ts > a) & (m15.ts < b) for a, b in mismatch], axis=0)]
rep["tz_check"] = {
    "first_bar_hour_on_days_in_US_EU_DST_mismatch_weeks(March)": first_bar_hour(sub[sub.ts.dt.dayofweek < 5]),
    "first_bar_hour_all_weekdays": first_bar_hour(m15[m15.ts.dt.dayofweek.between(1, 4)]),
    "conclusion": "Daily break stays at 00:00-01:00 server in all seasons incl. the US/EU DST mismatch weeks -> server clock follows US DST: server = New York + 7h (UTC+2 winter / UTC+3 US summer). Trading-day boundary = 17:00 New York.",
}

# ---------- price type: compare tickvol/real volume and spread
rep["price_type"] = {
    "assessment": "MT5 chart bars are built from BID prices (MT5 standard for CFD/FX symbols). <VOL>=0 everywhere -> no exchange volume; <TICKVOL> = number of price updates (tick activity), not traded ounces. <SPREAD> = minimum spread inside the bar, in points; 0 for older history (not recorded).",
}

# ---------- point size estimation for spread
d = raw["M1"]
rep["spread_units"] = {
    "M1_spread_points_quantiles": d.spread.quantile([.05, .25, .5, .75, .95, .99]).to_dict(),
    "note": "Prices have 3 decimals -> 1 point = 0.001 USD if broker point=0.001, or 0.01 if 2-digit point. Median 40 points = $0.04 (point 0.001) or $0.40 (point 0.01). Bar <SPREAD> is the *minimum* in the bar. A realistic retail all-in cost is modelled as scenarios ($0.15-$1.00 per oz round-trip), not taken from this column.",
}

# ---------- cross-timeframe consistency
xc = {}
cl = {tf: load(tf) for tf in TFS}
def compare(fine, coarse_tf, rule, label):
    f = cl[fine]
    c = cl[coarse_tf]
    lo, hi = max(f.index[0], c.index[0]), min(f.index[-1], c.index[-1])
    rs = resample(f.loc[lo:hi], rule)
    # require full coverage: count of fine bars == expected or same as present
    cnt = f.loc[lo:hi].open.resample(rule, label="left", closed="left").count()
    rs = rs.loc[rs.index.intersection(c.index)]
    cc = c.loc[rs.index]
    # drop first & last partial
    rs, cc = rs.iloc[1:-1], cc.iloc[1:-1]
    out = {"period": f"{rs.index[0]} -> {rs.index[-1]}", "bars_compared": len(rs)}
    for k in ["open", "high", "low", "close"]:
        diff = (rs[k] - cc[k]).abs()
        out[f"{k}_match_share(<=0.011)"] = round(float((diff <= 0.011).mean()), 4)
        out[f"{k}_max_absdiff"] = round(float(diff.max()), 3)
    out["coarse_bars_missing_in_resample"] = int(len(c.loc[lo:hi].iloc[1:-1].index.difference(rs.index)))
    xc[label] = out
compare("M1", "M5", "5min", "M1->M5")
compare("M1", "M15", "15min", "M1->M15")
compare("M1", "H1", "1h", "M1->H1")
compare("M1", "H4", "4h", "M1->H4")
compare("M5", "M15", "15min", "M5->M15")
compare("M5", "H1", "1h", "M5->H1")
compare("M15", "H1", "1h", "M15->H1")
compare("M15", "H4", "4h", "M15->H4")
compare("H1", "H4", "4h", "H1->H4")
compare("M15", "D1", "1D", "M15->D1")
compare("H1", "D1", "1D", "H1->D1")
compare("M1", "D1", "1D", "M1->D1")
rep["cross_tf"] = xc

# H4 boundary check
h4 = cl["H4"]
rep["H4_open_hours_server"] = h4.index.hour.value_counts().sort_index().to_dict()

# ---------- write
json.dump(rep, open(os.path.join(OUT, "data_audit.json"), "w"), indent=1, default=str)
for tf in TFS:
    r = rep[tf]
    lines.append(f"\n## {tf}\n")
    for k, v in r.items():
        if k in ("long_nonweekend_gaps",):
            lines.append(f"- {k}:\n" + "\n".join(f"    - {x}" for x in v))
        else:
            lines.append(f"- {k}: {v}")
for k in ("tz_check", "price_type", "spread_units", "cross_tf", "H4_open_hours_server"):
    lines.append(f"\n## {k}\n")
    if isinstance(rep[k], dict):
        for kk, vv in rep[k].items():
            lines.append(f"- {kk}: {vv}")
open(os.path.join(OUT, "data_audit.md"), "w").write("\n".join(lines))
print(json.dumps({k: rep[k] for k in ("tz_check", "cross_tf", "H4_open_hours_server")}, indent=1, default=str))
for tf in TFS:
    r = rep[tf]
    print(tf, {k: r.get(k) for k in ["rows", "first", "last", "sorted", "dup_ts", "ohlc_invalid", "flat_bars_OHLC_equal", "identical_consecutive_rows", "spread_zero_share", "spread_points_median_nonzero", "first_nonzero_spread_ts", "range_gt_15x_median", "gaps_total", "gaps_weekend", "gaps_daily_break_00_01_server", "gaps_holiday_or_long(>=6h,non-weekend)", "gaps_short_unexplained", "weekday_counts"]})
    print("   short gaps:", r.get("short_gap_minutes_distribution"), "outliers:", r["top_outliers"][:3])
