"""Phase 3 — pre-registered hypotheses. All times are SERVER time (= New York + 7 h).

Each generator returns a list of engine.Order. Every quantity used to build an order is known at
the moment the order is created (completed bars only). Parameter grids are fixed here, before any
result is seen, and every configuration is run and reported (no silent dropping).
"""
from __future__ import annotations

import itertools

import numpy as np
import pandas as pd

from engine import Market, Order
from features import atr, resample

# ----------------------------------------------------------------------------- context
def context(mkt: Market) -> dict:
    m = mkt.m
    smin = (m.ts.dt.hour * 60 + m.ts.dt.minute).values
    day = m.ts.dt.normalize()
    days = {}
    for d, idx in pd.Series(np.arange(len(m))).groupby(day.values):
        days[pd.Timestamp(d)] = (int(idx.iloc[0]), int(idx.iloc[-1]))
    # daily bars, previous-day values known at day start
    dd = m.groupby(day).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"), n=("open", "size"))
    dd["atr_d"] = atr(dd, 14)
    prev = dd.shift()
    prev = prev.where(dd.index.to_series().diff().dt.days.le(4), axis=0)   # no stale "previous day" across long gaps
    # ATR(14) of completed M15 bars, known at each M1 bar's open
    b15 = resample(m, "15min")
    b15["atr15"] = atr(b15, 14)
    a15 = pd.merge_asof(m[["ts"]], b15[["avail", "atr15"]].dropna().rename(columns={"avail": "ts"}), on="ts", direction="backward").atr15.values
    return {"smin": smin, "days": days, "pdh": prev.high, "pdl": prev.low, "pd_n": prev.n, "atr_d_prev": prev.atr_d, "atr15": a15}


def rng_idx(ctx, d, a_min, b_min):
    """Indices of day d with a_min <= server minute < b_min."""
    s, e = ctx["days"][d]
    sm = ctx["smin"][s:e + 1]
    sel = np.nonzero((sm >= a_min) & (sm < b_min))[0]
    return (s + sel[0], s + sel[-1]) if len(sel) else (None, None)


def first_at(ctx, d, minute):
    s, e = ctx["days"][d]
    sm = ctx["smin"][s:e + 1]
    k = np.nonzero(sm >= minute)[0]
    return s + int(k[0]) if len(k) else None


H = lambda h, m=0: h * 60 + m   # server clock helper


# ----------------------------------------------------------------------------- H01 Asian range breakout (Model D)
def h01_asia_breakout(mkt, ctx, sl_mode, tp_R, width_filter):
    """Asian range = server 02:00-09:00 (19:00-02:00 NY). OCO buy-stop above / sell-stop below the range,
    active 10:00-17:00 server (03:00-10:00 NY). Buffer = 0.05 x ATR15. SL = opposite side or range mid.
    Time exit 19:00 server (12:00 NY). width_filter: 'all' or 'narrow' (range <= 0.35 x previous-day ATR)."""
    out = []
    for d in ctx["days"]:
        a, b = rng_idx(ctx, d, H(2), H(9))
        i0 = first_at(ctx, d, H(10))
        ie = first_at(ctx, d, H(17))
        ix = first_at(ctx, d, H(19))
        if a is None or i0 is None or ie is None or ix is None or (b - a) < 300:
            continue
        ah, al = mkt.h[a:b + 1].max(), mkt.l[a:b + 1].min()
        atrd, a15 = ctx["atr_d_prev"].get(d, np.nan), ctx["atr15"][i0]
        if not (np.isfinite(atrd) and np.isfinite(a15)):
            continue
        if width_filter == "narrow" and (ah - al) > 0.35 * atrd:
            continue
        buf = 0.05 * a15
        mid = (ah + al) / 2
        sl_l = al - buf if sl_mode == "opposite" else mid
        sl_s = ah + buf if sl_mode == "opposite" else mid
        out.append([Order(+1, "stop", i0, ie - 1, sl=sl_l, price=ah + buf, tp_R=tp_R, i_exit=ix, tag="long"),
                    Order(-1, "stop", i0, ie - 1, sl=sl_s, price=al - buf, tp_R=tp_R, i_exit=ix, tag="short")])
    return out   # list of OCO groups


