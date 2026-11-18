"""Strategy signal generators. Each returns a DataFrame of order specs that sim.simulate() executes.
All conditions use only columns known at the signal bar's close (see features.py).
Columns: dec, side, otype(0 mkt,1 stop,2 limit), px, ref (planned entry for R), sl, tp, expiry, tex, be_r, oco
"""
import numpy as np, pandas as pd

H = pd.Timedelta(hours=1)


def at_clock(rows, col, target):
    """server timestamp at which local clock `col` (ldn_h / ny_h of bar START) reaches `target` hours,
    same local day as the decision. If already past, returns decision time."""
    cur = rows[col] + 0.25 * 0  # bar-start clock
    delta = (target - cur) * 3600
    return rows.index + pd.to_timedelta(np.maximum(delta, 0), unit="s")


def _mk(rows, side, otype, px, sl, tp, expiry, tex, be_r=0.0, oco=None, ref=None):
    s = pd.DataFrame({"dec": rows["dec"].values, "side": side, "otype": otype, "px": np.asarray(px, float),
                      "sl": np.asarray(sl, float), "tp": np.asarray(tp, float),
                      "expiry": pd.DatetimeIndex(expiry), "tex": pd.DatetimeIndex(tex), "be_r": be_r,
                      "atr": rows["atr"].values, "day": rows["day"].values, "split": rows["split"].values})
    s["ref"] = np.asarray(ref if ref is not None else (px if otype != 0 else rows["close"].values), float)
    if oco is not None:
        s["oco"] = oco
    return s


def trend_ok(rows, side, f):
    if f == "none":
        return np.ones(len(rows), bool)
    if f == "D1":
        return (rows.D1_trend == side).values
    if f == "H4":
        return (rows.H4_trend == side).values
    if f == "D1notagainst":
        return (rows.D1_trend != -side).values
    if f == "H1H4":
        return ((rows.H1_trend == side) & (rows.H4_trend == side)).values
    if f == "D1H1":
        return ((rows.D1_trend == side) & (rows.H1_trend == side)).values
    raise ValueError(f)


# ---------------------------------------------------------------- 1 Asia range breakout (London)
def asia_breakout(b, sl_mode="opp", R=2.0, width="all", trend="none", buf=0.1, start=7.0, end=10.0, exit_ldn=16.0):
    r = b[(b.ldn_h == start - 0.25)].dropna(subset=["asia_hi", "asia_lo"])  # bar closing at London `start`
    w = r.asia_w / r.D1_atr
    if width == "narrow":
        r = r[w < 0.5]
    elif width == "wide":
        r = r[w >= 0.5]
    out = []
    for side in (1, -1):
        rr = r[trend_ok(r, side, trend)]
        px = rr.asia_hi + buf * rr.atr if side == 1 else rr.asia_lo - buf * rr.atr
        if sl_mode == "opp":
            sl = rr.asia_lo - buf * rr.atr if side == 1 else rr.asia_hi + buf * rr.atr
        else:  # mid
            sl = (rr.asia_hi + rr.asia_lo) / 2
        risk = (px - sl).abs()
        tp = px + side * R * risk if R else np.nan
        out.append(_mk(rr, side, 1, px, sl, tp, at_clock(rr, "ldn_h", end), at_clock(rr, "ldn_h", exit_ldn), oco=rr.day.astype("int64").values))
    return pd.concat(out)


# ---------------------------------------------------------------- 2 Asia false breakout fade (Judas swing)
def asia_fade(b, tgt="opp", trend="none", start=7.0, end=11.0, buf=0.1, hold_h=4):
    w = b[(b.ldn_h >= start) & (b.ldn_h < end)].dropna(subset=["asia_hi"])
    # extreme since London open
    lo_since = w.groupby("day").low.cummin(); hi_since = w.groupby("day").high.cummax()
    out = []
    for side in (1, -1):
        if side == -1:
            m = (w.high > w.asia_hi) & (w.close < w.asia_hi)
            sl = hi_since + buf * w.atr; t_opp = w.asia_lo
        else:
            m = (w.low < w.asia_lo) & (w.close > w.asia_lo)
            sl = lo_since - buf * w.atr; t_opp = w.asia_hi
        m &= trend_ok(w, side, trend)
        rr = w[m]; sl = sl[m]; ref = rr.close; risk = (ref - sl).abs()
        if tgt == "opp":
            tp = t_opp[m]
        else:
            tp = ref + side * float(tgt) * risk
        ok = (risk > 0.3 * rr.atr) & ((tp - ref) * side > 0)
        rr, sl, tp = rr[ok], sl[ok], tp[ok]
        out.append(_mk(rr, side, 0, rr.close, sl, tp, rr.dec, rr.dec + hold_h * H))
    return pd.concat(out)


