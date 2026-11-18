import numpy as np, pandas as pd

SPLITS = {"dev": ("2022-08-16", "2025-01-01"), "val": ("2025-01-01", "2026-01-01"), "test": ("2026-01-01", "2026-11-18")}


def market_days(b, split=None):
    """trading days = server dates having London-session bars"""
    d = b[(b.ldn_h >= 8) & (b.ldn_h < 16)].day.unique()
    d = pd.DatetimeIndex(d)
    if split:
        lo, hi = SPLITS[split]
        d = d[(d >= lo) & (d < hi)]
    return d


def summarize(tr, days, risk_pct=1.0):
    """tr: trades in this split; days: all market days in split"""
    out = {"market_days": len(days)}
    n = len(tr)
    out["trades"] = n
    if n == 0:
        return out
    R = tr.R.values
    out["win_rate"] = float((R > 0).mean())
    out["avg_win_R"] = float(R[R > 0].mean()) if (R > 0).any() else 0
    out["avg_loss_R"] = float(R[R <= 0].mean()) if (R <= 0).any() else 0
    out["exp_R"] = float(R.mean())
    out["exp_R_gross"] = float(tr.R_gross.mean())
    out["PF"] = float(R[R > 0].sum() / -R[R < 0].sum()) if (R < 0).any() else np.inf
    out["total_R"] = float(R.sum())
    eq = np.cumsum(R)
    out["maxDD_R"] = float((np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max())
    out["amb_share"] = float(tr.amb.mean())
    dr = tr.groupby("day").R.sum().reindex(days).fillna(np.nan)
    traded = dr.dropna()
    out["days_traded"] = int(len(traded))
    out["days_win"] = int((traded > 0).sum())
    out["days_loss"] = int((traded < 0).sum())
    out["days_flat"] = int((traded == 0).sum())
    out["days_wait"] = int(dr.isna().sum())
    out["pct_win_days_of_all"] = out["days_win"] / max(1, len(days))
    out["pct_win_days_of_traded"] = out["days_win"] / max(1, len(traded))
    out["trades_per_day_traded"] = n / max(1, len(traded))
    d0 = dr.fillna(0)
    out["day_mean_R"] = float(d0.mean())
    out["day_median_R_traded"] = float(traded.median())
    out["avg_win_day_R"] = float(traded[traded > 0].mean()) if (traded > 0).any() else 0
    out["avg_loss_day_R"] = float(traded[traded < 0].mean()) if (traded < 0).any() else 0
    out["worst_day_R"] = float(traded.min())
    out["best_day_R"] = float(traded.max())
    wk = d0.groupby(d0.index.to_period("W")).sum(); mo = d0.groupby(d0.index.to_period("M")).sum()
    out["worst_week_R"] = float(wk.min()); out["worst_month_R"] = float(mo.min())
    out["pct_pos_weeks"] = float((wk > 0).mean()); out["pct_pos_months"] = float((mo > 0).mean())
    # longest losing-day streak (traded days only)
    s = 0; mx = 0
    for v in traded.values:
        s = s + 1 if v < 0 else 0; mx = max(mx, s)
    out["max_losing_day_streak"] = mx
    # day-clustered t-stat and bootstrap CI of expectancy (resample days, keeps intra-day correlation)
    out["t_day"] = float(traded.mean() / traded.std(ddof=1) * np.sqrt(len(traded))) if len(traded) > 2 else np.nan
    rng = np.random.default_rng(0)
    g = [x.values for _, x in tr.groupby("day").R]
    if len(g) > 5:
        bs = []
        for _ in range(500):
            idx = rng.integers(0, len(g), len(g))
            v = np.concatenate([g[i] for i in idx]); bs.append(v.mean())
        out["exp_R_ci90"] = (float(np.percentile(bs, 5)), float(np.percentile(bs, 95)))
    # concentration: share of total R from top 5% days
    pos = traded.sort_values(ascending=False)
    k = max(1, int(0.05 * len(pos)))
    out["R_without_top5pct_days"] = float(traded.sum() - pos.iloc[:k].sum())
    out["ret_pct_at_1pct_risk"] = float(R.sum() * risk_pct)
    return out


def by_split(tr, b, keys=("dev", "val", "test")):
    res = {}
    for sp in keys:
        lo, hi = SPLITS[sp]
        t = tr[(tr.day >= lo) & (tr.day < hi)] if len(tr) else tr
        res[sp] = summarize(t, market_days(b, sp))
    return res