# ----------------------------------------------------------------------------- sweep-and-reverse (H02 Asia, H03 PDH/PDL)
def _sweep_reverse(mkt, ctx, level_fn, tf, tp_R, win=(H(10), H(19)), exit_min=H(21)):
    """Price trades beyond a reference high (low), then a completed `tf` bar closes back inside →
    market order in the reversal direction at the next bar. SL = extreme since the sweep + 0.1 x ATR15.
    First qualifying event per day only."""
    out = []
    m = mkt.m
    for d in ctx["days"]:
        lv = level_fn(d)
        if lv is None:
            continue
        hi_lv, lo_lv = lv
        a, b = rng_idx(ctx, d, win[0], win[1])
        ix = first_at(ctx, d, exit_min)
        if a is None:
            continue
        seg = m.iloc[a:b + 1]
        bars = seg.set_index("ts").resample(tf, label="left", closed="left").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        swept_hi = swept_lo = False
        ext_hi, ext_lo = -np.inf, np.inf
        for t, r in bars.iterrows():
            if r.high > hi_lv:
                swept_hi = True
            if r.low < lo_lv:
                swept_lo = True
            if swept_hi:
                ext_hi = max(ext_hi, r.high)
            if swept_lo:
                ext_lo = min(ext_lo, r.low)
            avail = t + pd.Timedelta(tf)
            i_sig = mkt.idx_at(avail)
            if i_sig > b or i_sig >= mkt.n:
                break
            a15 = ctx["atr15"][i_sig]
            if not np.isfinite(a15):
                continue
            if swept_hi and r.close < hi_lv and r.close > lo_lv:
                out.append(Order(-1, "market", i_sig, i_sig, sl=ext_hi + 0.1 * a15, tp_R=tp_R, i_exit=ix if ix else -1, tag="short"))
                break
            if swept_lo and r.close > lo_lv and r.close < hi_lv:
                out.append(Order(+1, "market", i_sig, i_sig, sl=ext_lo - 0.1 * a15, tp_R=tp_R, i_exit=ix if ix else -1, tag="long"))
                break
    return out


def h02_asia_sweep(mkt, ctx, tf, tp_R):
    def lv(d):
        a, b = rng_idx(ctx, d, H(2), H(9))
        if a is None or (b - a) < 300:
            return None
        return mkt.h[a:b + 1].max(), mkt.l[a:b + 1].min()
    return _sweep_reverse(mkt, ctx, lv, tf, tp_R, win=(H(10), H(17)), exit_min=H(19))


def h03_pd_sweep(mkt, ctx, tf, tp_R):
    def lv(d):
        if not (ctx["pd_n"].get(d, 0) and ctx["pd_n"].get(d, 0) > 1000):
            return None
        return ctx["pdh"][d], ctx["pdl"][d]
    return _sweep_reverse(mkt, ctx, lv, tf, tp_R, win=(H(10), H(19)), exit_min=H(21))


# ----------------------------------------------------------------------------- H04 NY opening-range breakout (Model F)
def h04_ny_orb(mkt, ctx, or_len, tp_R, width_filter):
    """OR = server 16:30 + or_len minutes (NY cash open 09:30). OCO stop orders at OR high/low until 19:00 server.
    SL = other side of OR. Exit 21:00 server (14:00 NY). width_filter 'narrow': OR <= 0.25 x previous-day ATR."""
    out = []
    for d in ctx["days"]:
        a, b = rng_idx(ctx, d, H(16, 30), H(16, 30) + or_len)
        i0 = first_at(ctx, d, H(16, 30) + or_len)
        ie = first_at(ctx, d, H(19))
        ix = first_at(ctx, d, H(21))
        if a is None or i0 is None or ie is None or ix is None or (b - a) < or_len - 3:
            continue
        oh, ol = mkt.h[a:b + 1].max(), mkt.l[a:b + 1].min()
        atrd = ctx["atr_d_prev"].get(d, np.nan)
        if not np.isfinite(atrd):
            continue
        if width_filter == "narrow" and (oh - ol) > 0.25 * atrd:
            continue
        out.append([Order(+1, "stop", i0, ie - 1, sl=ol, price=oh + 0.01, tp_R=tp_R, i_exit=ix, tag="long"),
                    Order(-1, "stop", i0, ie - 1, sl=oh, price=ol - 0.01, tp_R=tp_R, i_exit=ix, tag="short")])
    return out


