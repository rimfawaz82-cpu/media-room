"""Convert the MT5 raw tick export (XAUUSD_part_XX.zip) into:
  data/ticks.parquet        — every quote state: ts (ms, server time), bid, ask in integer points ($0.01), flags
  data/m1_bidask.parquet    — per-minute Bid OHLC, Ask OHLC, real spread stats, tick counts

MT5 tick rows carry only the side that changed (FLAGS 2 = bid, 4 = ask, 6 = both); the
missing side is the prevailing quote, so each side is forward-filled, carrying state
across part boundaries. Nothing else is filled or invented.

Usage: python src/ticks.py <dir-with-part-zips>
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from load import DATA

TICKS = DATA / "ticks.parquet"
M1BA = DATA / "m1_bidask.parquet"


def read_part(zpath: Path) -> pd.DataFrame:
    with zipfile.ZipFile(zpath) as z:
        name = z.namelist()[0]
        with z.open(name) as f:
            df = pd.read_csv(f, sep="\t", usecols=[0, 1, 2, 3, 6], dtype={0: str, 1: str, 2: float, 3: float, 6: "int16"})
    df.columns = ["date", "time", "bid", "ask", "flags"]
    ts = pd.to_datetime(df["date"] + " " + df["time"], format="%Y.%m.%d %H:%M:%S.%f")
    out = pd.DataFrame({"ts": ts.values.astype("datetime64[ms]"),
                        "bid_raw": df["bid"].values, "ask_raw": df["ask"].values, "flags": df["flags"].values})
    return out


def aggregate_minutes(t: pd.DataFrame) -> pd.DataFrame:
    """t has ts, bid, ask (dollars, forward-filled), has_bid (bid present in this tick row)."""
    minute = t["ts"].dt.floor("min")
    t = t.assign(minute=minute, spread=(t["ask"] - t["bid"]))
    g = t.groupby("minute", sort=True)
    agg = g.agg(ask_o=("ask", "first"), ask_h=("ask", "max"), ask_l=("ask", "min"), ask_c=("ask", "last"),
                spr_open=("spread", "first"), spr_min=("spread", "min"), spr_mean=("spread", "mean"),
                spr_max=("spread", "max"), spr_close=("spread", "last"), ticks_all=("spread", "size"))
    tb = t[t["has_bid"]]
    gb = tb.groupby("minute", sort=True)
    bid = gb.agg(bid_o=("bid", "first"), bid_h=("bid", "max"), bid_l=("bid", "min"), bid_c=("bid", "last"), ticks_bid=("bid", "size"))
    # time-weighted spread inside the minute (each quote state weighted by how long it lasted, capped at minute end)
    nxt = t["ts"].shift(-1)
    end = (t["minute"] + pd.Timedelta(minutes=1))
    dur = (np.minimum(nxt.fillna(end).values.astype("int64"), end.values.astype("int64")) - t["ts"].values.astype("int64")).clip(min=0)
    tw = pd.DataFrame({"minute": t["minute"], "w": dur, "ws": dur * t["spread"].values}).groupby("minute").sum()
    agg["spr_twmean"] = tw["ws"] / tw["w"].replace(0, np.nan)
    out = agg.join(bid, how="left").reset_index().rename(columns={"minute": "ts"})
    return out


def main(src_dir: str) -> None:
    parts = sorted(Path(src_dir).glob("*XAUUSD_part_*.zip"), key=lambda p: p.name.split("part_")[1])
    print("parts:", [p.name for p in parts])
    writer = None
    last_bid = last_ask = np.nan
    pending = None  # ticks of the last (possibly incomplete) minute of the previous part
    minutes = []
    stats = []
    for p in parts:
        df = read_part(p)
        n_raw = len(df)
        df["has_bid"] = df["bid_raw"].notna()
        df["has_ask"] = df["ask_raw"].notna()
        bid = df["bid_raw"].copy()
        ask = df["ask_raw"].copy()
        if np.isfinite(last_bid) and pd.isna(bid.iloc[0]):
            bid.iloc[0] = last_bid
        if np.isfinite(last_ask) and pd.isna(ask.iloc[0]):
            ask.iloc[0] = last_ask
        df["bid"] = bid.ffill()
        df["ask"] = ask.ffill()
        last_bid, last_ask = df["bid"].iloc[-1], df["ask"].iloc[-1]
        stats.append({"part": p.name.split("-", 1)[-1], "rows": n_raw, "first": str(df.ts.iloc[0]), "last": str(df.ts.iloc[-1]),
                      "bid_only": int((df.has_bid & ~df.has_ask).sum()), "ask_only": int((~df.has_bid & df.has_ask).sum()),
                      "both": int((df.has_bid & df.has_ask).sum()), "neither": int((~df.has_bid & ~df.has_ask).sum())})
        valid = df.dropna(subset=["bid", "ask"])
        # ---- tick store (integer points)
        tbl = pa.table({"ts": pa.array(valid["ts"].values.astype("datetime64[ms]")),
                        "bid": pa.array(np.rint(valid["bid"].values * 100).astype("int32")),
                        "ask": pa.array(np.rint(valid["ask"].values * 100).astype("int32")),
                        "flags": pa.array(valid["flags"].values.astype("int8"))})
        if writer is None:
            writer = pq.ParquetWriter(TICKS, tbl.schema, compression="zstd")
        writer.write_table(tbl)
        # ---- minute aggregation; hold back the last minute (it may continue in the next part)
        cur = valid[["ts", "bid", "ask", "has_bid"]]
        if pending is not None:
            cur = pd.concat([pending, cur], ignore_index=True)
        last_min = cur["ts"].iloc[-1].floor("min")
        pending = cur[cur["ts"] >= last_min]
        done = cur[cur["ts"] < last_min]
        if len(done):
            minutes.append(aggregate_minutes(done))
        print(f"{p.name}: {n_raw:,} ticks  {df.ts.iloc[0]} -> {df.ts.iloc[-1]}", flush=True)
    if pending is not None and len(pending):
        minutes.append(aggregate_minutes(pending))
    writer.close()
    m = pd.concat(minutes, ignore_index=True)
    assert m["ts"].is_monotonic_increasing and not m["ts"].duplicated().any()
    m.to_parquet(M1BA, index=False)
    pd.DataFrame(stats).to_csv(Path(__file__).resolve().parents[1] / "reports" / "tables" / "ticks_parts.csv", index=False)
    print(f"minutes: {len(m):,}  {m.ts.min()} -> {m.ts.max()}")


if __name__ == "__main__":
    main(sys.argv[1])