# ---------------------------------------------------------------- 3 previous-day high/low sweep & reclaim
def pd_sweep(b, R=2.0, trend="none", buf=0.1, hold_h=4):
    kz = ((b.ldn_h >= 7) & (b.ldn_h < 11)) | ((b.ny_h >= 8) & (b.ny_h < 12))
    w = b[kz]
    out = []
    for side in (1, -1):
        if side == -1:
            m = (w.high > w.pdh) & (w.close < w.pdh); sl = w.high + buf * w.atr
        else:
            m = (w.low < w.pdl) & (w.close > w.pdl); sl = w.low - buf * w.atr
        m &= trend_ok(w, side, trend)
        rr = w[m]; sl = sl[m]; risk = (rr.close - sl).abs()
        ok = risk > 0.3 * rr.atr
        rr, sl, risk = rr[ok], sl[ok], risk[ok]
        tp = rr.close + side * R * risk
        out.append(_mk(rr, side, 0, rr.close, sl, tp, rr.dec, rr.dec + hold_h * H))
    return pd.concat(out)


# ---------------------------------------------------------------- 4 NY opening-range breakout
def ny_orb(b, or_start=8.5, or_len=0.5, sl_mode="opp", R=2.0, trend="none", buf=0.05, end=11.0, exit_ny=15.0, min_w=0.0):
    w = b[(b.ny_h >= or_start) & (b.ny_h < or_start + or_len)]
    g = w.groupby("day").agg(orh=("high", "max"), orl=("low", "min"), nb=("open", "size"))
    g = g[g.nb == int(or_len * 4)]
    last = b[b.ny_h == or_start + or_len - 0.25].join(g, on="day", how="inner")
    last = last[(last.orh - last.orl) >= min_w * last.D1_atr]
    out = []
    for side in (1, -1):
        rr = last[trend_ok(last, side, trend)]
        px = rr.orh + buf * rr.atr if side == 1 else rr.orl - buf * rr.atr
        if sl_mode == "opp":
            sl = rr.orl - buf * rr.atr if side == 1 else rr.orh + buf * rr.atr
        else:
            sl = (rr.orh + rr.orl) / 2
        risk = (px - sl).abs()
        tp = px + side * R * risk if R else np.full(len(rr), np.nan)
        out.append(_mk(rr, side, 1, px, sl, tp, at_clock(rr, "ny_h", end), at_clock(rr, "ny_h", exit_ny), oco=rr.day.astype("int64").values))
    return pd.concat(out)


# ---------------------------------------------------------------- 5 trend pullback (RSI2 in HTF trend), stop-entry confirmation
def trend_pullback(b, trend="H1H4", rsi_thr=10, R=2.0, be=0.0, hold_h=8, sess="LNY"):
    s = ((b.ldn_h >= 7) & (b.ny_h < 15)) if sess == "LNY" else (b.ny_h >= 18) | (b.ldn_h < 15)
    w = b[s]
    out = []
    for side in (1, -1):
        m = (w.rsi2 < rsi_thr) if side == 1 else (w.rsi2 > 100 - rsi_thr)
        m &= trend_ok(w, side, trend)
        rr = w[m]
        px = rr.high + 0.05 * rr.atr if side == 1 else rr.low - 0.05 * rr.atr
        swing = b.low.rolling(5).min().reindex(rr.index) if side == 1 else b.high.rolling(5).max().reindex(rr.index)
        sl = swing - side * 0.1 * rr.atr
        risk = (px - sl).abs()
        sl = np.where(risk < 0.5 * rr.atr, px - side * 0.5 * rr.atr, sl)
        risk = (px - sl).__abs__()
        tp = px + side * R * risk
        out.append(_mk(rr, side, 1, px, sl, tp, rr.dec + 0.75 * H, rr.dec + hold_h * H, be_r=be))
    return pd.concat(out)