# ----------------------------------------------------------------------------- H05 trend pullback (Model B)
def h05_trend_pullback(mkt, ctx, tp_R, bias):
    """Bias from completed H1 bars: close > EMA50 and EMA50 rising over 5 bars (mirror for shorts);
    bias='h1h4' also requires the same on completed H4 bars. Window 15:00-19:00 server (08-12 NY).
    On completed M5 bars: a pullback that touched EMA20(M5) in the last 3 bars, then an M5 close above the
    previous M5 high (below the previous low for shorts) → market entry. SL = 6-bar M5 extreme -/+ 0.1 ATR15.
    One trade per day. Time exit 21:00 server."""
    m = mkt.m
    m5 = resample(m, "5min")
    m5["ema20"] = m5.close.ewm(span=20, adjust=False).mean()
    def trend(rule):
        b = resample(m, rule)
        b["ema"] = b.close.ewm(span=50, adjust=False).mean()
        b["dir"] = np.where((b.close > b.ema) & (b.ema > b.ema.shift(5)), 1, np.where((b.close < b.ema) & (b.ema < b.ema.shift(5)), -1, 0))
        return b[["avail", "dir"]].rename(columns={"avail": "ts"})
    m5 = pd.merge_asof(m5.sort_values("avail"), trend("1h").rename(columns={"ts": "avail", "dir": "d1"}), on="avail", direction="backward")
    m5 = pd.merge_asof(m5, trend("4h").rename(columns={"ts": "avail", "dir": "d4"}), on="avail", direction="backward")
    m5["touch_up"] = (m5.low <= m5.ema20).rolling(3).max()      # pullback into EMA in an uptrend
    m5["touch_dn"] = (m5.high >= m5.ema20).rolling(3).max()
    m5["lo6"] = m5.low.rolling(6).min()
    m5["hi6"] = m5.high.rolling(6).max()
    m5["day"] = m5.ts.dt.normalize()
    sm = m5.avail.dt.hour * 60 + m5.avail.dt.minute
    cand = m5[(sm >= H(15)) & (sm < H(19)) & m5.day.eq(m5.avail.dt.normalize())]
    out, used = [], set()
    for r in cand.itertuples():
        if r.day in used:
            continue
        dirn = r.d1 if bias == "h1" else (r.d1 if r.d1 == r.d4 else 0)
        if dirn == 0 or not np.isfinite(dirn):
            continue
        prev = m5.loc[r.Index - 1]
        i_sig = mkt.idx_at(r.avail)
        if i_sig >= mkt.n:
            continue
        a15 = ctx["atr15"][i_sig]
        ix = first_at(ctx, r.day, H(21))
        if not np.isfinite(a15) or ix is None:
            continue
        if dirn > 0 and r.touch_up == 1 and r.close > prev.high and r.close > r.ema20:
            out.append(Order(+1, "market", i_sig, i_sig, sl=r.lo6 - 0.1 * a15, tp_R=tp_R, i_exit=ix, tag="long")); used.add(r.day)
        elif dirn < 0 and r.touch_dn == 1 and r.close < prev.low and r.close < r.ema20:
            out.append(Order(-1, "market", i_sig, i_sig, sl=r.hi6 + 0.1 * a15, tp_R=tp_R, i_exit=ix, tag="short")); used.add(r.day)
    return out


