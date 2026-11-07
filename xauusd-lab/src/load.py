"""XAE research lab — raw data loader.

Reads the MetaTrader 5 export (tab-separated, <DATE> <TIME> <OPEN> ... <SPREAD>),
splits it into its resolution segments, and caches the clean M1 segment as parquet.

Nothing is interpolated or invented: missing minutes stay missing.

Usage:
    python -I src/load.py <path-to-XAUUSD.c_M1.csv>
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
M1_PARQUET = DATA / "xauusd_m1.parquet"
RAW_PARQUET = DATA / "xauusd_raw.parquet"

# Contract constants observed in the file (prices quoted with 2 decimals).
POINT = 0.01  # 1 MT5 point = $0.01 of price; SPREAD column is in points.


def read_raw(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep="\t")
    df.columns = [c.strip("<>").lower() for c in df.columns]
    df["ts"] = pd.to_datetime(df["date"] + " " + df["time"], format="%Y.%m.%d %H:%M:%S")
    df = df.drop(columns=["date", "time"]).rename(columns={"tickvol": "tick_volume", "vol": "real_volume"})
    return df[["ts", "open", "high", "low", "close", "tick_volume", "real_volume", "spread"]]


def classify_segments(df: pd.DataFrame) -> pd.Series:
    """Label each row with its bar resolution, inferred from bars-per-day and timestamps."""
    day = df["ts"].dt.normalize()
    n_per_day = df.groupby(day)["ts"].transform("size")
    minute_nonzero = df.groupby(day)["ts"].transform(lambda s: (s.dt.minute != 0).any())
    res = pd.Series(np.where(minute_nonzero | (n_per_day > 30), "M1", np.where(n_per_day == 1, "D1", "H1")),
                    index=df.index, name="resolution")
    # The first "M1" day (2022-03-15) still starts with hourly bars until 15:00; true M1 starts at the
    # first bar whose successor is exactly one minute later. Everything before that is H1.
    nxt = df["ts"].shift(-1) - df["ts"]
    m1_start = df.loc[(res == "M1") & (nxt == pd.Timedelta(minutes=1)), "ts"].min()
    res[(res == "M1") & (df["ts"] < m1_start)] = "H1"
    return res


def build(path: str | Path) -> pd.DataFrame:
    DATA.mkdir(exist_ok=True)
    raw = read_raw(path)
    raw["resolution"] = classify_segments(raw)
    raw.to_parquet(RAW_PARQUET, index=False)
    m1 = raw[raw["resolution"] == "M1"].drop(columns="resolution").reset_index(drop=True)
    m1.to_parquet(M1_PARQUET, index=False)
    return m1


def load_m1() -> pd.DataFrame:
    return pd.read_parquet(M1_PARQUET)


if __name__ == "__main__":
    m1 = build(sys.argv[1])
    print(f"M1 rows: {len(m1):,}  {m1.ts.min()} -> {m1.ts.max()}")
