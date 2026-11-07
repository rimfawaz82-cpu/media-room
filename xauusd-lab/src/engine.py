"""Bar-level (M1) execution simulator with Bid/Ask, spread, slippage and conservative fill rules.

Price model
* M1 Bid OHLC from the file. Ask = Bid + spread, spread = max(file SPREAD, 10 pts)/100 (the minute's
  MINIMUM spread, Phase 1b) + measured median markup for that server hour (ba_spread_markup_by_hour.csv).
* Longs buy at Ask and sell at Bid; shorts sell at Bid and buy back at Ask.

Fill rules (conservative)
* market : at the open of the first bar after the signal bar, + slippage.
* stop   : first bar whose Ask-high (buy) / Bid-low (sell) reaches the price; fill = worse of (price, bar open) + slippage.
* limit  : needs a trade-through of 1 point; fill = better of (price, bar open); no slippage.
* SL     : stop order; fill = worse of (SL, bar open) - slippage (gaps fill at the open).
* TP     : limit order; needs a 1-point trade-through; fills at the TP price.
* SL and TP in the same bar -> SL. In the entry bar of a stop/limit order only the SL can be hit.
* Time exit at the open of a given bar (market, + slippage). Positions never cross the daily halt:
  forced exit at 23:50 server or the day's last bar.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from load import ROOT

COSTS = {
    "C0": {"spr_mult": 1.0, "slip": 0.00},
    "C1": {"spr_mult": 1.0, "slip": 0.10},
    "C2": {"spr_mult": 2.0, "slip": 0.30},
    "C1_CFI": {"spr_mult": 1.0, "slip": 0.10, "spr_add": 0.07},   # live account XAUUSD_ on CFI: ~$0.17 spread seen vs $0.10 in the data
    "C2_CFI": {"spr_mult": 2.0, "slip": 0.30, "spr_add": 0.07},
}
TT = 0.01  # 1-point trade-through for limit orders / TP


@dataclass
class Order:
    side: int              # +1 long, -1 short
    etype: str             # market | stop | limit
    i0: int                # first bar index on which the order may fill
    i_exp: int             # last bar index on which it may fill
    sl: float
    price: float = np.nan  # for stop/limit
    tp: float = np.nan     # absolute TP, or
    tp_R: float = np.nan   # TP as a multiple of realised risk
    i_exit: int = -1       # time exit at the open of this bar (-1: day end)
    tag: str = ""


class Market:
    def __init__(self, m: pd.DataFrame):
        self.m = m.reset_index(drop=True)
        mk = pd.read_csv(ROOT / "reports" / "tables" / "ba_spread_markup_by_hour.csv").set_index("hour").markup_tw_median
        hr = self.m.ts.dt.hour
        base = np.maximum(self.m.spread.values, 10) / 100.0
        self.spr0 = base + hr.map(mk).fillna(mk.max()).values
        self.o, self.h, self.l, self.c = (self.m[k].values for k in ["open", "high", "low", "close"])
        self.ts = self.m.ts.values
        day = self.m.ts.dt.normalize().values
        # last tradable bar of each day: min(last bar, last bar before 23:50)
        mins = (self.m.ts.dt.hour * 60 + self.m.ts.dt.minute).values
        idx = np.arange(len(self.m))
        last = pd.Series(idx).groupby(day).transform("max").values
        cut = pd.Series(np.where(mins < 23 * 60 + 50, idx, -1)).groupby(day).transform("max").values
        self.day_end = np.where(cut >= 0, cut, last)
        self.n = len(self.m)

    def idx_at(self, t) -> int:
        """First bar index with ts >= t."""
        return int(np.searchsorted(self.ts, np.datetime64(t), side="left"))


def simulate(mkt: Market, o: Order, cost: str = "C1") -> dict | None:
    c = COSTS[cost]
    spr = mkt.spr0 * c["spr_mult"] + c.get("spr_add", 0.0)
    slip = c["slip"]
    s = o.side
    if o.i0 >= mkt.n:
        return None
    dend = mkt.day_end[o.i0]
    i_exp = min(o.i_exp, dend)
    if i_exp < o.i0:
        return None
    a = slice(o.i0, i_exp + 1)
    ask_o, ask_h, ask_l = mkt.o[a] + spr[a], mkt.h[a] + spr[a], mkt.l[a] + spr[a]
    bid_o, bid_h, bid_l = mkt.o[a], mkt.h[a], mkt.l[a]
    # ---------------- entry
    if o.etype == "market":
        j = 0
        fill = (ask_o[0] + slip) if s > 0 else (bid_o[0] - slip)
    elif o.etype == "stop":
        hit = (ask_h >= o.price) if s > 0 else (bid_l <= o.price)
        if not hit.any():
            return None
        j = int(hit.argmax())
        fill = (max(o.price, ask_o[j]) + slip) if s > 0 else (min(o.price, bid_o[j]) - slip)
    elif o.etype == "limit":
        hit = (ask_l <= o.price - TT) if s > 0 else (bid_h >= o.price + TT)
        if not hit.any():
            return None
        j = int(hit.argmax())
        fill = min(o.price, ask_o[j]) if s > 0 else max(o.price, bid_o[j])
    else:
        raise ValueError(o.etype)
    ie = o.i0 + j
    risk = s * (fill - o.sl)
    if risk <= 0.01:
        return {"status": "invalid_risk", "i_entry": ie}
    tp = o.tp if np.isfinite(o.tp) else (fill + s * o.tp_R * risk if np.isfinite(o.tp_R) else np.nan)
    # ---------------- exit
    i_exit = dend if o.i_exit < 0 else min(o.i_exit, dend)
    if i_exit <= ie:
        i_exit = min(ie + 1, dend)
    b = slice(ie, i_exit + 1)
    sp = spr[b]
    if s > 0:
        sl_hit = mkt.l[b] <= o.sl
        tp_hit = (mkt.h[b] >= tp + TT) if np.isfinite(tp) else np.zeros_like(sl_hit)
    else:
        sl_hit = (mkt.h[b] + sp) >= o.sl
        tp_hit = ((mkt.l[b] + sp) <= tp - TT) if np.isfinite(tp) else np.zeros_like(sl_hit)
    if o.etype != "market":
        tp_hit = tp_hit.copy()
        tp_hit[0] = False
    # the time-exit bar itself is not scanned for SL/TP (we exit at its open)
    nb = i_exit - ie
    sl_hit, tp_hit = sl_hit[:max(nb, 1)], tp_hit[:max(nb, 1)]
    any_hit = sl_hit | tp_hit
    amb = False
    if any_hit.any():
        k = int(any_hit.argmax())
        ik = ie + k
        if sl_hit[k]:
            amb = bool(tp_hit[k])
            if s > 0:
                px = (o.sl if k == 0 else min(o.sl, mkt.o[ik])) - slip
            else:
                px = (o.sl if k == 0 else max(o.sl, mkt.o[ik] + spr[ik])) + slip
            reason = "SL"
        else:
            px, reason = tp, "TP"
        ix = ik
    else:
        ix = i_exit
        if i_exit == dend and (o.i_exit < 0 or o.i_exit >= dend):
            px = (mkt.c[ix] - slip) if s > 0 else (mkt.c[ix] + spr[ix] + slip)   # flat at the close of the last bar
        else:
            px = (mkt.o[ix] - slip) if s > 0 else (mkt.o[ix] + spr[ix] + slip)
        reason = "TIME"
    pnl = s * (px - fill)
    return {"status": "filled", "side": s, "i_entry": ie, "i_exit": ix, "t_entry": mkt.ts[ie], "t_exit": mkt.ts[ix],
            "entry": fill, "exit": px, "sl": o.sl, "tp": tp, "risk": risk, "pnl": pnl, "R": pnl / risk, "reason": reason,
            "ambiguous": amb, "minutes": (ix - ie), "tag": o.tag}


def stats(tr: pd.DataFrame, days: int) -> dict:
    if tr is None or len(tr) == 0:
        return {"n": 0}
    R = tr.R.values
    eq = np.cumsum(R)
    dd = (np.maximum.accumulate(np.r_[0, eq])[1:] - eq).max()
    wins, losses = R[R > 0], R[R <= 0]
    streak = max((len(list(g)) for k, g in __import__("itertools").groupby(R <= 0) if k), default=0)
    return {"n": len(R), "trades_per_day": len(R) / days, "win_rate": (R > 0).mean(), "avg_R": R.mean(),
            "t_stat": R.mean() / (R.std(ddof=1) / np.sqrt(len(R))) if len(R) > 2 else np.nan,
            "PF": wins.sum() / -losses.sum() if losses.sum() < 0 else np.inf, "total_R": R.sum(), "maxDD_R": dd,
            "avg_win_R": wins.mean() if len(wins) else 0, "avg_loss_R": losses.mean() if len(losses) else 0,
            "longest_losing_streak": streak, "avg_pnl_$": tr.pnl.mean(), "median_minutes": float(np.median(tr.minutes)),
            "ambiguous_share": tr.ambiguous.mean()}
