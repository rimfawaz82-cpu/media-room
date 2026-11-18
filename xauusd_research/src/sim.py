"""Execution simulator.

Signals are decided on a signal timeframe (M15 or M5) at bar close.  Orders are then simulated
on the FINEST data available at that moment: M1 (from 2026-08-07), M5 (from 2025-06-23),
otherwise M15.  When stop and target are both inside one bar of the execution series the
outcome is ambiguous -> conservative: stop first (flag `amb`=1).

Order types: 0 market (fill at open of first execution bar after the decision time),
             1 stop (fills when price trades through; gap -> fill at open),
             2 limit (fills when price trades to it; gap -> fill at open).
Prices are BID. Costs are charged as a round-trip in basis points of price (spread+commission)
plus extra slippage on stop-type fills (stop entry, stop-loss exit).
"""
import numpy as np, pandas as pd
from numba import njit
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from data import load, TF_MIN

_EXEC = None


def exec_series(end=None):
    global _EXEC
    if _EXEC is not None:
        return _EXEC
    m15, m5, m1 = load("M15"), load("M5"), load("M1")
    t5, t1 = m5.index[0], m1.index[0]
    parts = [m15[m15.index + pd.Timedelta(minutes=15) <= t5.floor("15min")].assign(g=15),
             m5[(m5.index >= t5) & (m5.index + pd.Timedelta(minutes=5) <= t1.floor("5min"))].assign(g=5), m1.assign(g=1)]
    ex = pd.concat(parts)
    # make the M5 start align to an M15 boundary (first M5 bar inside the M15 bar 15:45 already covered)
    ex = ex[~ex.index.duplicated()]
    # remove M15 bar that overlaps the first M5 bar
    s = ex.index.values.astype("datetime64[m]").astype(np.int64)
    e = s + ex.g.values
    # historical bar spread (points, point=0.01 USD). 0 = not recorded -> fill with median of same NY hour
    sp = ex.spread.astype(float).replace(0, np.nan)
    from data import server_to_utc
    nyh = server_to_utc(ex.index).tz_convert("America/New_York").hour
    sp = sp.fillna(sp.groupby(nyh).transform("median"))
    _EXEC = dict(sp=sp.values * 0.01, t=s, te=e, o=ex.open.values, h=ex.high.values, l=ex.low.values, c=ex.close.values, g=ex.g.values.astype(np.int64), idx=ex.index)
    return _EXEC


@njit(cache=True)
def _sim(t, te, o, h, l, c, g, dec, side, otype, px, expiry, sl, tp, tex, be_r):
    n = len(dec)
    ent_i = np.full(n, -1); ex_i = np.full(n, -1)
    ent_p = np.full(n, np.nan); ex_p = np.full(n, np.nan)
    reason = np.zeros(n, np.int64)  # 1 tp 2 sl 3 time 4 expired(no fill) 5 be
    amb = np.zeros(n, np.int64)
    stopfill = np.zeros(n, np.int64)
    N = len(t)
    for k in range(n):
        i = np.searchsorted(t, dec[k])  # first bar starting at/after decision
        if i >= N:
            continue
        s = side[k]
        filled = False
        # ---- entry
        while i < N:
            if t[i] >= expiry[k] and otype[k] != 0:
                reason[k] = 4
                break
            if t[i] >= tex[k]:
                reason[k] = 4
                break
            if otype[k] == 0:
                ent_p[k] = o[i]; filled = True; break
            elif otype[k] == 1:
                if s == 1 and h[i] >= px[k]:
                    ent_p[k] = max(px[k], o[i]); filled = True; stopfill[k] = 1; break
                if s == -1 and l[i] <= px[k]:
                    ent_p[k] = min(px[k], o[i]); filled = True; stopfill[k] = 1; break
            else:
                if s == 1 and l[i] <= px[k]:
                    ent_p[k] = min(px[k], o[i]); filled = True; break
                if s == -1 and h[i] >= px[k]:
                    ent_p[k] = max(px[k], o[i]); filled = True; break
            i += 1
        if not filled:
            if reason[k] == 0:
                reason[k] = 4
            continue
        ent_i[k] = i
        stop = sl[k]
        risk = abs(ent_p[k] - sl[k])
        first = True
        be_done = False
        # ---- manage
        while i < N:
            if t[i] >= tex[k] and not first:
                ex_p[k] = o[i]; ex_i[k] = i; reason[k] = 3; break
            hs = (l[i] <= stop) if s == 1 else (h[i] >= stop)
            ht = False
            if not np.isnan(tp[k]):
                ht = (h[i] >= tp[k]) if s == 1 else (l[i] <= tp[k])
            if first and otype[k] != 0:
                # fill bar: path order unknown on coarse bars -> only stop allowed unless finest (M1)
                # or the bar closed beyond the target
                if ht and not hs:
                    beyond = (c[i] >= tp[k]) if s == 1 else (c[i] <= tp[k])
                    if not (g[i] == 1 or beyond):
                        ht = False
            if hs and ht:
                amb[k] = 1
                ht = False
            if hs:
                gap = (o[i] < stop) if s == 1 else (o[i] > stop)
                ex_p[k] = o[i] if (gap and not first) else stop
                ex_i[k] = i; reason[k] = 5 if be_done else 2; break
            if ht:
                ex_p[k] = tp[k]; ex_i[k] = i; reason[k] = 1; break
            # move stop to breakeven after be_r R in favour (evaluated on close of bar)
            if be_r[k] > 0 and not be_done:
                fav = (c[i] - ent_p[k]) * s
                if fav >= be_r[k] * risk:
                    stop = ent_p[k]; be_done = True
            first = False
            i += 1
        if ex_i[k] == -1 and i >= N:
            ex_i[k] = N - 1; ex_p[k] = c[N - 1]; reason[k] = 3
    return ent_i, ex_i, ent_p, ex_p, reason, amb, stopfill


