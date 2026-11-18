"""Data loading + time handling for MT5 XAUUSD exports.

Server time convention (verified in audit.py): broker server clock = New York time + 7h
(i.e. UTC+2 in US winter, UTC+3 during US daylight time). A trading day therefore runs
00:00 -> 24:00 server time = 17:00 -> 17:00 New York, and the daily gold maintenance break
is 00:00-01:00 server.
"""
import os
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
OUT = os.path.join(HERE, "..", "out")
TFS = ["M1", "M5", "M15", "H1", "H4", "D1"]
TF_MIN = {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240, "D1": 1440}


def load_raw(tf):
    df = pd.read_csv(os.path.join(DATA, f"XAUUSD_{tf}.csv"), sep="\t")
    df.columns = [c.strip("<>").lower() for c in df.columns]
    if "time" in df.columns:
        ts = pd.to_datetime(df["date"] + " " + df["time"], format="%Y.%m.%d %H:%M:%S")
    else:
        ts = pd.to_datetime(df["date"], format="%Y.%m.%d")
    df.insert(0, "ts", ts)
    df = df.drop(columns=[c for c in ("date", "time") if c in df.columns])
    return df


def server_to_utc(ts_server):
    """server = NY + 7h  ->  utc = (ts - 7h) localized to NY then converted."""
    s = pd.DatetimeIndex(ts_server) - pd.Timedelta(hours=7)
    ny = s.tz_localize("America/New_York", ambiguous="NaT", nonexistent="shift_forward")
    # ambiguous fall-back hour: fill by +5h/+4h fallback using neighbour offsets
    utc = ny.tz_convert("UTC")
    if utc.isna().any():
        fix = s[utc.isna()].tz_localize("America/New_York", ambiguous=np.zeros(utc.isna().sum(), bool)).tz_convert("UTC")
        utc = utc.to_series().copy()
        utc[utc.isna().values] = fix
        utc = pd.DatetimeIndex(utc)
    return utc


def load(tf, clean=True):
    """Return cleaned frame indexed by server time with utc/beirut/ny/london clocks."""
    df = load_raw(tf)
    if clean:
        df = df.drop_duplicates("ts").sort_values("ts")
        # MT5 D1 history pre-2013 contains small Sunday bars; merge them into Monday
        if tf == "D1":
            df = merge_sunday_daily(df)
        df = df[(df.high >= df[["open", "close"]].max(axis=1)) & (df.low <= df[["open", "close"]].min(axis=1))]
    df = df.set_index("ts")
    return df


def merge_sunday_daily(df):
    df = df.copy()
    sun = df.ts.dt.dayofweek == 6
    if not sun.any():
        return df
    rows = []
    vals = df.to_dict("records")
    i = 0
    while i < len(vals):
        r = vals[i]
        if r["ts"].dayofweek == 6 and i + 1 < len(vals) and (vals[i + 1]["ts"] - r["ts"]).days == 1:
            n = dict(vals[i + 1])
            n["open"] = r["open"]
            n["high"] = max(r["high"], n["high"])
            n["low"] = min(r["low"], n["low"])
            n["tickvol"] = r["tickvol"] + n["tickvol"]
            rows.append(n)
            i += 2
        elif r["ts"].dayofweek == 6:
            i += 1
        else:
            rows.append(r)
            i += 1
    return pd.DataFrame(rows)


def add_clocks(df):
    utc = server_to_utc(df.index)
    df = df.copy()
    df["utc"] = utc
    df["beirut"] = utc.tz_convert("Asia/Beirut")
    df["ny"] = utc.tz_convert("America/New_York")
    df["ldn"] = utc.tz_convert("Europe/London")
    df["day"] = df.index.normalize()  # trading day = server date (17:00 NY -> 17:00 NY)
    return df


def resample(df, rule, origin="start_day"):
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "tickvol": "sum", "spread": "min"}
    r = df[list(agg)].resample(rule, origin=origin, label="left", closed="left").agg(agg)
    return r.dropna(subset=["open"])
