"""Section 3: conditional first-passage event studies on M15.
Question form: "When X happens (known at bar close), what is P(price reaches +a*ATR in the
event's direction before -b*ATR against it, within N minutes)?"  Entry reference = next bar
open (realistic market fill).  Same-bar touches of both levels are counted as LOSSES
(conservative).  Mean return is in ATR units after a cost of 1bp+0.5bp (round trip).
Baseline = same direction, same London/NY clock hour, all bars of that split.
"""
import numpy as np, pandas as pd, os, sys, json
from numba import njit
sys.path.insert(0, os.path.dirname(__file__))
OUT = os.path.join(os.path.dirname(__file__), "..", "out")
b = pd.read_pickle(os.path.join(OUT, "feat_M15.pkl"))
b = b[b.atr > 0]


@njit(cache=True)
def first_pass(o, h, l, c, day, atr, a, bb, N):
    n = len(o)
    up = np.full(n, np.nan); dn = np.full(n, np.nan); fr = np.full(n, np.nan)
    for i in range(n - 1):
        e = o[i + 1]; A = atr[i]
        # long outcome
        res_l = np.nan; res_s = np.nan
        for j in range(i + 1, min(n, i + 1 + N)):
            if day[j] != day[i + 1]:
                break
            if np.isnan(res_l):
                hs = l[j] <= e - bb * A; ht = h[j] >= e + a * A
                if hs:
                    res_l = 0.0
                elif ht:
                    res_l = 1.0
            if np.isnan(res_s):
                hs = h[j] >= e + bb * A; ht = l[j] <= e - a * A
                if hs:
                    res_s = 0.0
                elif ht:
                    res_s = 1.0
        up[i] = res_l; dn[i] = res_s
        jN = min(n - 1, i + N)
        fr[i] = (c[jN] - e) / A
    return up, dn, fr


o, h, l, c = (b[k].values for k in ["open", "high", "low", "close"])
day = b.day.values.astype(np.int64)
res = {}
for (a, bb_, N) in [(1.0, 1.0, 8), (2.0, 1.0, 16)]:
    up, dn, fr = first_pass(o, h, l, c, day, b.atr.values, a, bb_, N)
    res[(a, bb_, N)] = (up, dn, fr)

cost_atr = (1.5e-4 * b.close / b.atr).values  # round-trip cost in ATR units
hourkey = np.floor(b.ldn_h).astype(int).values

