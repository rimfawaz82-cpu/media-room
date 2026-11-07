"""Phase 2 — XAUUSD Behavior Atlas (statistical market profiling).

Discovery on DEV (2022-03-16 → 2024-06-30); replication check on VAL (2024-07-02 → 2025-06-30).
The holdout is never loaded.

Usage: python src/atlas.py
Outputs: reports/02_behavior_atlas.md, reports/atlas_results.json, reports/tables/atlas_*.csv, reports/figures/*.png
"""
from __future__ import annotations

import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from audit import md_table
from features import atr, load_research, resample
from load import ROOT

OUT = ROOT / "reports"
TAB = OUT / "tables"
FIG = OUT / "figures"
FIG.mkdir(parents=True, exist_ok=True)
R: dict = {}
C1_ROUNDTRIP = 0.30   # $: spread 0.10 + 2 x 0.10 slippage on market orders (Phase 1b, C1)
SPLITS = ("dev", "val")

INK, MUTED, SURFACE, BLUE = "#1f1f1e", "#6b6a66", "#fcfcfb", "#2a78d6"
SEQ = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]


def wilson(k, n, z=1.96):
    if n == 0:
        return (np.nan, np.nan)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def zprop(k, n, p0=0.5):
    return (k / n - p0) / np.sqrt(p0 * (1 - p0) / n) if n else np.nan


def style(ax):
    ax.set_facecolor(SURFACE)
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    for s in ["left", "bottom"]:
        ax.spines[s].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.yaxis.grid(True, color="#e6e5e1", linewidth=0.6)
    ax.set_axisbelow(True)


# =============================================================================== A. time
def hourly(m: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for sp in SPLITS:
        x = m[m.split == sp]
        h = resample(x, "1h")
        h = h[h.n >= 50].copy()
        h["day"] = h.ts.dt.normalize()
        h["hour"] = h.ts.dt.hour
        h = h.merge(daily[["day", "atr_d_prev"]], on="day", how="left")
        h["rng"] = h.high - h.low
        h["rng_n"] = h.rng / h.atr_d_prev
        h["ret"] = h.close - h.open
        same_day = h.day.eq(h.day.shift()) & (h.ts - h.ts.shift() == pd.Timedelta(hours=1))
        ph, pl, pr = h.high.shift(), h.low.shift(), h.ret.shift()
        h["bo_up"] = (h.high > ph) & same_day
        h["bo_dn"] = (h.low < pl) & same_day
        one_side = h.bo_up ^ h.bo_dn
        h["false_bo"] = one_side & (((h.bo_up) & (h.close < ph)) | ((h.bo_dn) & (h.close > pl)))
        h["cont"] = np.sign(h.ret) == np.sign(pr)
        h["valid_prev"] = same_day & (pr != 0) & (h.ret != 0)
        # within-hour M1 metrics
        x = x.assign(hr=x.ts.dt.floor("h"))
        x["dc"] = x.groupby("hr").close.diff()
        x["lr"] = np.log(x.close).diff().where(x.hr.eq(x.hr.shift()))
        g = x.groupby("hr")
        er = (g.close.last() - g.open.first()).abs() / g.dc.apply(lambda s: s.abs().sum()).replace(0, np.nan)
        rv = np.sqrt(g.lr.apply(lambda s: (s ** 2).sum())) * 1e4
        # 5-min variance ratio (pooled by hour of day)
        x["m5"] = x.ts.dt.floor("5min")
        r5 = x.groupby("m5").agg(o=("open", "first"), c=("close", "last"), n=("open", "size"))
        r5 = r5[r5.n == 5]
        r5["lr5"] = np.log(r5.c / r5.o)
        r5["hour"] = r5.index.hour
        x["hour"] = x.ts.dt.hour
        vr = (r5.groupby("hour").lr5.var() / (5 * x.groupby("hour").lr.var()))
        h = h.merge(pd.DataFrame({"er": er, "rv_bps": rv}).rename_axis("ts").reset_index(), on="ts", how="left")
        for hr, s in h.groupby("hour"):
            v = s[s.valid_prev]
            bo = s.bo_up | s.bo_dn
            k_cont, n_cont = int(v.cont.sum()), len(v)
            rows.append({"split": sp, "srv_hour": hr, "ny_hour": (hr - 7) % 24, "n": len(s),
                         "range_med_$": s.rng.median(), "range_mean_$": s.rng.mean(), "range_vs_ATRd_med": s.rng_n.median(),
                         "rv_bps_med": s.rv_bps.median(), "eff_ratio_med": s.er.median(), "VR5": vr.get(hr, np.nan),
                         "breakout_rate": bo.mean() if n_cont else np.nan, "false_bo_rate": s.false_bo.sum() / (s.bo_up ^ s.bo_dn).sum() if n_cont else np.nan,
                         "sweep_rate": s.false_bo.mean() if n_cont else np.nan, "P_cont_prev_hour": k_cont / n_cont if n_cont else np.nan, "z_cont": zprop(k_cont, n_cont),
                         "cost_C1_vs_med_range": C1_ROUNDTRIP / s.rng.median()})
    return pd.DataFrame(rows)


def daily_bars(m: pd.DataFrame) -> pd.DataFrame:
    d = m.groupby("day").agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
                             split=("split", "first"), n=("open", "size")).reset_index()
    d["atr_d"] = atr(d.rename(columns={}), 14)
    d["atr_d_prev"] = d.atr_d.shift()          # known at the start of the day
    d["rng"] = d.high - d.low
    d["ret"] = d.close - d.open
    d["dow"] = d.day.dt.dayofweek
    return d