# ----------------------------------------------------------------------------- H06 Bollinger mean reversion in Asia (Model C)
def h06_bb_revert(mkt, ctx, k, sl_atr):
    """Completed M15 close outside Bollinger(20, k) during 02:00-09:00 server → fade at market.
    TP = middle band at signal time; SL = entry ∓ sl_atr x ATR15; time exit 60 min; max 2 trades/day, no overlap."""
    m15 = resample(mkt.m, "15min")
    m15["mid"] = m15.close.rolling(20).mean()
    m15["sd"] = m15.close.rolling(20).std()
    sm = m15.ts.dt.hour * 60 + m15.ts.dt.minute
    cand = m15[(sm >= H(2)) & (sm < H(9) - 15) & m15.sd.notna()]
    out, last_exit, cnt = [], -1, {}
    for r in cand.itertuples():
        d = r.ts.normalize()
        if cnt.get(d, 0) >= 2:
            continue
        i_sig = mkt.idx_at(r.avail)
        if i_sig >= mkt.n or i_sig <= last_exit:
            continue
        a15 = ctx["atr15"][i_sig]
        if not np.isfinite(a15):
            continue
        ix = i_sig + 60
        if r.close > r.mid + k * r.sd:
            out.append(Order(-1, "market", i_sig, i_sig, sl=r.close + sl_atr * a15, tp=r.mid, i_exit=ix, tag="short"))
        elif r.close < r.mid - k * r.sd:
            out.append(Order(+1, "market", i_sig, i_sig, sl=r.close - sl_atr * a15, tp=r.mid, i_exit=ix, tag="long"))
        else:
            continue
        cnt[d] = cnt.get(d, 0) + 1
        last_exit = ix
    return out


# ----------------------------------------------------------------------------- H07 last-hour fade (atlas A5)
def h07_last_hour_fade(mkt, ctx, thr, sl_atr):
    """At 23:00 server (16:00 NY) trade against the 22:00-23:00 server move if |move| >= thr x ATR15.
    SL = sl_atr x ATR15; exit at 23:50 server (day end)."""
    out = []
    for d in ctx["days"]:
        a, b = rng_idx(ctx, d, H(22), H(23))
        i0 = first_at(ctx, d, H(23))
        if a is None or i0 is None or (b - a) < 50:
            continue
        mv = mkt.c[b] - mkt.o[a]
        a15 = ctx["atr15"][i0]
        if not np.isfinite(a15) or abs(mv) < thr * a15 or mv == 0:
            continue
        s = -int(np.sign(mv))
        out.append(Order(s, "market", i0, i0, sl=mkt.o[i0] - s * sl_atr * a15, i_exit=-1, tag="fade"))
    return out


# ----------------------------------------------------------------------------- H08 ICT: sweep → displacement FVG → limit retest (Model A)
def h08_ict_sweep_fvg(mkt, ctx, level, tp_R):
    """Window 10:00-18:00 server (03:00-11:00 NY). After price sweeps the reference high (Asia high or PDH),
    look for a bearish M5 FVG formed within the next 30 min: low[i-2] > high[i] with the middle bar's body
    >= 1 x ATR(14, M5). Sell-limit at the bottom of the gap (high[i]), valid 60 min. SL = sweep extreme +
    0.1 x ATR15. TP = tp_R x risk. Mirror for lows. First setup per day. Time exit 21:00 server."""
    m = mkt.m
    out = []
    for d in ctx["days"]:
        if level == "asia":
            a, b = rng_idx(ctx, d, H(2), H(9))
            if a is None or (b - a) < 300:
                continue
            hi_lv, lo_lv = mkt.h[a:b + 1].max(), mkt.l[a:b + 1].min()
        else:
            if not (ctx["pd_n"].get(d, 0) and ctx["pd_n"].get(d, 0) > 1000):
                continue
            hi_lv, lo_lv = ctx["pdh"][d], ctx["pdl"][d]
        a, b = rng_idx(ctx, d, H(10), H(18))
        ix = first_at(ctx, d, H(21))
        if a is None or ix is None:
            continue
        seg = m.iloc[a:b + 1].set_index("ts")
        m5 = seg.resample("5min", label="left", closed="left").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        if len(m5) < 20:
            continue
        pc = m5.close.shift()
        tr = np.maximum(m5.high - m5.low, np.maximum((m5.high - pc).abs(), (m5.low - pc).abs()))
        atr5 = tr.ewm(alpha=1 / 14, adjust=False, min_periods=5).mean().shift()
        H5, L5, O5, C5 = m5.high.values, m5.low.values, m5.open.values, m5.close.values
        t5 = m5.index
        sweep_hi_t = sweep_lo_t = None
        ext_hi, ext_lo = -np.inf, np.inf
        done = False
        for i in range(len(m5)):
            if H5[i] > hi_lv and sweep_hi_t is None:
                sweep_hi_t = i
            if L5[i] < lo_lv and sweep_lo_t is None:
                sweep_lo_t = i
            if sweep_hi_t is not None:
                ext_hi = max(ext_hi, H5[i])
            if sweep_lo_t is not None:
                ext_lo = min(ext_lo, L5[i])
            if i < 2 or not np.isfinite(atr5.iloc[i - 1]):
                continue
            avail = t5[i] + pd.Timedelta("5min")
            i_sig = mkt.idx_at(avail)
            if i_sig >= mkt.n:
                break
            a15 = ctx["atr15"][i_sig]
            if not np.isfinite(a15):
                continue
            body_mid = abs(C5[i - 1] - O5[i - 1])
            disp = body_mid >= atr5.iloc[i - 1]
            if sweep_hi_t is not None and i - sweep_hi_t <= 6 and disp and C5[i - 1] < O5[i - 1] and L5[i - 2] > H5[i]:
                out.append(Order(-1, "limit", i_sig, i_sig + 60, sl=ext_hi + 0.1 * a15, price=H5[i], tp_R=tp_R, i_exit=ix, tag="short"))
                done = True
            elif sweep_lo_t is not None and i - sweep_lo_t <= 6 and disp and C5[i - 1] > O5[i - 1] and H5[i - 2] < L5[i]:
                out.append(Order(+1, "limit", i_sig, i_sig + 60, sl=ext_lo - 0.1 * a15, price=L5[i], tp_R=tp_R, i_exit=ix, tag="long"))
                done = True
            if done:
                break
    return out