# ----- event definitions: (name, mask, direction +1 long / -1 short)
E = {}
first_break_up = (b.close > b.asia_hi) & (b.close.shift() <= b.asia_hi) & (b.ldn_h >= 7) & (b.ldn_h < 11)
first_break_dn = (b.close < b.asia_lo) & (b.close.shift() >= b.asia_lo) & (b.ldn_h >= 7) & (b.ldn_h < 11)
E["London: M15 closes above Asia high -> continue long"] = (first_break_up, 1)
E["London: M15 closes below Asia low -> continue short"] = (first_break_dn, -1)
sweep_hi = (b.high > b.asia_hi) & (b.close < b.asia_hi) & (b.ldn_h >= 7) & (b.ldn_h < 11)
sweep_lo = (b.low < b.asia_lo) & (b.close > b.asia_lo) & (b.ldn_h >= 7) & (b.ldn_h < 11)
E["London: wick above Asia high, close back inside -> short"] = (sweep_hi, -1)
E["London: wick below Asia low, close back inside -> long"] = (sweep_lo, 1)
kz = ((b.ldn_h >= 7) & (b.ldn_h < 11)) | ((b.ny_h >= 8) & (b.ny_h < 12))
E["PDH sweep: high>PDH, close<PDH (London/NY) -> short"] = ((b.high > b.pdh) & (b.close < b.pdh) & kz, -1)
E["PDL sweep: low<PDL, close>PDL (London/NY) -> long"] = ((b.low < b.pdl) & (b.close > b.pdl) & kz, 1)
E["PDH breakout: close>PDH first time -> long"] = ((b.close > b.pdh) & (b.close.shift() <= b.pdh) & kz, 1)
E["PDL breakout: close<PDL first time -> short"] = ((b.close < b.pdl) & (b.close.shift() >= b.pdl) & kz, -1)
big = b.rng > 2.5 * b.atr.shift()
E["Big bull bar (>2.5 ATR, close top 25%) -> continue long"] = (big & (b.clv > 0.75), 1)
E["Big bear bar (>2.5 ATR, close bottom 25%) -> continue short"] = (big & (b.clv < 0.25), -1)
E["Big bull bar -> fade short"] = (big & (b.clv > 0.75), -1)
E["Big bear bar -> fade long"] = (big & (b.clv < 0.25), 1)
up4 = (b.close > b.open).rolling(4).sum() == 4
dn4 = (b.close < b.open).rolling(4).sum() == 4
E["4 consecutive bull bars -> continue long"] = (up4, 1)
E["4 consecutive bear bars -> continue short"] = (dn4, -1)
E["Bollinger z>2.5 -> fade short"] = (b.bb_z > 2.5, -1)
E["Bollinger z<-2.5 -> fade long"] = (b.bb_z < -2.5, 1)
E["RSI2<5 & H1 uptrend -> long (pullback in trend)"] = ((b.rsi2 < 5) & (b.H1_trend == 1), 1)
E["RSI2>95 & H1 downtrend -> short (pullback in trend)"] = ((b.rsi2 > 95) & (b.H1_trend == -1), -1)
E["Price >1.5 ATR(H1) above VWAP -> fade short"] = (((b.close - b.vwap) > 1.5 * b.H1_atr) & kz, -1)
E["Price >1.5 ATR(H1) below VWAP -> fade long"] = (((b.vwap - b.close) > 1.5 * b.H1_atr) & kz, 1)
bear_eng = (b.close < b.open) & (b.open >= b.close.shift()) & (b.close < b.open.shift()) & (b.close.shift() > b.open.shift())
bull_eng = (b.close > b.open) & (b.open <= b.close.shift()) & (b.close > b.open.shift()) & (b.close.shift() < b.open.shift())
E["Bull engulfing at 20-bar low -> long"] = (bull_eng & (b.low.rolling(3).min() <= b.low.rolling(20).min()), 1)
E["Bear engulfing at 20-bar high -> short"] = (bear_eng & (b.high.rolling(3).max() >= b.high.rolling(20).max()), -1)
E["MSS up: close>last swing high after new 20-bar low -> long"] = ((b.close > b.last_sh) & (b.close.shift() <= b.last_sh.shift()) & (b.low.rolling(8).min() <= b.low.rolling(40).min()), 1)
E["MSS down: close<last swing low after new 20-bar high -> short"] = ((b.close < b.last_sl) & (b.close.shift() >= b.last_sl.shift()) & (b.high.rolling(8).max() >= b.high.rolling(40).max()), -1)
E["D1 uptrend, any London/NY bar -> long (drift)"] = ((b.D1_trend == 1) & kz, 1)
E["D1 downtrend, any London/NY bar -> short (drift)"] = ((b.D1_trend == -1) & kz, -1)
E["H4 uptrend & H1 uptrend, London/NY -> long"] = ((b.H4_trend == 1) & (b.H1_trend == 1) & kz, 1)
E["H4 downtrend & H1 downtrend, London/NY -> short"] = ((b.H4_trend == -1) & (b.H1_trend == -1) & kz, -1)
# NY continuation of London move: at NY 08:30, sign of (price - London 07:00 open)
lo7 = b.open.where((b.ldn_h == 7.0)).groupby(b.day).transform("first")
at_ny = (b.ny_h == 8.25)  # bar 08:15-08:30 closes at 08:30 NY
mv = (b.close - lo7) / b.H1_atr
E["NY 08:30: London move > +1 ATR(H1) -> continue long"] = (at_ny & (mv > 1), 1)
E["NY 08:30: London move < -1 ATR(H1) -> continue short"] = (at_ny & (mv < -1), -1)
E["NY 08:30: London move > +1 ATR(H1) -> reverse short"] = (at_ny & (mv > 1), -1)
E["NY 08:30: London move < -1 ATR(H1) -> reverse long"] = (at_ny & (mv < -1), 1)
spring = (b.low < b.low.shift(1).rolling(48).min()) & (b.close > b.low.shift(1).rolling(48).min()) & \
         ((b.high.shift(1).rolling(48).max() - b.low.shift(1).rolling(48).min()) < 6 * b.atr) & (b.tv_rel > 1.3)