def to_min(ts):
    return pd.DatetimeIndex(ts).values.astype("datetime64[m]").astype(np.int64)


def simulate(sig, cost_bps=None, slip_bps=0.5, one_at_a_time=True, max_per_day=99, oco=True):
    """sig: DataFrame with columns dec(ts server), side, otype, px, expiry(ts), sl, tp, tex(ts), [be_r], [oco], tag cols.
    Returns trades DataFrame (filled trades only) with R results."""
    E = exec_series()
    if len(sig) == 0:
        return pd.DataFrame()
    sig = sig.sort_values("dec").reset_index(drop=True)
    be = sig["be_r"].values.astype(float) if "be_r" in sig else np.zeros(len(sig))
    r = _sim(E["t"], E["te"], E["o"], E["h"], E["l"], E["c"], E["g"], to_min(sig.dec), sig.side.values.astype(np.int64),
             sig.otype.values.astype(np.int64), sig.px.values.astype(float), to_min(sig.expiry), sig.sl.values.astype(float),
             sig.tp.values.astype(float), to_min(sig.tex), be)
    ent_i, ex_i, ent_p, ex_p, reason, amb, stopfill = r
    df = sig.copy()
    df["filled"] = ent_i >= 0
    df["entry_ts"] = pd.NaT; df["exit_ts"] = pd.NaT
    f = ent_i >= 0
    df.loc[f, "entry_ts"] = E["idx"][ent_i[f]]
    df.loc[f, "exit_ts"] = E["idx"][ex_i[f]] + pd.to_timedelta(np.where(reason[f] == 3, 0, E["g"][ex_i[f]]), unit="m")
    df["exec_tf"] = np.where(f, E["g"][np.maximum(ent_i, 0)], 0)
    df["spread_entry"] = np.where(f, E["sp"][np.maximum(ent_i, 0)], np.nan)
    df["spread_exit"] = np.where(f, E["sp"][np.maximum(ex_i, 0)], np.nan)
    df["entry"] = ent_p; df["exit"] = ex_p; df["reason"] = reason; df["amb"] = amb; df["stopfill"] = stopfill
    df = df[df.filled].copy()
    if oco and "oco" in df:
        # keep first-filled order of each OCO group; ties -> conservative (worse gross result)
        df["gross"] = df.side * (df.exit - df.entry)
        df = df.sort_values(["oco", "entry_ts", "gross"]).groupby("oco", as_index=False).head(1)
    df = df.sort_values("entry_ts")
    if one_at_a_time:
        keep = []; last_exit = pd.Timestamp(0); cnt = {}
        for idx, row in zip(df.index, df.itertuples()):
            d = row.entry_ts.normalize()
            if row.entry_ts < last_exit or cnt.get(d, 0) >= max_per_day:
                continue
            keep.append(idx); last_exit = row.exit_ts; cnt[d] = cnt.get(d, 0) + 1
        df = df.loc[keep]
    return finalize(df, cost_bps, slip_bps)


COMMISSION = 0.07  # USD per oz round trip (~$7 per 100oz lot)


def finalize(df, cost_bps=None, slip_bps=0.5):
    """cost_bps=None -> realistic: historical bar spread paid on the ask side (entry for longs,
    exit for shorts) + commission + slip_bps on stop-type fills. cost_bps=x -> fixed x bp round trip
    + slippage (stress scenarios)."""
    df = df.copy()
    ref = df["ref"] if "ref" in df else df.entry
    df["risk"] = (ref - df.sl).abs()
    stop_exit = df.reason.isin([2]).astype(int)
    slip = df.entry * slip_bps * (df.stopfill + stop_exit) / 1e4
    if cost_bps is None:
        spread = np.where(df.side == 1, df.spread_entry, df.spread_exit)
        df["cost"] = spread + COMMISSION + slip
    else:
        df["cost"] = df.entry * cost_bps / 1e4 + slip
    df["gross_usd"] = df.side * (df.exit - df.entry)
    df["net_usd"] = df.gross_usd - df.cost
    df["R_gross"] = df.gross_usd / df.risk
    df["R"] = df.net_usd / df.risk
    df["day"] = df.entry_ts.dt.normalize()
    return df


def recost(df, cost_bps=None, slip_bps=0.5):
    return finalize(df, cost_bps, slip_bps)
