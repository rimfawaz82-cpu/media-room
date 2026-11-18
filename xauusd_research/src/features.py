"""Feature frame on the signal timeframe. Every column is known at the CLOSE of the bar
(decision time = bar open + bar length). Higher-timeframe values come from the last CLOSED
HTF bar only (merge_asof on availability time). Swing points are only usable after their
confirmation bar."""
import numpy as np, pandas as pd, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from data import load, add_clocks, TF_MIN

END = pd.Timestamp("2026-11-18")  # drop today's incomplete session


def ema(x, n):
    return x.ewm(span=n, adjust=False).mean()


def atr(df, n=14):
    pc = df.close.shift()
    tr = np.maximum(df.high - df.low, np.maximum((df.high - pc).abs(), (df.low - pc).abs()))
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def rsi(x, n):
    d = x.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def htf_frame(tf):
    h = load(tf)
    h = h[h.index < END]
    f = pd.DataFrame(index=h.index)
    f[f"{tf}_close"] = h.close
    f[f"{tf}_ema20"] = ema(h.close, 20)
    f[f"{tf}_ema50"] = ema(h.close, 50)
    f[f"{tf}_ema200"] = ema(h.close, 200)
    f[f"{tf}_atr"] = atr(h)
    f[f"{tf}_slope50"] = f[f"{tf}_ema50"].diff(3) / f[f"{tf}_atr"]
    f[f"{tf}_trend"] = np.sign(h.close - f[f"{tf}_ema50"]) * (np.sign(f[f"{tf}_slope50"]) == np.sign(h.close - f[f"{tf}_ema50"]))
    f[f"{tf}_rsi14"] = rsi(h.close, 14)
    dur = pd.Timedelta(minutes=TF_MIN[tf]) if tf != "D1" else pd.Timedelta(days=1)
    f["avail"] = f.index + dur
    return f


def build(tf="M15"):
    b = load(tf)
    b = b[b.index < END]
    b = add_clocks(b)
    m = TF_MIN[tf]
    b["dec"] = b.index + pd.Timedelta(minutes=m)  # decision time (bar close), server clock
    b["atr"] = atr(b)
    b["atr_pct"] = b.atr.rolling(96 * 20 // (m // 15 if m >= 15 else 1), min_periods=200).rank(pct=True)
    b["ema20"] = ema(b.close, 20); b["ema50"] = ema(b.close, 50)
    b["rsi2"] = rsi(b.close, 2); b["rsi14"] = rsi(b.close, 14)
    sd = b.close.rolling(20).std()
    b["bb_z"] = (b.close - b.close.rolling(20).mean()) / sd
    b["rng"] = b.high - b.low
    b["body"] = (b.close - b.open)
    b["clv"] = (b.close - b.low) / b.rng.replace(0, np.nan)  # 0 = close at low, 1 = at high
    b["tv_rel"] = b.tickvol / b.tickvol.rolling(96 // max(1, m // 15) * 5, min_periods=20).median()
    # local clocks (DST aware)
    b["ldn_h"] = b.ldn.dt.hour + b.ldn.dt.minute / 60
    b["ny_h"] = b.ny.dt.hour + b.ny.dt.minute / 60
    b["dow"] = b.day.dt.dayofweek
    # ---- daily (trading-day = server date) levels from the same series
    g = b.groupby("day")
    dd = pd.DataFrame({"dh": g.high.max(), "dl": g.low.min(), "do": g.open.first(), "dc": g.close.last()})
    dd["pdh"], dd["pdl"], dd["pdc"] = dd.dh.shift(), dd.dl.shift(), dd.dc.shift()
    dd["pdr"] = dd.pdh - dd.pdl
    b = b.join(dd[["pdh", "pdl", "pdc", "pdr", "do"]], on="day")
    # running intraday high/low up to and including this bar
    b["day_hi"] = g.high.cummax(); b["day_lo"] = g.low.cummin()
    # Asia range: from day open (18:00 NY) to 07:00 London local
    asia = (b.ny_h >= 18) | (b.ldn_h < 7.0)
    ah = b.high.where(asia).groupby(b.day).cummax()
    al = b.low.where(asia).groupby(b.day).cummin()
    fin = b[asia].groupby("day").agg(asia_hi=("high", "max"), asia_lo=("low", "min"))
    b = b.join(fin, on="day")
    # final only at the close of the last Asia bar (the bar ending at London 07:00)
    b.loc[asia & ~((b.ldn_h >= 6.75) & (b.ldn_h < 7.0)), ["asia_hi", "asia_lo"]] = np.nan
    b["asia_w"] = b.asia_hi - b.asia_lo
    # VWAP-like intraday anchor (tick-volume weighted typical price; tick volume = activity proxy)
    tp = (b.high + b.low + b.close) / 3
    b["vwap"] = (tp * b.tickvol).groupby(b.day).cumsum() / b.tickvol.groupby(b.day).cumsum()
    # fractal swings (2 left / 2 right) -> known only 2 bars after the pivot
    hi, lo = b.high.values, b.low.values
    n = len(b)
    sh = np.full(n, np.nan); sl_ = np.full(n, np.nan)
    for i in range(2, n - 2):
        if hi[i] > max(hi[i - 1], hi[i - 2]) and hi[i] >= max(hi[i + 1], hi[i + 2]):
            sh[i + 2] = hi[i]
        if lo[i] < min(lo[i - 1], lo[i - 2]) and lo[i] <= min(lo[i + 1], lo[i + 2]):
            sl_[i + 2] = lo[i]
    b["last_sh"] = pd.Series(sh, index=b.index).ffill()
    b["last_sl"] = pd.Series(sl_, index=b.index).ffill()
    # FVG at bar i (3-bar pattern i-2,i-1,i) known at close of i
    b["fvg_bull"] = b.low > b.high.shift(2)
    b["fvg_bear"] = b.high < b.low.shift(2)
    # ---- HTF context (closed bars only)
    for tf2 in ["H1", "H4", "D1"]:
        f = htf_frame(tf2).reset_index(drop=True).sort_values("avail")
        b = pd.merge_asof(b.reset_index().sort_values("dec"), f, left_on="dec", right_on="avail", direction="backward").set_index("ts")
        b = b.drop(columns="avail")
    b["split"] = np.where(b.index < "2025-01-01", "dev", np.where(b.index < "2026-01-01", "val", "test"))
    return b


if __name__ == "__main__":
    import time
    t0 = time.time()
    for tf in ["M15", "M5"]:
        b = build(tf)
        b.to_pickle(os.path.join(os.path.dirname(__file__), "..", "out", f"feat_{tf}.pkl"))
        print(tf, b.shape, b.index[0], b.index[-1], time.time() - t0)
    print(b[["ldn_h", "ny_h", "asia_hi", "asia_lo", "pdh", "H1_trend", "D1_trend"]].dropna().head(3))