# ----------------------------------------------------------------------------- H00 random baseline
def h00_random(mkt, ctx, seed, tp_R):
    """Benchmark: one trade per day at a random minute 15:00-19:00 server, random side, SL 1 x ATR15, TP tp_R x risk."""
    rng = np.random.default_rng(seed)
    out = []
    for d in ctx["days"]:
        a, b = rng_idx(ctx, d, H(15), H(19))
        ix = first_at(ctx, d, H(21))
        if a is None or ix is None:
            continue
        i0 = int(rng.integers(a, b + 1))
        a15 = ctx["atr15"][i0]
        if not np.isfinite(a15):
            continue
        s = int(rng.choice([-1, 1]))
        out.append(Order(s, "market", i0, i0, sl=mkt.o[i0] - s * a15, tp_R=tp_R, i_exit=ix, tag="rand"))
    return out


# ----------------------------------------------------------------------------- registry (fixed grids)
REGISTRY = {
    "H00_random_baseline": (h00_random, {"seed": [1, 2, 3], "tp_R": [1.5]}),
    "H01_asia_range_breakout": (h01_asia_breakout, {"sl_mode": ["opposite", "mid"], "tp_R": [1.0, 1.5, 2.0], "width_filter": ["all", "narrow"]}),
    "H02_asia_sweep_reverse": (h02_asia_sweep, {"tf": ["5min", "15min"], "tp_R": [1.0, 1.5, 2.0]}),
    "H03_pdhl_sweep_reverse": (h03_pd_sweep, {"tf": ["5min", "15min"], "tp_R": [1.0, 1.5, 2.0]}),
    "H04_ny_opening_range_breakout": (h04_ny_orb, {"or_len": [15, 30], "tp_R": [1.0, 1.5, 2.0], "width_filter": ["all", "narrow"]}),
    "H05_trend_pullback": (h05_trend_pullback, {"tp_R": [1.0, 1.5, 2.0], "bias": ["h1", "h1h4"]}),
    "H06_bollinger_revert_asia": (h06_bb_revert, {"k": [2.0, 2.5], "sl_atr": [1.0, 1.5]}),
    "H07_last_hour_fade": (h07_last_hour_fade, {"thr": [0.0, 0.5], "sl_atr": [1.0, 2.0]}),
    "H08_ict_sweep_fvg_limit": (h08_ict_sweep_fvg, {"level": ["asia", "pdhl"], "tp_R": [1.5, 2.0, 3.0]}),
}


def grid(params: dict):
    keys = list(params)
    for vals in itertools.product(*[params[k] for k in keys]):
        yield dict(zip(keys, vals))
