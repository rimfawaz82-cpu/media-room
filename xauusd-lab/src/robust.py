"""Phase 6 (part 1) — robustness of the two candidates, on DEV+VAL only (holdout untouched).

A) Swing: Donchian long-only. Neighbourhood grid of entry N, exit channel, stop; cost and swap stress;
   one-day execution delay; block-bootstrap Monte Carlo of daily P&L.
B) Intraday: NY opening-range breakout on high-volatility days. Neighbourhood grid of OR length,
   volatility threshold and target; costs C1 / C1_CFI / C2 / C2_CFI; Monte Carlo of trade order and of
   20% randomly missed trades.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

import swing
from audit import md_table
from engine import Market
from features import load_research
from hypotheses import context, h04_ny_orb
from load import ROOT
from run_phase3 import run_orders

TAB = ROOT / "reports" / "tables"
RNG = np.random.default_rng(20261107)


# ============================================================================ A. swing
def sig_donchian_gen(d, N, exit_n, long_only=True):
    hi = d.high.rolling(N).max().shift(); lo = d.low.rolling(N).min().shift()
    xhi = d.high.rolling(exit_n).max().shift(); xlo = d.low.rolling(exit_n).min().shift()
    pos, out = 0, []
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
    return pd.Series(out, index=d.index)


def block_bootstrap(pnl, price_ref, block=20, n=5000):
    r = (pnl / price_ref).values
    yrs = len(r) / 252
    res = []
    for _ in range(n):
        idx = np.concatenate([np.arange(s, s + block) % len(r) for s in RNG.integers(0, len(r), len(r) // block + 1)])[:len(r)]
        x = r[idx]; eq = np.cumsum(x)
        res.append((eq[-1] / yrs * 100, (np.maximum.accumulate(eq) - eq).max() * 100))
    a = np.array(res)
    return {"ann_ret_p5": np.quantile(a[:, 0], .05), "ann_ret_p50": np.median(a[:, 0]), "ann_ret_p95": np.quantile(a[:, 0], .95),
            "P(ann_ret<0)": (a[:, 0] < 0).mean(), "maxDD_p50": np.median(a[:, 1]), "maxDD_p95": np.quantile(a[:, 1], .95)}


def swing_robust():
    d = swing.daily_series()
    pref = d[d.day >= swing.START].close.mean()
    rows = []
    base_cost = swing.COST_SIDE
    for N in [10, 15, 20, 25, 30, 40, 55]:
        for ex_ratio in [0.33, 0.5, 1.0]:
            exit_n = max(3, int(round(N * ex_ratio)))
            tg = sig_donchian_gen(d, N, exit_n)
            for stop in [1.5, 2.0, 3.0, np.nan]:
                pnl, tr = swing.simulate_daily(d, tg, stop, swing.SWAP["W1"], swing.START)
                mt = swing.metrics(pnl, tr, pref)
                rows.append({"N": N, "exit_n": exit_n, "stop_ATR": stop, **{k: mt[k] for k in ["annual_return_%", "sharpe", "maxDD_%", "trades", "win_rate", "years_negative"]}})
    G = pd.DataFrame(rows)
    # stress on the registered candidate (N=20, exit 10, stop 2)
    tg = sig_donchian_gen(d, 20, 10)
    stress = []
    for label, cost, swap_rate, delay in [("base (W1, $0.50/side)", base_cost, .04, 0), ("costs x2 ($1.00/side)", 2 * base_cost, .04, 0),
                                          ("swap 0%", base_cost, 0, 0), ("swap 8%", base_cost, .08, 0), ("swap 12%", base_cost, .12, 0),
                                          ("1-day execution delay", base_cost, .04, 1), ("costs x2 + swap 8% + delay", 2 * base_cost, .08, 1)]:
        swing.COST_SIDE = cost
        t2 = tg.shift(delay).fillna(0) if delay else tg
        pnl, tr = swing.simulate_daily(d, t2, 2.0, swap_rate, swing.START)
        mt = swing.metrics(pnl, tr, pref)
        stress.append({"scenario": label, **{k: mt[k] for k in ["annual_return_%", "sharpe", "maxDD_%", "trades", "years_negative"]}})
    swing.COST_SIDE = base_cost
    pnl, tr = swing.simulate_daily(d, tg, 2.0, .04, swing.START)
    mc = block_bootstrap(pnl, pref)
    return G, pd.DataFrame(stress), mc


# ============================================================================ B. intraday
def v1_orders(mkt, ctx, or_len, tp_R, q):
    a = ctx["atr_d_prev"]
    thr = a.rolling(60, min_periods=40).quantile(q)
    keep = set(a.index[a > thr])
    return [g for g in h04_ny_orb(mkt, ctx, or_len, tp_R, "all") if pd.Timestamp(mkt.ts[g[0].i0]).normalize() in keep]


def dd_R(R):
    eq = np.cumsum(R)
    return (np.maximum.accumulate(np.r_[0, eq])[1:] - eq).max()


def intraday_robust():
    m = load_research(("dev", "val"))
    mkt = Market(m); ctx = context(mkt)
    split = m.groupby(m.ts.dt.normalize()).split.first()
    rows, base_trades = [], None
    for or_len in [15, 20, 30, 45]:
        for q in [0.4, 0.5, 0.6]:
            for tp in [1.0, 1.5, 2.0]:
                orders = v1_orders(mkt, ctx, or_len, tp, q)
                for cost in ["C1", "C1_CFI", "C2"]:
                    tr = run_orders(mkt, orders, cost)
                    tr["split"] = pd.to_datetime(tr.t_entry).dt.normalize().map(split).values
                    rec = {"or_len": or_len, "vol_quantile": q, "tp_R": tp, "cost": cost, "n": len(tr), "avg_R": tr.R.mean(),
                           "t": tr.R.mean() / (tr.R.std() / np.sqrt(len(tr))), "avg_R_dev": tr[tr.split == "dev"].R.mean(),
                           "avg_R_val": tr[tr.split == "val"].R.mean(), "win_rate": (tr.R > 0).mean()}
                    yr = tr.groupby(pd.to_datetime(tr.t_entry).dt.year).R.mean()
                    rec.update({f"avgR_{y}": v for y, v in yr.items()})
                    rows.append(rec)
                    if (or_len, q, tp, cost) == (30, 0.5, 1.0, "C1_CFI"):
                        base_trades = tr
    G = pd.DataFrame(rows)
    R = base_trades.R.values
    sims_dd = [dd_R(RNG.permutation(R)) for _ in range(5000)]
    sims_miss = []
    for _ in range(5000):
        keep = RNG.random(len(R)) > 0.2
        x = R[keep]
        sims_miss.append((x.mean(), dd_R(x)))
    sims_miss = np.array(sims_miss)
    mc = {"n_trades": int(len(R)), "avg_R": float(R.mean()), "actual_maxDD_R": float(dd_R(R)),
          "shuffle_maxDD_R_p50": float(np.median(sims_dd)), "shuffle_maxDD_R_p95": float(np.quantile(sims_dd, .95)),
          "missed20_avgR_p5": float(np.quantile(sims_miss[:, 0], .05)), "missed20_avgR_p50": float(np.median(sims_miss[:, 0])),
          "missed20_P(avgR<0)": float((sims_miss[:, 0] < 0).mean())}
    return G, mc


def main():
    Gs, St, mcs = swing_robust()
    Gi, mci = intraday_robust()
    Gs.to_csv(TAB / "p6_swing_grid.csv", index=False); St.to_csv(TAB / "p6_swing_stress.csv", index=False)
    Gi.to_csv(TAB / "p6_intraday_grid.csv", index=False)
    json.dump({"swing_mc": mcs, "intraday_mc": mci}, open(ROOT / "reports" / "p6_mc.json", "w"), indent=1, default=float)
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)
    print(Gs.round(3).to_string()); print(St.round(3).to_string()); print(mcs)
    print(Gi.round(3).to_string()); print(mci)


if __name__ == "__main__":
    main()
