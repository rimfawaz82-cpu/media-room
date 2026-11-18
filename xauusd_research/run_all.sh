#!/usr/bin/env bash
# Re-runs the whole study. Put the six MT5 exports in data/ as XAUUSD_{M1,M5,M15,H1,H4,D1}.csv
set -euo pipefail
cd "$(dirname "$0")/src"
pip install -q numba scipy pandas numpy
python3 audit.py            # step 1: inventory + quality + timezone + cross-TF  -> out/data_audit.md
python3 features.py         # feature frames (closed-bar / no look-ahead)        -> out/feat_*.pkl
python3 events.py           # step 3: 72 conditional first-passage hypotheses   -> out/event_study.csv
python3 session_decomp.py   # session/hour return decomposition 2019-2026
python3 run_grid.py         # step 2/4: 152 strategy variants, dev+val only     -> out/grid_dev_val_costNone.csv
python3 run_extra.py NYORB2 # 9 cost-aware NY ORB variants, dev+val only
python3 robust.py           # walk-forward + robustness (dev+val)
python3 final_test.py       # ONE run on locked 2026 holdout for pre-registered finalists
python3 tables.py