utad = (b.high > b.high.shift(1).rolling(48).max()) & (b.close < b.high.shift(1).rolling(48).max()) & \
       ((b.high.shift(1).rolling(48).max() - b.low.shift(1).rolling(48).min()) < 6 * b.atr) & (b.tv_rel > 1.3)
E["Wyckoff spring (12h range<6ATR, sweep low, close inside, tickvol>1.3x) -> long"] = (spring, 1)
E["Wyckoff UTAD (mirror) -> short"] = (utad, -1)
fvgb = b.fvg_bull & (b.close > b.last_sh) & kz
fvgs = b.fvg_bear & (b.close < b.last_sl) & kz
E["Bull FVG + close above swing high (displacement BOS) -> long"] = (fvgb, 1)
E["Bear FVG + close below swing low (displacement BOS) -> short"] = (fvgs, -1)


def stats(mask, d, key):
    up, dn, fr = res[key]
    p = up if d == 1 else dn
    frd = fr * d - cost_atr
    out = {}
    for sp in ["dev", "val", "test"]:
        m = mask.values & (b.split.values == sp) & ~np.isnan(p)
        base_m = (b.split.values == sp) & ~np.isnan(p)
        # baseline matched on London clock hour distribution of the events
        hrs = hourkey[m]
        if m.sum() == 0:
            out[sp] = (0, np.nan, np.nan, np.nan); continue
        bp = pd.Series(p[base_m]).groupby(hourkey[base_m]).mean()
        base = np.nanmean(bp.reindex(hrs).values)
        out[sp] = (int(m.sum()), float(np.mean(p[m])), float(base), float(np.nanmean(frd[m])))
    return out


rows = []
for name, (mask, d) in E.items():
    mask = mask.fillna(False)
    for key in res:
        s = stats(mask, d, key)
        rows.append({"event": name, "target_stop_N": f"+{key[0]}/-{key[1]} ATR, {key[2]*15}min",
                     **{f"{sp}_{k}": v for sp in s for k, v in zip(["n", "p_hit", "p_base", "fwd_ret_atr_net"], s[sp])}})
ev = pd.DataFrame(rows)
for sp in ["dev", "val", "test"]:
    ev[f"{sp}_edge"] = ev[f"{sp}_p_hit"] - ev[f"{sp}_p_base"]
    # binomial z vs baseline
    ev[f"{sp}_z"] = ev[f"{sp}_edge"] / np.sqrt(ev[f"{sp}_p_base"] * (1 - ev[f"{sp}_p_base"]) / ev[f"{sp}_n"])
ev.to_csv(os.path.join(OUT, "event_study.csv"), index=False)
pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 70)
cols = ["event", "target_stop_N", "dev_n", "dev_p_hit", "dev_p_base", "dev_z", "dev_fwd_ret_atr_net", "val_n", "val_p_hit", "val_z", "test_n", "test_p_hit", "test_z"]
print(ev[cols].round(3).to_string())
print("hypotheses tested in event study:", len(ev))

# hour-of-day profile (Beirut clock) : mean return per M15 bar in ATR, by split
b["ret_atr"] = (b.close - b.open) / b.atr.shift()
b["bei_h"] = b.beirut.dt.hour
hod = b.pivot_table(index="bei_h", columns="split", values="ret_atr", aggfunc="mean").round(4)
hod_t = b.groupby(["bei_h", "split"]).ret_atr.agg(lambda x: x.mean() / x.std() * np.sqrt(len(x))).unstack().round(2)
hod.join(hod_t, rsuffix="_t").to_csv(os.path.join(OUT, "hour_of_day_beirut.csv"))
print(hod.join(hod_t, rsuffix="_t").to_string())