# ---------------------------------------------------------------- 6 ICT: sweep -> MSS -> FVG retrace (killzones)
def ict_mss_fvg(b, need_sweep=True, entry="fvg", R=2.0, trend="none", look=12):
    kz = ((b.ldn_h >= 7) & (b.ldn_h < 10)) | ((b.ny_h >= 8.5) & (b.ny_h < 11))
    lowN = b.low.rolling(look).min(); highN = b.high.rolling(look).max()
    swept_lo = (lowN < b[["asia_lo", "pdl"]].min(axis=1)) | (lowN <= b.low.rolling(96).min())  # took sell-side liquidity
    swept_hi = (highN > b[["asia_hi", "pdh"]].max(axis=1)) | (highN >= b.high.rolling(96).max())
    fvg_b = b.fvg_bull | b.fvg_bull.shift(1).fillna(False)
    fvg_s = b.fvg_bear | b.fvg_bear.shift(1).fillna(False)
    mss_up = (b.close > b.last_sh) & (b.close.shift() <= b.last_sh.shift())
    mss_dn = (b.close < b.last_sl) & (b.close.shift() >= b.last_sl.shift())
    out = []
    for side in (1, -1):
        if side == 1:
            m = kz & mss_up & fvg_b
            if need_sweep: m &= swept_lo
            rr = b[m & trend_ok(b, 1, trend)]
            fvg_edge = np.where(rr.fvg_bull, b.high.shift(2).reindex(rr.index), b.high.shift(3).reindex(rr.index))
            sl = lowN.reindex(rr.index) - 0.1 * rr.atr
        else:
            m = kz & mss_dn & fvg_s
            if need_sweep: m &= swept_hi
            rr = b[m & trend_ok(b, -1, trend)]
            fvg_edge = np.where(rr.fvg_bear, b.low.shift(2).reindex(rr.index), b.low.shift(3).reindex(rr.index))
            sl = highN.reindex(rr.index) + 0.1 * rr.atr
        if entry == "fvg":
            px = fvg_edge; ot = 2
        else:
            px = rr.close.values; ot = 0
        risk = np.abs(px - sl)
        ok = (risk > 0.3 * rr.atr) & (risk < 6 * rr.atr) & ((px - sl) * side > 0)
        rr, px, sl, risk = rr[ok], np.asarray(px)[ok.values], sl[ok], risk[ok]
        tp = px + side * R * risk
        out.append(_mk(rr, side, ot, px, sl, tp, rr.dec + 1.0 * H, rr.dec + 4 * H))
    return pd.concat(out)


# ---------------------------------------------------------------- 7 mean reversion in non-trending regime
def mean_rev(b, z=2.5, tgt="vwap", regime="notrend", hold_h=2):
    kz = ((b.ldn_h >= 7) & (b.ny_h < 15))
    out = []
    for side in (1, -1):
        m = kz & ((b.bb_z < -z) if side == 1 else (b.bb_z > z))
        if regime == "notrend":
            m &= (b.H1_trend == 0) | (b.H1_trend == side)
        rr = b[m]
        sl = rr.close - side * 1.0 * rr.atr
        tp = rr.vwap if tgt == "vwap" else rr.close + side * 1.0 * rr.atr
        ok = (tp - rr.close) * side > 0.3 * rr.atr
        rr, sl, tp = rr[ok], sl[ok], tp[ok]
        out.append(_mk(rr, side, 0, rr.close, sl, tp, rr.dec, rr.dec + hold_h * H))
    return pd.concat(out)


# ---------------------------------------------------------------- 8 Asia-session drift (time based)
def asia_drift(b, trend="none", exit_ldn=7.0, sl_atr=2.0, start_ny=20.0):
    r = b[b.ny_h == start_ny - 0.25]  # bar closing at start_ny (18:15 = right after reopen; 20:00 = after spread normalises)
    r = r[trend_ok(r, 1, trend)]
    sl = r.close - sl_atr * r.H1_atr
    return _mk(r, 1, 0, r.close, sl, np.full(len(r), np.nan), r.dec, at_clock(r, "ldn_h", exit_ldn + 24 * (r.ldn_h > 12).astype(float)))


# ---------------------------------------------------------------- 9 Wyckoff spring / UTAD
def wyckoff(b, tgt="mid", tv=1.3, rng_atr=6, n=48):
    lo = b.low.shift(1).rolling(n).min(); hi = b.high.shift(1).rolling(n).max()
    box = (hi - lo) < rng_atr * b.atr
    act = (b.ldn_h >= 7) & (b.ny_h < 15)
    out = []
    for side in (1, -1):
        if side == 1:
            m = box & act & (b.low < lo) & (b.close > lo) & (b.tv_rel > tv); sl = b.low - 0.1 * b.atr; opp = hi
        else:
            m = box & act & (b.high > hi) & (b.close < hi) & (b.tv_rel > tv); sl = b.high + 0.1 * b.atr; opp = lo
        rr = b[m]; sl = sl[m]; risk = (rr.close - sl).abs()
        tp = {"mid": (hi + lo)[m] / 2, "opp": opp[m]}.get(tgt, rr.close + side * 2 * risk)
        ok = ((tp - rr.close) * side > 0.5 * risk) & (risk > 0.3 * rr.atr)
        rr, sl, tp = rr[ok], sl[ok], tp[ok]
        out.append(_mk(rr, side, 0, rr.close, sl, tp, rr.dec, rr.dec + 6 * H))
    return pd.concat(out)


