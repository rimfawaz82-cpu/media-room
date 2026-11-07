"""Phase 4A — multi-day (swing) trend systems on daily bars, 2020-01 → 2025-06 (holdout excluded).

Daily series = file D1 bars (2020-01 → 2021-11) + daily bars aggregated from the H1 (→ 2022-03) and M1 segments.
Server day boundary = 17:00 New York, the same convention throughout.

Execution model (conservative)
* Signals use the completed daily close; orders execute at the NEXT day's open (the 01:00 reopen) with
  entry/exit cost = $0.20 spread + $0.30 slippage per side (the reopen spread is wide, Phase 1b).
* Protective stops are checked on daily high/low; a gap through the stop fills at the open; stop exits pay $0.30 slippage.
* Overnight financing (swap) is unknown for this broker: scenarios W0 = 0, W1 = 4 %/yr, W2 = 8 %/yr of notional,
  charged on BOTH long and short positions per calendar night held.
* Size: 1 oz per position (unlevered). Returns are reported as % of the average gold price, so the result
  is comparable to buy-and-hold.

Parameter values are classic textbook defaults, fixed in advance; nothing is optimised.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from audit import md_table
from load import RAW_PARQUET, ROOT

TAB = ROOT / "reports" / "tables"
COST_SIDE = 0.50          # spread 0.20 + slippage 0.30 at the open
STOP_SLIP = 0.30
SWAP = {"W0": 0.0, "W1": 0.04, "W2": 0.08}
END = "2025-06-30"        # holdout starts 2025-07-01


def daily_series() -> pd.DataFrame:
    raw = pd.read_parquet(RAW_PARQUET)
    raw = raw[raw.ts <= pd.Timestamp(END) + pd.Timedelta(hours=23, minutes=59)]
    raw["day"] = raw.ts.dt.normalize()
    d = raw.groupby("day").agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
                               src=("resolution", "first")).reset_index()
    pc = d.close.shift()
    tr = np.maximum(d.high - d.low, np.maximum((d.high - pc).abs(), (d.low - pc).abs()))
    d["atr20"] = tr.ewm(alpha=1 / 20, adjust=False, min_periods=20).mean()
    return d


# ----------------------------------------------------------------------------- signal generators (all use data up to and including day t)
def sig_donchian(d, N, long_only):
    hi = d.high.rolling(N).max().shift()
    lo = d.low.rolling(N).min().shift()
    xhi = d.high.rolling(N // 2).max().shift()
    xlo = d.low.rolling(N // 2).min().shift()
    pos, out, stops = 0, [], []
    for i in range(len(d)):
        c = d.close.iat[i]
        if pos > 0 and c < xlo.iat[i]:
            pos = 0
        elif pos < 0 and c > xhi.iat[i]:
            pos = 0
        if pos == 0:
            if c > hi.iat[i]:
                pos = 1
            elif c < lo.iat[i] and not long_only:
                pos = -1
        out.append(pos)
    return pd.Series(out, index=d.index), 2.0           # target position, initial stop in ATRs


def sig_ema(d, f, s, long_only):
    ef, es = d.close.ewm(span=f, adjust=False).mean(), d.close.ewm(span=s, adjust=False).mean()
    p = np.where(ef > es, 1, -1)
    if long_only:
        p = np.where(p > 0, 1, 0)
    p = pd.Series(p, index=d.index)
    p[es.index < s] = 0
    return p, 3.0                                          # chandelier-style 3 ATR stop


def sig_tsmom(d, L, long_only):
    mom = np.sign(d.close - d.close.shift(L))
    week = d.day.dt.isocalendar().week.astype(int) + 100 * d.day.dt.year
    last_of_week = week != week.shift(-1)                  # decide on the last trading day of the week
    p = pd.Series(np.nan, index=d.index)
    p[last_of_week] = mom[last_of_week]
    p = p.ffill().fillna(0)
    if long_only:
        p = p.clip(lower=0)
    return p, np.nan                                       # no stop


def sig_buyhold(d):
    return pd.Series(1, index=d.index), np.nan


# ----------------------------------------------------------------------------- daily simulator
def simulate_daily(d: pd.DataFrame, target: pd.Series, stop_atr: float, swap_rate: float, start: str):
    """target[t] = desired position decided at the close of day t, executed at the open of t+1."""
    d = d.reset_index(drop=True)
    target = target.reset_index(drop=True)
    pos, entry, stop, entry_day, peak = 0, np.nan, np.nan, None, np.nan
    blocked = 0                                            # after a stop-out, wait until target changes
    pnl = np.zeros(len(d))
    trades = []
    i0 = int(np.searchsorted(d.day.values, np.datetime64(start)))
    for t in range(max(i0, 1), len(d)):
        o, h, l, c, pc = d.open.iat[t], d.high.iat[t], d.low.iat[t], d.close.iat[t], d.close.iat[t - 1]
        want = int(target.iat[t - 1]) if np.isfinite(target.iat[t - 1]) else 0
        if blocked and want != blocked:
            blocked = 0
        if blocked:
            want = 0
        day_pnl = 0.0
        # 1) execute at the open
        if want != pos:
            if pos != 0:                                   # close existing
                fill = o - pos * COST_SIDE
                day_pnl += pos * (fill - pc)
                trades.append({"entry_day": entry_day, "exit_day": d.day.iat[t], "side": pos, "entry": entry, "exit": fill, "reason": "signal",
                               "risk": stop_atr * d.atr20.iat[t - 1] if np.isfinite(stop_atr) else 2 * d.atr20.iat[t - 1]})
                pos = 0
            if want != 0:
                pos, entry, entry_day = want, o + want * COST_SIDE, d.day.iat[t]
                a = d.atr20.iat[t - 1]
                stop = entry - pos * stop_atr * a if np.isfinite(stop_atr) else np.nan
                peak = entry
                day_ref = entry
            else:
                day_ref = None
        else:
            day_ref = pc if pos != 0 else None
        # 2) intraday stop
        if pos != 0 and np.isfinite(stop) and ((pos > 0 and l <= stop) or (pos < 0 and h >= stop)):
            fill = (min(stop, o) if pos > 0 else max(stop, o)) - pos * STOP_SLIP
            day_pnl += pos * (fill - day_ref)
            trades.append({"entry_day": entry_day, "exit_day": d.day.iat[t], "side": pos, "entry": entry, "exit": fill, "reason": "stop",
                           "risk": abs(entry - stop)})
            blocked, pos = pos, 0
        elif pos != 0:
            day_pnl += pos * (c - day_ref)
            # trail the stop (chandelier / ATR trail) on the close
            if np.isfinite(stop):
                peak = max(peak, c) if pos > 0 else min(peak, c)
                trail = peak - pos * stop_atr * d.atr20.iat[t]
                stop = max(stop, trail) if pos > 0 else min(stop, trail)
            # 3) financing for the nights until the next trading day
            if t + 1 < len(d):
                nights = (d.day.iat[t + 1] - d.day.iat[t]).days
                day_pnl -= abs(pos) * c * swap_rate * nights / 365
        pnl[t] = day_pnl
    if pos != 0:
        trades.append({"entry_day": entry_day, "exit_day": d.day.iat[-1], "side": pos, "entry": entry, "exit": d.close.iat[-1], "reason": "open_at_end",
                       "risk": abs(entry - stop) if np.isfinite(stop) else 2 * d.atr20.iat[-1]})
    ser = pd.Series(pnl, index=d.day)
    return ser[ser.index >= pd.Timestamp(start)], pd.DataFrame(trades)


def metrics(pnl: pd.Series, trades: pd.DataFrame, price_ref: float) -> dict:
    r = pnl / price_ref                                    # daily return on 1x notional at average price
    eq = r.cumsum()
    dd = (eq.cummax() - eq).max()
    yrs = (pnl.index[-1] - pnl.index[0]).days / 365.25
    tr = trades.copy()
    if len(tr):
        tr["pnl"] = tr.side * (tr.exit - tr.entry)
        tr["R"] = tr.pnl / tr.risk
    by_year = r.groupby(r.index.year).sum()
    return {"total_return_%": eq.iloc[-1] * 100, "annual_return_%": eq.iloc[-1] / yrs * 100, "annual_vol_%": r.std() * np.sqrt(252) * 100,
            "sharpe": r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else np.nan, "maxDD_%": dd * 100,
            "calmar": (eq.iloc[-1] / yrs) / dd if dd > 0 else np.nan, "trades": len(tr), "win_rate": (tr.pnl > 0).mean() if len(tr) else np.nan,
            "avg_R": tr.R.mean() if len(tr) else np.nan, "long_pnl_$": tr[tr.side > 0].pnl.sum() if len(tr) else 0,
            "short_pnl_$": tr[tr.side < 0].pnl.sum() if len(tr) else 0, "exposure_%": (pnl != 0).mean() * 100,
            "years_negative": int((by_year < 0).sum()), "by_year_%": {int(k): round(v * 100, 1) for k, v in by_year.items()}}


SYSTEMS = {
    "S1_donchian20_LS": lambda d: sig_donchian(d, 20, False),
    "S1_donchian20_LO": lambda d: sig_donchian(d, 20, True),
    "S1_donchian55_LS": lambda d: sig_donchian(d, 55, False),
    "S1_donchian55_LO": lambda d: sig_donchian(d, 55, True),
    "S2_ema20_50_LS": lambda d: sig_ema(d, 20, 50, False),
    "S2_ema20_50_LO": lambda d: sig_ema(d, 20, 50, True),
    "S2_ema50_200_LS": lambda d: sig_ema(d, 50, 200, False),
    "S2_ema50_200_LO": lambda d: sig_ema(d, 50, 200, True),
    "S3_tsmom20_LS": lambda d: sig_tsmom(d, 20, False),
    "S3_tsmom20_LO": lambda d: sig_tsmom(d, 20, True),
    "S3_tsmom60_LS": lambda d: sig_tsmom(d, 60, False),
    "S3_tsmom60_LO": lambda d: sig_tsmom(d, 60, True),
    "B0_buy_and_hold": lambda d: sig_buyhold(d),
}
START = "2020-12-01"   # warm-up: the slowest indicator (EMA200) needs ~11 months of daily data


def main():
    d = daily_series()
    price_ref = d[d.day >= START].close.mean()
    rows, years, all_trades = [], [], []
    for name, fn in SYSTEMS.items():
        target, stop_atr = fn(d)
        for w, rate in SWAP.items():
            pnl, tr = simulate_daily(d, target, stop_atr, rate, START)
            mt = metrics(pnl, tr, price_ref)
            rows.append({"system": name, "swap": w, **{k: v for k, v in mt.items() if k != "by_year_%"}})
            if w == "W1":
                years.append({"system": name, **{str(k): v for k, v in mt["by_year_%"].items()}})
                all_trades.append(tr.assign(system=name))
    S = pd.DataFrame(rows)
    Y = pd.DataFrame(years)
    S.to_csv(TAB / "p4_swing_summary.csv", index=False)
    Y.to_csv(TAB / "p4_swing_by_year.csv", index=False)
    pd.concat(all_trades).to_csv(TAB / "p4_swing_trades.csv", index=False)
    # daily target positions for the hybrid intraday models (decided at close t, valid for day t+1)
    st = {}
    for name in ["S1_donchian20_LS", "S2_ema20_50_LS", "S3_tsmom20_LS"]:
        tg, _ = SYSTEMS[name](d)
        st[name] = pd.Series(tg.values, index=d.day).shift(1)       # effective on day t (decided at t-1 close)
    pd.DataFrame(st).to_csv(TAB / "p4_swing_state_by_day.csv")
    json.dump({"price_ref": price_ref, "start": START, "end": END, "days": int((d.day >= START).sum()),
               "segments": d.groupby("src").day.agg(["min", "max", "size"]).astype(str).to_dict()}, open(ROOT / "reports" / "p4_swing_meta.json", "w"), indent=1)
    pd.set_option("display.width", 250)
    print(S[S.swap == "W1"].round(3).to_string())
    print(Y.round(1).to_string())


if __name__ == "__main__":
    main()
