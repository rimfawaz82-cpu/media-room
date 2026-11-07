# XAE Research Lab — XAUUSD M1

Quantitative research on one broker's XAUUSD.c M1 feed (MT5 export). The aim is to find out whether a trading edge exists after costs, and if it does, to build the **XAU Adaptive Edge (XAE)** strategy.

## Reproduce
```bash
pip install -r requirements.txt
python src/load.py /path/to/XAUUSD.c_M1.csv   # builds data/*.parquet (git-ignored)
python src/audit.py                            # Phase 1 -> reports/01_data_audit.md
```

## Status
| Phase | Status | Output |
|---|---|---|
| 1. Data inspection & cleaning | ✅ done | `reports/01_data_audit.md`, `reports/audit_results.json`, `reports/tables/audit_*.csv` |
| 2. Statistical market profiling (Behavior Atlas) | ⏳ next | |
| 3–10 | not started | |

## Fixed research protocol (set before any strategy testing)
- Data: M1 only, 2022-03-15 15:06 → 2026-11-06 (server time = New York + 7 h).
- Split: Dev 2022-03-15→2024-06-30 · Validation 2024-07-01→2025-06-30 · **Holdout 2025-07-01→2026-11-06 (untouched until the end)**, 1-day embargo between sets.
- Costs: scenarios C0–C3 (see audit §7). Results are only accepted if they hold at C1 and are reported at C2.
- If SL and TP are both hit inside the same bar, the SL is assumed to fill first.
- Raw data is never committed. Gaps are never filled.