# ---------------------------------------------------------------- 10 compression -> expansion (H1 inside bar / NR4 built from M15)
def compression(b, R=2.0, trend="none"):
    h1 = b[["open", "high", "low", "close"]].resample("1h", label="left", closed="left").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    rng = h1.high - h1.low
    nr4 = (rng <= rng.rolling(4).min()) & (h1.high < h1.high.shift()) & (h1.low > h1.low.shift())
    sig_bars = h1[nr4].index + pd.Timedelta(minutes=45)  # last M15 of the H1 bar
    rr = b.loc[b.index.intersection(sig_bars)]
    rr = rr[(rr.ldn_h >= 6.75) & (rr.ny_h < 13)]
    hh = h1.high.reindex(rr.index - pd.Timedelta(minutes=45)).values
    ll = h1.low.reindex(rr.index - pd.Timedelta(minutes=45)).values
    out = []
    for side in (1, -1):
        k = trend_ok(rr, side, trend)
        px = (hh + 0.05 * rr.atr.values) if side == 1 else (ll - 0.05 * rr.atr.values)
        sl = (ll - 0.05 * rr.atr.values) if side == 1 else (hh + 0.05 * rr.atr.values)
        tp = px + side * R * np.abs(px - sl)
        x = rr[k]
        out.append(_mk(x, side, 1, px[k], sl[k], tp[k], x.dec + 2 * H, x.dec + 6 * H, oco=(x.index.astype("int64")).values))
    return pd.concat(out)


# ---------------------------------------------------------------- 11 big-bar momentum continuation
def big_bar(b, k=2.5, R=1.5, mode="cont"):
    big = b.rng > k * b.atr.shift()
    act = (b.ldn_h >= 7) & (b.ny_h < 15)
    out = []
    for side in (1, -1):
        m = big & act & ((b.clv > 0.75) if side == 1 else (b.clv < 0.25))
        rr = b[m]
        d = side if mode == "cont" else -side
        sl = rr.close - d * 0.5 * rr.rng
        tp = rr.close + d * R * 0.5 * rr.rng
        out.append(_mk(rr, d, 0, rr.close, sl, tp, rr.dec, rr.dec + 3 * H))
    return pd.concat(out)


REGISTRY = {
    "ARB": (asia_breakout, dict(sl_mode=["opp", "mid"], R=[1.0, 1.5, 2.0, 3.0], width=["all", "narrow"], trend=["none", "D1"])),
    "AFADE": (asia_fade, dict(tgt=["opp", "1", "1.5", "2"], trend=["none", "D1notagainst"])),
    "PDSWEEP": (pd_sweep, dict(R=[1.0, 1.5, 2.0, 3.0], trend=["none", "D1notagainst"])),
    "NYORB": (ny_orb, dict(or_start=[8.5, 9.5], sl_mode=["opp", "mid"], R=[1.0, 1.5, 2.0, 3.0], trend=["none", "D1"])),
    "NYORB2": (ny_orb, dict(or_start=[8.5], R=[3.0, 4.0, 0], min_w=[0.1, 0.15, 0.2])),
    "TPB": (trend_pullback, dict(trend=["H1H4", "D1H1"], rsi_thr=[5, 10], R=[1.5, 2.0, 3.0], be=[0.0, 1.0])),
    "ICT": (ict_mss_fvg, dict(need_sweep=[True, False], entry=["fvg", "mkt"], R=[1.5, 2.0, 3.0])),
    "MR": (mean_rev, dict(z=[2.0, 2.5], tgt=["vwap", "1atr"], regime=["notrend", "any"])),
    "ADRIFT": (asia_drift, dict(trend=["none", "D1"], exit_ldn=[1.0, 7.0], start_ny=[18.25, 20.0])),
    "WYCK": (wyckoff, dict(tgt=["mid", "opp", "2R"], tv=[1.0, 1.3])),
    "COMP": (compression, dict(R=[1.5, 2.0, 3.0], trend=["none", "D1"])),
    "BIGBAR": (big_bar, dict(k=[2.0, 2.5], mode=["cont", "fade"], R=[1.0, 1.5])),
}