def day_of_week(d: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for sp in SPLITS:
        x = d[(d.split == sp) & (d.n > 1000)].dropna(subset=["atr_d_prev"])
        for dw, s in x.groupby("dow"):
            k = int((s.ret > 0).sum())
            rows.append({"split": sp, "dow": ["Mon", "Tue", "Wed", "Thu", "Fri"][dw], "n": len(s), "range_med_$": s.rng.median(),
                         "range_vs_ATRd_med": (s.rng / s.atr_d_prev).median(), "ret_mean_ATR": (s.ret / s.atr_d_prev).mean(),
                         "P_up": k / len(s), "z_up": zprop(k, len(s))})
    return pd.DataFrame(rows)


def sessions(m: pd.DataFrame, d: pd.DataFrame):
    rows = []
    hl_rows = []
    for sp in SPLITS:
        x = m[m.split == sp]
        dd = d[d.split == sp].set_index("day")
        g = x.groupby(["day", "session"]).agg(h=("high", "max"), l=("low", "min"), o=("open", "first"), c=("close", "last"), n=("open", "size")).reset_index()
        g = g.join(dd[["atr_d_prev", "high", "low"]], on="day")
        g["rng"] = g.h - g.l
        g["sets_day_high"] = g.h >= g.high
        g["sets_day_low"] = g.l <= g.low
        for ss, s in g.groupby("session"):
            rows.append({"split": sp, "session": ss, "days": len(s), "minutes_med": s.n.median(), "range_med_$": s.rng.median(),
                         "range_vs_ATRd_med": (s.rng / s.atr_d_prev).median(), "range_per_hour_vs_ATRd": ((s.rng / s.atr_d_prev) / (s.n / 60)).median(),
                         "P_sets_day_high": s.sets_day_high.mean(), "P_sets_day_low": s.sets_day_low.mean(),
                         "cost_C1_vs_med_range": C1_ROUNDTRIP / s.rng.median()})
        # time-of-day (NY hour) at which the daily high and low are first printed
        full = x[x.day.isin(dd.index[dd.n > 1000])]
        ih = full.loc[full.groupby("day").high.idxmax(), "ny_hour"].value_counts(normalize=True)
        il = full.loc[full.groupby("day").low.idxmin(), "ny_hour"].value_counts(normalize=True)
        hl = pd.DataFrame({"P_day_high_in_hour": ih, "P_day_low_in_hour": il}).fillna(0)
        hl["split"] = sp
        hl_rows.append(hl.rename_axis("ny_hour").reset_index())
    return pd.DataFrame(rows), pd.concat(hl_rows)


def opening_ranges(m: pd.DataFrame, d: pd.DataFrame) -> pd.DataFrame:
    """Opening-range behaviour at session opens. OR = first 30 minutes after the open (all known at OR end)."""
    specs = [("Asia 19:00 NY", "ny_min", 19 * 60, 2 * 60 + 24 * 60), ("London 08:00 LDN", "ldn_min", 8 * 60, 12 * 60),
             ("NY data 08:30 NY", "ny_min", 8 * 60 + 30, 12 * 60), ("NY cash 09:30 NY", "ny_min", 9 * 60 + 30, 12 * 60)]
    rows = []
    for sp in SPLITS:
        x = m[m.split == sp]
        for name, col, start, end in specs:
            t = x[col].where(x[col] >= start % 1440, x[col] + 1440) if end > 1440 else x[col]
            orm = x[(t >= start) & (t < start + 30)]
            rest = x[(t >= start + 30) & (t < end)]
            a = orm.groupby("day").agg(oh=("high", "max"), ol=("low", "min"), oo=("open", "first"), oc=("close", "last"), on=("open", "size"))
            b = rest.groupby("day").agg(rh=("high", "max"), rl=("low", "min"), rc=("close", "last"), rn=("open", "size"))
            j = a.join(b, how="inner")
            j = j[(j.on >= 25) & (j.rn >= 60)]
            # which side broke first
            first = []
            for day, s in rest[rest.day.isin(j.index)].groupby("day"):
                oh, ol = j.at[day, "oh"], j.at[day, "ol"]
                iu = np.argmax(s.high.values > oh) if (s.high.values > oh).any() else 10 ** 9
                idn = np.argmax(s.low.values < ol) if (s.low.values < ol).any() else 10 ** 9
                first.append((day, "up" if iu < idn else ("down" if idn < iu else ("none" if iu == 10 ** 9 else "same"))))
            fb = pd.Series(dict(first))
            j["first_break"] = fb
            up, dn = j.first_break == "up", j.first_break == "down"
            # after first break, does the window close beyond the OR in the break direction?
            hold = ((up & (j.rc > j.oh)) | (dn & (j.rc < j.ol))).sum() / max((up | dn).sum(), 1)
            back = ((up & (j.rc < j.oh) & (j.rc > j.ol)) | (dn & (j.rc > j.ol) & (j.rc < j.oh))).sum() / max((up | dn).sum(), 1)
            orient = np.sign(j.oc - j.oo)
            same = (np.sign(j.rc - j.oc) == orient) & (orient != 0)
            rows.append({"split": sp, "open": name, "days": len(j), "OR_width_med_$": (j.oh - j.ol).median(),
                         "P_break_up_first": up.mean(), "P_break_down_first": dn.mean(), "P_no_break": (j.first_break == "none").mean(),
                         "P_break_both": ((j.rh > j.oh) & (j.rl < j.ol)).mean(),
                         "P_close_beyond_OR_after_break": hold, "P_close_back_inside_after_break": back,
                         "P_rest_same_dir_as_OR": same.sum() / max((orient != 0).sum(), 1),
                         "z_same_dir": zprop(same.sum(), (orient != 0).sum())})
    return pd.DataFrame(rows)


def reference_levels(m: pd.DataFrame, d: pd.DataFrame) -> pd.DataFrame:
    """Asian range taken during London/NY; previous-day high/low taken and rejected."""
    rows = []
    for sp in SPLITS:
        x = m[m.split == sp]
        dd = d[d.split == sp].set_index("day")
        asia = x[x.session == "Asia"].groupby("day").agg(ah=("high", "max"), al=("low", "min"), n=("open", "size"))
        later = x[x.session.isin(["London", "LDN-NY overlap", "New York"])].groupby("day").agg(h=("high", "max"), l=("low", "min"), c=("close", "last"))
        j = asia[asia.n > 300].join(later, how="inner")
        up, dn = j.h > j.ah, j.l < j.al
        rows.append({"split": sp, "level": "Asian range (in London+NY)", "days": len(j), "P_take_high": up.mean(), "P_take_low": dn.mean(),
                     "P_take_both": (up & dn).mean(), "P_take_neither": (~up & ~dn).mean(),
                     "P_close_back_inside_given_high_taken_only": ((up & ~dn) & (j.c < j.ah)).sum() / max((up & ~dn).sum(), 1),
                     "P_close_back_inside_given_low_taken_only": ((dn & ~up) & (j.c > j.al)).sum() / max((dn & ~up).sum(), 1)})
        p = dd[["high", "low", "n"]].shift().rename(columns={"high": "pdh", "low": "pdl", "n": "pn"})
        k = dd.join(p)
        k = k[(k.n > 1000) & (k.pn > 1000)]
        up, dn = k.high > k.pdh, k.low < k.pdl
        rows.append({"split": sp, "level": "Previous-day high/low", "days": len(k), "P_take_high": up.mean(), "P_take_low": dn.mean(),
                     "P_take_both": (up & dn).mean(), "P_take_neither": (~up & ~dn).mean(),
                     "P_close_back_inside_given_high_taken_only": ((up & ~dn) & (k.close < k.pdh)).sum() / max((up & ~dn).sum(), 1),
                     "P_close_back_inside_given_low_taken_only": ((dn & ~up) & (k.close > k.pdl)).sum() / max((dn & ~up).sum(), 1)})
    return pd.DataFrame(rows)


# =============================================================================== B. candles
def candles(m: pd.DataFrame):
    stats, acf_rows, cond = [], [], []
    for sp in SPLITS:
        x = m[m.split == sp]
        for tf in ["1min", "5min", "15min", "1h"]:
            b = x[["ts", "open", "high", "low", "close", "tick_volume"]].copy() if tf == "1min" else resample(x, tf)
            if tf != "1min":
                b = b[b.n >= {"5min": 4, "15min": 12, "1h": 50}[tf]]
            b = b.reset_index(drop=True)
            b["day"] = b.ts.dt.normalize()
            b["rng"] = b.high - b.low
            b["body"] = (b.close - b.open)
            b["dir"] = np.sign(b.body)
            b["atr"] = atr(b, 14).shift()                     # ATR known before this bar opens
            ok = b.day.eq(b.day.shift())                      # previous bar same trading day
            rr = b.rng.replace(0, np.nan)
            stats.append({"split": sp, "tf": tf, "bars": len(b), "range_med_$": b.rng.median(), "body/range_med": (b.body.abs() / rr).median(),
                          "upper_wick/range_med": ((b.high - b[["open", "close"]].max(axis=1)) / rr).median(),
                          "lower_wick/range_med": ((b[["open", "close"]].min(axis=1) - b.low) / rr).median(),
                          "P_up_bar": (b.dir > 0).mean(), "P_doji(body<10%)": ((b.body.abs() / rr) < 0.1).mean(),
                          "cost_C1_vs_med_range": C1_ROUNDTRIP / b.rng.median()})
            # autocorrelation of returns (within day) and of |returns|
            lr = np.log(b.close).diff().where(ok)
            n_eff = lr.notna().sum()
            for lag in [1, 2, 3, 5, 10]:
                a = lr.autocorr(lag)
                av = lr.abs().autocorr(lag)
                acf_rows.append({"split": sp, "tf": tf, "lag": lag, "acf_ret": a, "acf_absret": av, "band_95": 2 / np.sqrt(n_eff), "n": int(n_eff)})
            # conditional next-bar behaviour (in ATR units, direction-signed); horizon 1 and 3 bars, same day only
            fwd1 = (b.close.shift(-1) - b.close)
            fwd3 = (b.close.shift(-3) - b.close)
            same3 = b.day.eq(b.day.shift(-3))
            base_up = (b.dir > 0).sum() / (b.dir != 0).sum()

            def add(name, mask, sign):
                mk = mask & same3 & b.atr.notna()
                s = sign[mk]
                f1, f3 = (fwd1[mk] * s), (fwd3[mk] * s)
                n = int(mk.sum())
                if n < 30:
                    return
                nd = b.dir.shift(-1)[mk] * s
                nn = int((nd != 0).sum())          # exclude next bars with zero body
                k = int((nd > 0).sum())
                cond.append({"split": sp, "tf": tf, "condition": name, "n": n, "P_next_bar_continues": k / nn, "z_vs_50": zprop(k, nn),
                             "fwd1_$_mean": f1.mean(), "fwd3_$_mean": f3.mean(), "fwd3_ATR_mean": (f3 / b.atr[mk]).mean(),
                             "fwd3_t": f3.mean() / (f3.std() / np.sqrt(n)), "fwd3_net_of_C1_$": f3.mean() - C1_ROUNDTRIP})
            # streaks
            st = b.dir.groupby((b.dir != b.dir.shift()).cumsum()).cumcount() + 1
            for k in [1, 2, 3, 4, 5, 6]:
                add(f"streak={k} same-colour bars", (st == k) & (b.dir != 0), b.dir)
            disp = (b.body.abs() >= 1.5 * b.atr) & (b.body.abs() / rr >= 0.6)
            add("displacement (body>=1.5 ATR, body>=60% range)", disp, b.dir)
            big = (b.body.abs() >= 2.5 * b.atr) & (b.body.abs() / rr >= 0.6)
            add("big displacement (body>=2.5 ATR)", big, b.dir)
            uw = (b.high - b[["open", "close"]].max(axis=1)) / rr
            lw = (b[["open", "close"]].min(axis=1) - b.low) / rr
            add("rejection: upper wick>=60%, range>=1 ATR (fade = short)", (uw >= 0.6) & (b.rng >= b.atr), pd.Series(-1.0, index=b.index))
            add("rejection: lower wick>=60%, range>=1 ATR (fade = long)", (lw >= 0.6) & (b.rng >= b.atr), pd.Series(1.0, index=b.index))
            # engulfing
            pb = b.body.shift()
            eng = ok & (b.dir != 0) & (np.sign(pb) == -b.dir) & (b.body.abs() > pb.abs()) & \
                ((b[["open", "close"]].max(axis=1) >= b[["open", "close"]].max(axis=1).shift()) & (b[["open", "close"]].min(axis=1) <= b[["open", "close"]].min(axis=1).shift()))
            add("engulfing (trade in engulfing direction)", eng, b.dir)
            # inside bar: direction of prior 5-bar trend
            ib = ok & (b.high <= b.high.shift()) & (b.low >= b.low.shift())
            trend = np.sign(b.close - b.close.shift(5))
            add("inside bar (trade with prior 5-bar trend)", ib & (trend != 0), trend)
            # expansion / compression → next-bar range (volatility clustering), not direction
            nxt = b.rng.shift(-1) / b.atr
            for nm, mk in [("expansion range>=2 ATR", b.rng >= 2 * b.atr), ("compression range<=0.5 ATR", b.rng <= 0.5 * b.atr), ("all bars", b.atr.notna())]:
                mk = mk & b.day.eq(b.day.shift(-1)) & b.atr.notna()
                cond.append({"split": sp, "tf": tf, "condition": f"[vol] {nm}: next-bar range / ATR", "n": int(mk.sum()),
                             "next_range_ATR_mean": nxt[mk].mean(), "P_next_bar_continues": np.nan})
            cond.append({"split": sp, "tf": tf, "condition": "[baseline] P(bar up | non-zero body)", "n": len(b), "P_next_bar_continues": base_up})
    return pd.DataFrame(stats), pd.DataFrame(acf_rows), pd.DataFrame(cond)


# =============================================================================== C. barriers
def barriers(m: pd.DataFrame):
    dists = [0.5, 1, 1.5, 2, 3, 5, 7.5, 10, 15, 20]
    horizons = [1, 3, 5, 10, 15, 30, 60, 120]
    ks = [0.25, 0.5, 1, 1.5, 2, 3]
    HMAX = 120
    out_abs, out_norm, out_year, out_sess = [], [], [], []
    for sp in SPLITS:
        x = m[m.split == sp].reset_index(drop=True)
        H, L, C = x.high.values, x.low.values, x.close.values
        tmin = (x.ts.values.astype("datetime64[m]").astype("int64"))
        day = x.day.values
        # ATR of completed M15 bars at each minute
        b15 = resample(x, "15min")
        b15["atr15"] = atr(b15, 14)
        a = pd.merge_asof(x[["ts"]], b15[["avail", "atr15"]].rename(columns={"avail": "ts"}).dropna(), on="ts", direction="backward")
        atr15 = a.atr15.values
        starts = np.arange(0, len(x) - HMAX - 1, 5)
        Hw = np.lib.stride_tricks.sliding_window_view(H, HMAX + 1)[starts, 1:]
        Lw = np.lib.stride_tricks.sliding_window_view(L, HMAX + 1)[starts, 1:]
        rmax = np.maximum.accumulate(Hw, axis=1)
        rmin = np.minimum.accumulate(Lw, axis=1)
        e = C[starts][:, None]
        span = tmin[np.minimum(starts[:, None] + np.arange(1, HMAX + 1)[None, :], len(x) - 1)] - tmin[starts][:, None]
        sameday = day[np.minimum(starts[:, None] + np.arange(1, HMAX + 1)[None, :], len(x) - 1)] == day[starts][:, None]
        contiguous = (span <= np.arange(1, HMAX + 1)[None, :] + 5) & sameday   # allow <=5 missing minutes
        valid_upto = np.where(contiguous.all(axis=1), HMAX, contiguous.argmin(axis=1))  # number of usable bars
        sess = x.session.values[starts]
        yrs = x.ts.dt.year.values[starts]

        def first_idx(cond):
            any_ = cond.any(axis=1)
            return np.where(any_, cond.argmax(axis=1) + 1, 10 ** 6)

        def table(dvec, label, store, extra=None):
            iu = first_idx(rmax >= e + dvec[:, None])
            idn = first_idx(rmin <= e - dvec[:, None])
            for T in horizons:
                v = valid_upto >= T
                if extra is not None:
                    v &= extra
                u, dn = (iu <= T) & v, (idn <= T) & v
                n = int(v.sum())
                anyh = u | dn
                same = (iu == idn) & anyh
                upfirst = (iu < idn) & anyh
                dnfirst = (idn < iu) & anyh
                decided = upfirst | dnfirst
                store.append({"split": sp, "dist": label, "T_min": T, "n": n, "P_hit_up": u.sum() / n, "P_hit_down": dn.sum() / n,
                              "P_hit_any": anyh.sum() / n, "P_hit_both": (u & dn).sum() / n, "P_up_first|decided": upfirst.sum() / max(decided.sum(), 1),
                              "z_up_first": zprop(upfirst.sum(), decided.sum()), "P_same_bar_ambiguous|hit": same.sum() / max(anyh.sum(), 1)})

        for dval in dists:
            table(np.full(len(starts), dval), f"${dval:g}", out_abs)
        okatr = np.isfinite(atr15[starts])
        for k in ks:
            table(np.where(okatr, k * atr15[starts], np.inf), f"{k:g}xATR15", out_norm, extra=okatr)
        # stability: by year and by session for 1 x ATR15 within 30 / 60 min
        for yv in np.unique(yrs):
            tmp = []
            table(np.where(okatr, atr15[starts], np.inf), "1xATR15", tmp, extra=okatr & (yrs == yv))
            for r in tmp:
                if r["T_min"] in (30, 60):
                    out_year.append({**r, "year": int(yv)})
        for sv in np.unique(sess):
            tmp = []
            table(np.where(okatr, atr15[starts], np.inf), "1xATR15", tmp, extra=okatr & (sess == sv))
            for r in tmp:
                if r["T_min"] in (15, 60):
                    out_sess.append({**r, "session": sv})
        R.setdefault("barrier_samples", {})[sp] = {"starts": int(len(starts)), "atr15_median_$": float(np.nanmedian(atr15[starts]))}
    return pd.DataFrame(out_abs), pd.DataFrame(out_norm), pd.DataFrame(out_year), pd.DataFrame(out_sess)


# =============================================================================== figures
def fig_hourly(hr: pd.DataFrame):
    x = hr[hr.split == "dev"].sort_values("ny_hour")
    fig, axes = plt.subplots(2, 1, figsize=(9, 5.6), sharex=True, facecolor=SURFACE)
    for ax, col, ttl in [(axes[0], "range_vs_ATRd_med", "Median hourly range ÷ previous-day ATR(14) — DEV"),
                         (axes[1], "cost_C1_vs_med_range", "C1 round-trip cost ÷ median hourly range — DEV (lower is better)")]:
        style(ax)
        ax.bar(x.ny_hour, x[col], color=BLUE, width=0.7)
        ax.set_title(ttl, fontsize=9.5, color=INK, loc="left")
    axes[1].set_xticks(range(24))
    axes[1].set_xlabel("New York hour (server hour = NY + 7)", fontsize=8.5, color=MUTED)
    fig.tight_layout()
    fig.savefig(FIG / "atlas_hourly.png", dpi=150, facecolor=SURFACE)
    plt.close(fig)


def fig_barrier(ab: pd.DataFrame):
    x = ab[ab.split == "dev"].pivot(index="dist", columns="T_min", values="P_hit_up")
    order = [f"${d:g}" for d in [0.5, 1, 1.5, 2, 3, 5, 7.5, 10, 15, 20]]
    x = x.loc[order]
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("seq", SEQ)
    fig, ax = plt.subplots(figsize=(8, 5), facecolor=SURFACE)
    im = ax.imshow(x.values, cmap=cmap, vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(x.shape[1]), [f"{c}m" for c in x.columns], fontsize=8, color=MUTED)
    ax.set_yticks(range(x.shape[0]), x.index, fontsize=8, color=MUTED)
    for i in range(x.shape[0]):
        for j in range(x.shape[1]):
            v = x.values[i, j]
            ax.text(j, i, f"{v * 100:.0f}", ha="center", va="center", fontsize=7.5, color="white" if v > 0.5 else INK)
    ax.set_title("P(price rises ≥ distance within horizon), % — DEV 2022-03 → 2024-06", fontsize=9.5, color=INK, loc="left")
    for s in ax.spines.values():
        s.set_visible(False)
    fig.tight_layout()
    fig.savefig(FIG / "atlas_barrier_up.png", dpi=150, facecolor=SURFACE)
    plt.close(fig)


def fig_highlow(hl: pd.DataFrame):
    x = hl[hl.split == "dev"].set_index("ny_hour").reindex(range(24)).fillna(0)
    order = [(h + 18) % 24 for h in range(24)]  # trading day starts 18:00 NY
    x = x.loc[order]
    fig, axes = plt.subplots(2, 1, figsize=(9, 5), sharex=True, facecolor=SURFACE)
    for ax, col, ttl in [(axes[0], "P_day_high_in_hour", "When is the day's HIGH printed? share of days — DEV"),
                         (axes[1], "P_day_low_in_hour", "When is the day's LOW printed? share of days — DEV")]:
        style(ax)
        ax.bar(range(24), x[col] * 100, color=BLUE, width=0.7)
        ax.set_title(ttl, fontsize=9.5, color=INK, loc="left")
        ax.set_ylabel("%", fontsize=8, color=MUTED)
    axes[1].set_xticks(range(24), [str(h) for h in order], fontsize=8)
    axes[1].set_xlabel("New York hour, in trading-day order (day opens 18:00 NY)", fontsize=8.5, color=MUTED)
    fig.tight_layout()
    fig.savefig(FIG / "atlas_day_high_low_timing.png", dpi=150, facecolor=SURFACE)
    plt.close(fig)


# =============================================================================== main
def main():
    m = load_research(SPLITS)
    d = daily_bars(m)
    m = m.merge(d[["day", "atr_d_prev"]], on="day", how="left")

    hr = hourly(m, d); hr.to_csv(TAB / "atlas_hourly.csv", index=False)
    dw = day_of_week(d); dw.to_csv(TAB / "atlas_day_of_week.csv", index=False)
    se, hl = sessions(m, d); se.to_csv(TAB / "atlas_sessions.csv", index=False); hl.to_csv(TAB / "atlas_day_high_low_timing.csv", index=False)
    orr = opening_ranges(m, d); orr.to_csv(TAB / "atlas_opening_ranges.csv", index=False)
    lv = reference_levels(m, d); lv.to_csv(TAB / "atlas_reference_levels.csv", index=False)
    cs, acf, cond = candles(m)
    cs.to_csv(TAB / "atlas_candle_stats.csv", index=False); acf.to_csv(TAB / "atlas_autocorr.csv", index=False); cond.to_csv(TAB / "atlas_candle_conditions.csv", index=False)
    ab, an, ay, ass = barriers(m)
    ab.to_csv(TAB / "atlas_barrier_usd.csv", index=False); an.to_csv(TAB / "atlas_barrier_atr.csv", index=False)
    ay.to_csv(TAB / "atlas_barrier_by_year.csv", index=False); ass.to_csv(TAB / "atlas_barrier_by_session.csv", index=False)
    fig_hourly(hr); fig_barrier(ab); fig_highlow(hl)
    for name, df in [("hourly", hr), ("dow", dw), ("sessions", se), ("opening_ranges", orr), ("levels", lv), ("candle_stats", cs),
                     ("autocorr", acf), ("candle_conditions", cond), ("barrier_usd", ab), ("barrier_atr", an), ("barrier_year", ay), ("barrier_session", ass)]:
        R[name] = df.round(5).to_dict("records")
    (OUT / "atlas_results.json").write_text(json.dumps(R, indent=1, default=str), encoding="utf-8")
    print("done")


if __name__ == "__main__":
    main()
