"""Hand-checkable cases for the execution engine (run: python tests/test_engine.py)."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
import numpy as np, pandas as pd
from engine import Market, Order, simulate

def mk(rows):
    ts = pd.date_range("2023-01-03 10:00", periods=len(rows), freq="min")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"]); df["ts"] = ts
    df["spread"] = 10; df["tick_volume"] = 1; df["real_volume"] = 0
    m = Market(df); m.spr0[:] = 0.10   # fixed $0.10 spread for hand checks
    return m

# 1) market long, TP hit: entry ask 100.10 (+0.10 slip C1 = 100.20), SL 99.20 -> risk 1.00, TP 2R = 102.20
m = mk([[100,100,100,100],[100,100.5,99.8,100.3],[100.3,102.5,100.2,102.4],[102.4,102.4,102.4,102.4]])
r = simulate(m, Order(+1, "market", 1, 1, sl=99.20, tp_R=2.0), "C1")
assert abs(r["entry"]-100.20)<1e-9 and r["reason"]=="TP" and abs(r["exit"]-102.20)<1e-9 and abs(r["R"]-2.0)<1e-9, r
# 2) SL and TP inside the same bar -> SL, flagged ambiguous; SL fill = SL - slip
m = mk([[100,100,100,100],[100,100.1,99.9,100],[100,103,99,100],[100,100,100,100]])
r = simulate(m, Order(+1, "market", 1, 1, sl=99.5, tp_R=1.0), "C1")
assert r["reason"]=="SL" and r["ambiguous"] and abs(r["exit"]-(99.5-0.10))<1e-9, r
# 3) gap through SL fills at the (worse) open
m = mk([[100,100,100,100],[100,100.1,99.9,100],[98,98.5,97.5,98],[98,98,98,98]])
r = simulate(m, Order(+1, "market", 1, 1, sl=99.5, tp_R=2.0), "C0")
assert r["reason"]=="SL" and abs(r["exit"]-98.0)<1e-9, r
# 4) sell stop: triggers on bid low; fill = min(price, open) - slip
m = mk([[100,100,100,100],[100,100.2,99.4,99.5],[99.5,99.6,98,98.1],[98,98,98,98]])
r = simulate(m, Order(-1, "stop", 1, 2, sl=100.5, price=99.6, tp_R=1.0), "C1")
assert abs(r["entry"]-(99.6-0.10))<1e-9, r
# 5) limit needs trade-through: touch exactly at price -> no fill
m = mk([[100,100,100,100],[100,100.5,99.9,100.2],[100.2,100.5,99.9,100.4],[100,100,100,100]])
r = simulate(m, Order(+1, "limit", 1, 2, sl=99.0, price=100.0, tp_R=1.0), "C1")   # ask low = 99.9+0.1 = 100.0, no trade-through
assert r is None, r
print("engine tests passed")
