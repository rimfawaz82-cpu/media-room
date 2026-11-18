"""Session return decomposition on H1 (2019-2026): where does gold's return accrue?
Segments by local clocks (DST-aware): ASIA 18:00 NY -> 03:00 NY (=08:00 London);
LONDON 03:00 -> 08:00 NY; NY_AM 08:00 -> 12:00 NY; NY_PM 12:00 -> 17:00 NY.
Returns in bp, per year, with t-stats; plus sign consistency."""
import os, sys, numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from data import load, add_clocks
h = add_clocks(load("H1")); h = h[h.index < "2026-11-18"]
h["nyh"] = h.ny.dt.hour
seg = np.select([(h.nyh >= 18) | (h.nyh < 3), h.nyh < 8, h.nyh < 12], ["1_ASIA", "2_LONDON", "3_NY_AM"], "4_NY_PM")
h["seg"] = seg
h["r"] = np.log(h.close / h.open) * 1e4
g = h.groupby(["day", "seg"]).r.sum().unstack()
g["year"] = g.index.year
pd.set_option("display.width", 200)
mean = g.groupby("year").mean().round(1)
t = g.groupby("year").agg(lambda x: x.mean() / x.std() * np.sqrt(x.count())).round(1)
print("mean bp per day-segment by year\n", mean.join(t, rsuffix="_t").to_string())
print("ALL", g.drop(columns="year").mean().round(2).to_dict(), (g.drop(columns="year").mean() / g.drop(columns="year").std() * np.sqrt(len(g))).round(2).to_dict())
mean.join(t, rsuffix="_t").to_csv(os.path.join(os.path.dirname(__file__), "..", "out", "session_decomp_by_year.csv"))
# hourly in NY clock across years
h["year"] = h.index.year
hm = h.pivot_table(index="nyh", columns="year", values="r", aggfunc="mean").round(1)
print(hm.to_string())
hm.to_csv(os.path.join(os.path.dirname(__file__), "..", "out", "hourly_bp_by_year_nyclock.csv"))
