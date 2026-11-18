import itertools, os, sys, json
import pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from strategies import REGISTRY
from sim import simulate
from metrics import by_split
OUT = os.path.join(os.path.dirname(__file__), "..", "out")
b = pd.read_pickle(os.path.join(OUT, "feat_M15.pkl"))
fam = sys.argv[1]
fn, grid = REGISTRY[fam]; keys = list(grid); rows = []
for vals in itertools.product(*[grid[k] for k in keys]):
    p = dict(zip(keys, vals)); sig = fn(b, **p); sig = sig[sig.split != "test"]
    tr = simulate(sig, max_per_day=1)
    r = by_split(tr, b, ("dev", "val"))
    rows.append({"family": fam, "params": json.dumps(p), **{f"{s}_{k}": r[s].get(k) for s in r for k in ["trades", "exp_R_gross", "exp_R", "PF", "t_day", "win_rate"]}})
df = pd.DataFrame(rows); df.to_csv(os.path.join(OUT, f"grid_extra_{fam}.csv"), index=False)
pd.set_option("display.width", 250); print(df.round(3).to_string())
