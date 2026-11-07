"""Shared, look-ahead-safe building blocks: data splits, session clock, higher-timeframe bars, ATR.

Conventions
* Server time = New York + 7 h all year (verified in Phase 1). Trading day = server calendar date
  (00:00 server = 17:00 NY = daily halt).
* A higher-timeframe bar labelled T covers [T, T+tf). It becomes KNOWN only at T+tf
  (column `avail`). Any join from M1 to a higher timeframe must use `avail <= decision time`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from load import load_m1

SPLITS = {
    "dev": ("2022-03-16", "2024-06-30"),
    "val": ("2024-07-02", "2025-06-30"),        # 1-day embargo after dev
    "holdout": ("2025-07-02", "2026-12-31"),    # 1-day embargo after val — DO NOT USE until the end
}


def split_of(ts: pd.Series) -> pd.Series:
    d = ts.dt.normalize()
    out = pd.Series("embargo", index=ts.index)
    for k, (a, b) in SPLITS.items():
        out[(d >= a) & (d <= b)] = k
    return out


def add_clock(m: pd.DataFrame) -> pd.DataFrame:
    """Adds NY / London local time and session labels (DST-correct)."""
    ny_naive = m["ts"] - pd.Timedelta(hours=7)
    ny = ny_naive.dt.tz_localize("America/New_York", ambiguous="NaT", nonexistent="shift_forward")
    ldn = ny.dt.tz_convert("Europe/London")
    m["ny_hour"] = ny_naive.dt.hour
    m["ny_min"] = ny_naive.dt.hour * 60 + ny_naive.dt.minute
    m["ldn_min"] = ldn.dt.hour * 60 + ldn.dt.minute
    m["srv_hour"] = m["ts"].dt.hour
    m["day"] = m["ts"].dt.normalize()            # trading day (server date)
    m["dow"] = m["ts"].dt.dayofweek
    nm, lm = m["ny_min"], m["ldn_min"]
    # Sessions (local clock of each centre)
    asia = (nm >= 19 * 60) | (nm < 2 * 60)                       # 19:00-02:00 NY  (Tokyo/Singapore core)
    london = (lm >= 8 * 60) & (lm < 16 * 60 + 30)               # 08:00-16:30 London
    newyork = (nm >= 8 * 60) & (nm < 17 * 60)                   # 08:00-17:00 NY
    sess = np.select([london & newyork, london, newyork, asia], ["LDN-NY overlap", "London", "New York", "Asia"], "Off-hours")
    m["session"] = sess
    return m


def load_research(splits=("dev", "val")) -> pd.DataFrame:
    m = load_m1()
    m["split"] = split_of(m["ts"])
    m = m[m["split"].isin(splits)].reset_index(drop=True)
    return add_clock(m)


def resample(m: pd.DataFrame, rule: str) -> pd.DataFrame:
    """OHLC bars from M1; bars never span the daily halt because server day boundary = halt."""
    g = m.set_index("ts").groupby(pd.Grouper(freq=rule, label="left", closed="left"))
    b = g.agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
              tick_volume=("tick_volume", "sum"), n=("open", "size"), last_ts=("open", lambda s: s.index.max() if len(s) else pd.NaT))
    b = b[b["n"] > 0].reset_index()
    b["avail"] = b["ts"] + pd.tseries.frequencies.to_offset(rule)   # known from this time on
    if rule.upper() in ("1D", "D"):
        b["avail"] = b["last_ts"] + pd.Timedelta(minutes=1)
    return b


def atr(b: pd.DataFrame, n: int = 14) -> pd.Series:
    """Wilder-style ATR using only completed bars (value at row i uses bars <= i)."""
    pc = b["close"].shift()
    tr = np.maximum(b["high"] - b["low"], np.maximum((b["high"] - pc).abs(), (b["low"] - pc).abs()))
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
