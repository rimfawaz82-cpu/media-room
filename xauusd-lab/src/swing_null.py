"""Is long-only trend timing better than random long exposure of the same size?
Null: keep each system's trade holding lengths, place them at random non-overlapping start days
(seeded), apply the same costs/swap (W1, no stop). Compare total return. 5,000 draws per system."""
import json
import numpy as np, pandas as pd
from swing import daily_series, START, COST_SIDE, SWAP
from load import ROOT
TAB = ROOT / "reports" / "tables"

def main():
    d = daily_series(); d = d[d.day >= START].reset_index(drop=True)
    o, c = d.open.values, d.close.values
    days = d.day.values
    nights = np.r_[np.diff(days).astype("timedelta64[D]").astype(int), 1]
    pref = c.mean()
    T = pd.read_csv(TAB / "p4_swing_trades.csv", parse_dates=["entry_day", "exit_day"])
    S = pd.read_csv(TAB / "p4_swing_summary.csv")
    rng = np.random.default_rng(20261107)
    out = {}
    for sysname in ["S1_donchian20_LO", "S1_donchian55_LO", "S3_tsmom60_LO", "S3_tsmom20_LO", "S2_ema20_50_LO"]:
        tr = T[T.system == sysname]
        idx = {pd.Timestamp(x): i for i, x in enumerate(days)}
        lens = [max(1, idx.get(r.exit_day, len(d) - 1) - idx.get(r.entry_day, 0)) for r in tr.itertuples()]
        actual = S[(S.system == sysname) & (S.swap == "W1")]["total_return_%"].iloc[0]
        sims = []
        for _ in range(5000):
            occ = np.zeros(len(d), bool); tot = 0.0
            for L in rng.permutation(lens):
                for _try in range(50):
                    s = int(rng.integers(0, len(d) - L - 1))
                    if not occ[s:s + L + 1].any():
                        break
                occ[s:s + L + 1] = True
                e, x = o[s] + COST_SIDE, o[s + L] - COST_SIDE
                fin = (c[s:s + L] * nights[s:s + L]).sum() * SWAP["W1"] / 365
                tot += (x - e - fin) / pref
            sims.append(tot * 100)
        sims = np.array(sims)
        out[sysname] = {"actual_total_%": round(actual, 2), "random_median_%": round(float(np.median(sims)), 2),
                        "random_p95_%": round(float(np.quantile(sims, .95)), 2), "p_value": round(float((sims >= actual).mean()), 4),
                        "trades": len(lens), "exposure_days": int(sum(lens))}
        print(sysname, out[sysname], flush=True)
    json.dump(out, open(ROOT / "reports" / "p4_swing_null.json", "w"), indent=1)

if __name__ == "__main__":
    main()
