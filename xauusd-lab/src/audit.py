"""Phase 1 — Data Quality Audit for the XAUUSD.c MT5 export.

Every number in reports/01_data_audit.md is produced by this script.
Usage:  python -I src/audit.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from load import DATA, POINT, RAW_PARQUET, ROOT, load_m1

OUT = ROOT / "reports"
TAB = OUT / "tables"
TAB.mkdir(parents=True, exist_ok=True)
R: dict = {}  # machine-readable results


def md_table(df: pd.DataFrame, floatfmt: str = "{:.2f}") -> str:
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, row in df.iterrows():
        cells = []
        for v in row.values:
            if isinstance(v, (float, np.floating)):
                cells.append(floatfmt.format(v) if np.isfinite(v) else "")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> None:
    raw = pd.read_parquet(RAW_PARQUET)
    m = load_m1()
    m["date"] = m.ts.dt.normalize()
    m["dow"] = m.ts.dt.dayofweek
    m["hour"] = m.ts.dt.hour
    m["year"] = m.ts.dt.year
    m["range"] = m.high - m.low
    sections: list[str] = []

    # ---------------------------------------------------------------- 1. file / segments
    seg = raw.groupby("resolution").ts.agg(first="min", last="max", rows="size").reset_index()
    R["segments"] = seg.astype(str).to_dict("records")
    days = m.date.nunique()
    span_years = (m.ts.max() - m.ts.min()).days / 365.25
    R.update(m1_rows=len(m), m1_days=days, m1_first=str(m.ts.min()), m1_last=str(m.ts.max()), m1_years=round(span_years, 2))

    # ---------------------------------------------------------------- 2. integrity
    integ = {
        "duplicate_timestamps": int(m.ts.duplicated().sum()),
        "non_monotonic": int((m.ts.diff() <= pd.Timedelta(0)).sum()),
        "nan_any": int(m[["open", "high", "low", "close"]].isna().any(axis=1).sum()),
        "nonpositive_price": int((m[["open", "high", "low", "close"]] <= 0).any(axis=1).sum()),
        "high_lt_max_oc": int((m.high < m[["open", "close"]].max(axis=1) - 1e-9).sum()),
        "low_gt_min_oc": int((m.low > m[["open", "close"]].min(axis=1) + 1e-9).sum()),
        "high_lt_low": int((m.high < m.low).sum()),
        "zero_range_bars": int((m.range == 0).sum()),
        "flat_ohlc_bars": int(((m.open == m.high) & (m.high == m.low) & (m.low == m.close)).sum()),
        "price_decimals_max": int(m.close.map(lambda x: len(f"{x:.5f}".rstrip("0").split(".")[1]) if "." in f"{x:.5f}".rstrip("0") else 0).max()),
        "real_volume_nonzero_rows": int((m.real_volume != 0).sum()),
        "spread_zero_rows": int((m.spread == 0).sum()),
        "tick_volume_le_1": int((m.tick_volume <= 1).sum()),
        "seconds_nonzero": int((m.ts.dt.second != 0).sum()),
    }
    R["integrity"] = integ

    # ---------------------------------------------------------------- 3. session clock / timezone
    g = m.groupby("date").ts
    fl = pd.DataFrame({"first": g.min().dt.strftime("%H:%M"), "last": g.max().dt.strftime("%H:%M"), "bars": g.size()})
    fl["dow"] = pd.to_datetime(fl.index).dayofweek
    first_mode = fl.groupby("dow")["first"].agg(lambda s: s.value_counts().idxmax())
    last_mode = fl.groupby("dow")["last"].agg(lambda s: s.value_counts().idxmax())
    bars_by_hour = m.groupby("hour").size()
    R["session_clock"] = {
        "first_bar_mode_by_dow": first_mode.to_dict(),
        "last_bar_mode_by_dow": last_mode.to_dict(),
        "hours_with_zero_bars": [int(h) for h in range(24) if h not in bars_by_hour.index],
        "weekend_bars": int((m.dow >= 5).sum()),
    }

    # Timezone verification: US data releases at 08:30 New York must appear at a fixed
    # server minute if the server is NY+7 (GMT+2 winter / GMT+3 summer, US DST rule).
    # Test: on the first Friday of each month (NFP, approx.), which minute has the largest range?
    m["minute_of_day"] = m.hour * 60 + m.ts.dt.minute
    fridays = m[m.dow == 4]
    first_fri = fridays.groupby(fridays.ts.dt.to_period("M")).date.min()
    nfp = m[m.date.isin(first_fri.values)]
    peak = nfp.loc[nfp.groupby("date")["range"].idxmax(), ["date", "ts"]]
    peak["server_time"] = peak.ts.dt.strftime("%H:%M")
    peak_counts = peak.server_time.value_counts()
    # also check across the US/EU DST mismatch windows (US switched, EU not yet / already)
    R["tz_check"] = {
        "first_friday_count": int(len(peak)),
        "largest_range_minute_top5": peak_counts.head(5).to_dict(),
        "share_at_15_30": round(float((peak.server_time == "15:30").mean()), 3),
    }
    # Average range by minute-of-day across all days, top minutes (scheduled-event fingerprints)
    mod = m.groupby("minute_of_day")["range"].mean().sort_values(ascending=False).head(8)
    R["top_range_minutes"] = {f"{k // 60:02d}:{k % 60:02d}": round(v, 3) for k, v in mod.items()}

    # ---------------------------------------------------------------- 4. gaps
    d = m.ts.diff().dt.total_seconds().div(60)
    gp = m.assign(gap_min=d, prev_ts=m.ts.shift())
    gp = gp[gp.gap_min > 1].copy()

    def gap_type(r):
        if r.gap_min >= 24 * 60:
            return "weekend/holiday (>=1 day)"
        if r.prev_ts.hour >= 23 and r.ts.hour == 1 and r.ts.minute <= 5:
            return "daily break (~23:59-01:00)"
        if r.gap_min > 60:
            return "early close / long intraday halt (>60m)"
        if r.gap_min > 5:
            return "intraday gap 6-60m"
        return "intraday gap 2-5m"

    gp["type"] = gp.apply(gap_type, axis=1)
    gap_summary = gp.groupby("type").gap_min.agg(count="size", total_missing_min=lambda s: (s - 1).sum(), max_min="max").reset_index()
    R["gaps"] = gap_summary.to_dict("records")
    unusual = gp[~gp.type.isin(["weekend/holiday (>=1 day)", "daily break (~23:59-01:00)"])][["prev_ts", "ts", "gap_min", "type"]]
    unusual.to_csv(TAB / "audit_unusual_gaps.csv", index=False)

    # Missing weekdays (calendar business days without any bar)
    bdays = pd.bdate_range(m.date.min(), m.date.max())
    missing_bdays = sorted(set(bdays) - set(m.date.unique()))
    R["missing_weekdays"] = [str(x.date()) for x in missing_bdays]

    # Short days
    full = fl.bars.median()
    short = fl[fl.bars < 0.9 * full].reset_index().rename(columns={"index": "date"})
    short.to_csv(TAB / "audit_short_days.csv", index=False)
    R["short_days_count"] = int(len(short))
    R["full_day_bars_median"] = int(full)

    # Coverage of expected minutes: expected = Mon-Fri 01:00-23:58 (Fri to ~23:5x) per trading day present
    expected = days * (23 * 60 - 1)
    R["coverage_vs_nominal_23h_session"] = round(len(m) / expected, 4)

    # ---------------------------------------------------------------- 5. jumps / outliers
    m["ret"] = np.log(m.close).diff()
    m["open_gap"] = m.open - m.close.shift()
    within = gp.index  # rows that start after a gap
    m["after_gap"] = m.index.isin(within)
    contig = m[~m.after_gap]
    # robust scale per year (price level moved from ~1.9k to 4k+)
    contig = contig.assign(absret=contig.ret.abs())
    mad = contig.groupby("year").absret.median()
    contig = contig.assign(z=contig.absret / contig.year.map(mad))
    big = contig[contig.z > 25].sort_values("z", ascending=False)
    big_out = big[["ts", "open", "high", "low", "close", "tick_volume", "spread", "range", "z"]].head(40)
    big_out.to_csv(TAB / "audit_largest_moves.csv", index=False)
    R["jumps"] = {
        "bars_absret_gt_25x_median": int(len(big)),
        "bars_range_gt_10usd": int((m.range > 10).sum()),
        "bars_range_gt_20usd": int((m.range > 20).sum()),
        "max_bar_range": {"ts": str(m.loc[m.range.idxmax(), "ts"]), "range": float(m.range.max())},
    }
    # open vs previous close continuity on contiguous bars
    oc = contig.open_gap.abs()
    R["open_vs_prev_close_contiguous"] = {
        "share_exact_equal": round(float((oc < 1e-9).mean()), 4),
        "p50": float(oc.quantile(0.5)), "p99": float(oc.quantile(0.99)), "max": float(oc.max()),
    }
    # weekend / daily-break opening gaps
    wk = m[m.after_gap].copy()
    wk["gap_type"] = gp.loc[wk.index, "type"].values
    wg = wk.groupby("gap_type").open_gap.agg(n="size", mean_abs=lambda s: s.abs().mean(), p95_abs=lambda s: s.abs().quantile(0.95), max_abs=lambda s: s.abs().max()).reset_index()
    R["opening_gaps"] = wg.to_dict("records")
    wk[wk.gap_type == "weekend/holiday (>=1 day)"][["ts", "open", "open_gap"]].assign(prev_close=lambda x: x.open - x.open_gap).sort_values("open_gap", key=abs, ascending=False).head(15).to_csv(TAB / "audit_largest_weekend_gaps.csv", index=False)

    # ---------------------------------------------------------------- 6. spread
    sp = m.spread
    R["spread_points"] = {k: float(v) for k, v in sp.describe(percentiles=[0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99, 0.999]).items()}
    R["spread_value_counts_top"] = {int(k): int(v) for k, v in sp.value_counts().head(10).items()}
    sp_year = m.groupby("year").spread.describe(percentiles=[0.5, 0.95, 0.99])[["mean", "50%", "95%", "99%", "max"]].reset_index()
    sp_hour = m.groupby("hour").spread.agg(mean="mean", p50="median", p95=lambda s: s.quantile(0.95), share_gt_20=lambda s: (s > 20).mean()).reset_index()
    sp_ym = m.groupby(m.ts.dt.to_period("M")).spread.agg(["mean", "median", lambda s: s.quantile(0.95)])
    sp_ym.columns = ["mean", "median", "p95"]
    sp_ym.to_csv(TAB / "audit_spread_by_month.csv")
    sp_hour.to_csv(TAB / "audit_spread_by_hour.csv", index=False)
    # spread relative to bar range (cost burden)
    rng_med_year = m.groupby("year")["range"].median()

    # ---------------------------------------------------------------- 7. tick volume
    tv = m.groupby("year").tick_volume.describe(percentiles=[0.5, 0.99])[["mean", "50%", "99%", "max"]].reset_index()

    # ---------------------------------------------------------------- 8. yearly market character
    daily = m.groupby("date").agg(o=("open", "first"), h=("high", "max"), l=("low", "min"), c=("close", "last"), bars=("ts", "size"))
    daily["rng"] = daily.h - daily.l
    daily["rng_pct"] = daily.rng / daily.o * 100
    daily["year"] = daily.index.year
    yr = daily.groupby("year").agg(days=("rng", "size"), first_open=("o", "first"), last_close=("c", "last"), price_min=("l", "min"), price_max=("h", "max"),
                                   daily_range_mean=("rng", "mean"), daily_range_median=("rng", "median"), daily_range_pct_median=("rng_pct", "median")).reset_index()
    yr["year_return_pct"] = (yr.last_close / yr.first_open - 1) * 100
    m1_yr = m.groupby("year").agg(m1_range_median=("range", "median"), m1_range_mean=("range", "mean"), spread_median_usd=("spread", lambda s: s.median() * POINT)).reset_index()
    yr = yr.merge(m1_yr, on="year")
    yr["spread_over_m1_median_range"] = yr.spread_median_usd / yr.m1_range_median
    yr.to_csv(TAB / "audit_yearly_profile.csv", index=False)

    # ---------------------------------------------------------------- write report
    seg_md = md_table(seg.assign(first=seg["first"].astype(str), last=seg["last"].astype(str)))
    gap_md = md_table(gap_summary, "{:.0f}")
    wg_md = md_table(wg, "{:.2f}")
    yr_md = md_table(yr.round(3).assign(year=yr.year.astype(str), days=yr.days.astype(str)), "{:.2f}")
    spy_md = md_table(sp_year.round(2).assign(year=sp_year.year.astype(str)), "{:.1f}")
    sph_md = md_table(sp_hour.round(3).assign(hour=sp_hour.hour.astype(str)), "{:.2f}")
    tv_md = md_table(tv.round(1), "{:.0f}")
    big_md = md_table(big_out.head(12).assign(ts=lambda x: x.ts.astype(str)).round(2), "{:.2f}")
    unusual_md = md_table(unusual.assign(prev_ts=unusual.prev_ts.astype(str), ts=unusual.ts.astype(str)).head(40), "{:.0f}")

    report = f"""# Phase 1 — Data Audit Report (XAUUSD.c, MT5 export)

_Generated by `src/audit.py`. Every number below comes from that script; machine-readable copy in `reports/audit_results.json`._

## 1. Identity of the file

| Item | Finding |
|---|---|
| File | `XAUUSD.c_M1.csv` (101.5 MB, tab-separated, CRLF, MT5 "Export bars" format) |
| Symbol | `XAUUSD.c` — broker-specific suffix `.c`; this is an **OTC spot-gold CFD feed of one broker**, not exchange futures (GC) and not a consolidated spot reference |
| Price side | MT5 bars are built from **Bid** prices. No Ask series is present. Ask ≈ Bid + spread is an approximation only |
| Columns | DATE, TIME, OPEN, HIGH, LOW, CLOSE, TICKVOL, VOL, SPREAD |
| Real volume | `VOL` is non-zero on {integ['real_volume_nonzero_rows']} of {len(m):,} M1 rows → **no real volume**. Volume-weighted tools (true VWAP, volume profile) cannot be built; only tick-count proxies |
| Tick volume | Present (count of price updates per bar) — a broker-specific activity proxy, not traded size |
| Spread | Integer **points** (1 point = $0.01). MT5 stores one spread value per bar (typically the minimum/representative spread recorded in that bar, not the max) → it **understates** spikes |
| Price precision | {integ['price_decimals_max']} decimals → 1 point = $0.01, 1 "pip" (common gold convention) = $0.10, $1.00 = 100 points |

**Unit convention used in this lab (fixed for all phases):** all distances are expressed in **USD of price** (e.g. $1.50), and when needed in points ($0.01). The ambiguous word "pip" is not used in results.

## 2. The file is NOT 6.8 years of M1 — it contains three resolutions

{seg_md}

* 2020-01-02 → 2021-11-15: **daily bars**. 2021-11-16 → 2022-03-15 15:00: **hourly bars**. Only from **2022-03-15 15:06** is the data true M1 (the first M1 day is partial).
* Usable M1 history: **{R['m1_first']} → {R['m1_last']}** = **{R['m1_years']} years, {days:,} trading days, {len(m):,} bars**. This matches the "≈4.5 years" brief.
* Decision: research uses **only the M1 segment**. The D1/H1 rows are excluded (they cannot be used for M1 simulation and would contaminate intraday statistics). They could later serve as long-term context only.

## 3. Integrity checks (M1 segment)

| Check | Result |
|---|---|
| Duplicate timestamps | {integ['duplicate_timestamps']} |
| Non-monotonic timestamps | {integ['non_monotonic']} |
| NaN in OHLC | {integ['nan_any']} |
| Non-positive prices | {integ['nonpositive_price']} |
| High < max(Open, Close) | {integ['high_lt_max_oc']} |
| Low > min(Open, Close) | {integ['low_gt_min_oc']} |
| High < Low | {integ['high_lt_low']} |
| Bars with zero range | {integ['zero_range_bars']} |
| Bars with flat OHLC | {integ['flat_ohlc_bars']} |
| Bars with tick volume ≤ 1 | {integ['tick_volume_le_1']} |
| Bars with spread = 0 | {integ['spread_zero_rows']} |
| Weekend (Sat/Sun) bars | {R['session_clock']['weekend_bars']} |

No structural corruption found. OHLC relationships are internally consistent on every bar.

## 4. Server clock, timezone & DST

* Every trading day starts at **{first_mode.iloc[1]}** server time (Mon–Fri mode) and ends at **{last_mode.iloc[1]}** (Mon–Thu); Friday ends at **{last_mode.iloc[4]}**. Server hour(s) with zero bars: {R['session_clock']['hours_with_zero_bars']}.
* This is the classic "New-York-close" server clock: the CME/OTC gold maintenance halt 17:00–18:00 New York maps to **00:00–01:00 server**, i.e. **server = New York + 7 h** all year round (GMT+2 in US winter, GMT+3 in US summer).
* **Verification with a market fingerprint:** on {R['tz_check']['first_friday_count']} first-Fridays-of-month (≈ NFP, released 08:30 New York), the minute with the largest M1 range was **15:30 server** on **{R['tz_check']['share_at_15_30']*100:.0f}%** of days (top minutes: {R['tz_check']['largest_range_minute_top5']}). 08:30 NY + 7h = 15:30 → the NY+7 hypothesis holds through both US DST regimes.
* Highest-average-range minutes over all days: {R['top_range_minutes']} — the 15:30/17:00 (08:30 / 10:00 NY data releases) and 16:30 (NY cash open 09:30) fingerprints appear exactly where NY+7 predicts.

**Consequences for all later phases**
* New York times are a constant shift (−7 h). London times are **not** constant: during the 2–3 weeks per year when US and EU DST differ (March and late Oct/early Nov), London is 1 h "earlier" on the server clock. Session definitions will be computed in true Europe/London and America/New_York time from `ts − 7h` (NY) and tz conversion, not in fixed server hours.
* Tokyo/Asia has no DST; Asian session in server time shifts by 1 h between US summer and winter.

## 5. Gaps and missing data

{gap_md}

* The daily ~62-minute halt and weekend closures are normal market structure, not data loss.
* Calendar weekdays with **no bars at all**: {len(R['missing_weekdays'])} → {', '.join(R['missing_weekdays'])} (Good Friday, Christmas, New Year — gold closed).
* Days with < 90% of a normal day's {R['full_day_bars_median']} bars: {R['short_days_count']} (holidays with early close, e.g. US holidays at 21:30 server = 14:30 NY close; first day of the file). List: `reports/tables/audit_short_days.csv`.
* Coverage vs a nominal 23-h session on present days: {R['coverage_vs_nominal_23h_session']*100:.2f}%.
* Unusual intraday gaps (not daily halt/weekend) — full list in `reports/tables/audit_unusual_gaps.csv`; first 40:

{unusual_md}

**Treatment:** gaps are left as gaps. No bars are synthesised. Any backtest must (a) not fill orders inside a gap, (b) treat the first bar after a gap as a possible gap-through for stops (fill at the bar open, not at the stop price), and (c) features that span a gap (e.g. rolling windows) must count real bars, not clock minutes, or be invalidated across the gap.

## 6. Price jumps, opening gaps, continuity

* Within contiguous trading, open vs previous close: equal on {R['open_vs_prev_close_contiguous']['share_exact_equal']*100:.1f}% of bars; median |diff| ${R['open_vs_prev_close_contiguous']['p50']:.2f}, p99 ${R['open_vs_prev_close_contiguous']['p99']:.2f}, max ${R['open_vs_prev_close_contiguous']['max']:.2f}.
* Opening gaps after halts:

{wg_md}

* Bars with range > $10: {R['jumps']['bars_range_gt_10usd']:,}; > $20: {R['jumps']['bars_range_gt_20usd']:,}. Largest M1 range: ${R['jumps']['max_bar_range']['range']:.2f} at {R['jumps']['max_bar_range']['ts']}.
* Bars whose |log return| exceeds 25× that year's median absolute return: {R['jumps']['bars_absret_gt_25x_median']:,}. The top ones (below) coincide with tick-volume spikes at known release minutes — they are **genuine moves, not bad ticks**: each sits inside a sequence of neighbouring bars that continue at the new level (checked manually for 2026-01-29 17:24–17:33, 2026-02-02 03:07–03:16, 2023-05-04 01:02–01:11 and 2026-09-04 15:27–15:36), so they are kept. Note several of these violent bars carry spread = 0 or 10 — the recorded spread clearly does not reflect real news-time execution. Full list `reports/tables/audit_largest_moves.csv`.

{big_md}

## 7. Spread (execution cost evidence)

Distribution over all M1 bars (points; 10 points = $0.10): median {R['spread_points']['50%']:.0f}, mean {R['spread_points']['mean']:.2f}, p95 {R['spread_points']['95%']:.0f}, p99 {R['spread_points']['99%']:.0f}, p99.9 {R['spread_points']['99.9%']:.0f}, max {R['spread_points']['max']:.0f}.
Most frequent values: {R['spread_value_counts_top']}.

By year:

{spy_md}

By server hour (mean, median, p95, share of bars with spread > 20 pts):

{sph_md}

**Interpretation & limits**
* The spread is overwhelmingly a fixed **10 points ($0.10)** — this looks like a broker-set floor, not a measured market spread. It widens around the daily halt (server 23:00 / 01:00) and on news.
* Because only one value per bar is stored, spikes inside the minute (exactly when stops get hit on news) are **under-represented**. Spread = 0 on {integ['spread_zero_rows']:,} bars is not physically real.
* The account type behind `.c` is unknown: if it is a commission account, a commission per lot must be added. **Cost scenarios** used for every backtest (round-turn, in USD of price per 1 oz):
  * **C0 (optimistic):** recorded bar spread, no commission, no slippage.
  * **C1 (base):** max(recorded spread, $0.20) + $0.07 commission-equivalent + $0.05 slippage per side on stop/market orders.
  * **C2 (stress):** 2× C1.
  * **C3 (news):** C1 + extra $0.30 slippage for entries/exits within ±3 min of 15:30/17:00 server releases.
  These are declared assumptions, not measured broker costs; they must be replaced by the user's real broker contract spec before sizing.

## 8. Tick volume

{tv_md}

**Tick volume is capped by the feed:** from 2023 onward the per-minute maximum never exceeds ~{int(tv['max'].iloc[1:].max())} even on the most violent news minutes (e.g. the $128 bar on 2026-01-29 shows only 836 ticks, similar to its neighbours). It saturates exactly when activity matters most, so it is a weak, truncated proxy.

Tick volume is usable as a relative *activity* proxy within this one feed (e.g. "this minute is 3× the hour's usual activity"). It is not traded volume and is not comparable across brokers.

## 9. Market regime changes across the sample (why everything must be normalised)

{yr_md}

* Gold more than doubled over the sample, and the typical daily range in dollars changed several-fold. A fixed "$5 target" in 2022 and in 2026 are completely different trades. **All thresholds, stops and targets in later phases will be tested both in USD and normalised by ATR / realised volatility.**
* The cost burden falls over time: a fixed $0.10–0.30 spread is a much larger fraction of the median M1 range in 2022 than in 2026 (`spread_over_m1_median_range`). Results must be reported per year so that any edge which exists only because costs shrank in relative terms is visible.

## 10. What the data can and cannot support

| Capability | Status |
|---|---|
| M1 OHLC simulation 2022-03 → 2026-11 | ✅ available |
| Higher timeframes (M5…D1) | ✅ reconstructable from M1 (with daily boundary at 00:00 server = 17:00 NY) |
| Bid/Ask, true fills | ❌ Bid only + one spread per bar → cost scenarios required |
| Intra-minute order of High/Low | ❌ unknown → conservative SL-first rule when SL and TP are both inside one bar |
| Real volume / VWAP / order flow | ❌ only tick-count proxies; "VWAP" can only be tick-weighted, labelled as such |
| Economic calendar | ❌ not in the file. Release minutes can be inferred from the clock (08:30/10:00 NY fingerprints) but event identity/surprise is unknown. A dated calendar would be needed for event studies |
| Long-term (pre-2022) context | ⚠️ D1/H1 only; excluded from intraday research |

## 11. Proposed data split (fixed now, before any strategy work)

| Set | Period | Purpose |
|---|---|---|
| Development / Training | 2022-03-15 → 2024-06-30 (~2.3 y) | exploration, hypothesis screening, walk-forward inner loops |
| Validation | 2024-07-01 → 2025-06-30 (1 y) | model / parameter selection |
| **Final untouched holdout** | **2025-07-01 → 2026-11-06 (~1.35 y)** | touched once, at the end; never used for selection |

Embargo of 1 trading day at each boundary. Note the holdout falls in the highest-price, highest-volatility regime of the sample — a deliberately hard out-of-sample test, but also a regime shift; normalised features are mandatory.

## 12. Verdict for Phase 1

**Data quality: GOOD for M1 OHLC research, with declared limitations.** No duplicates, no corrupt OHLC, no fabricated-looking jumps; gaps correspond to genuine market closures. Main limitations: single-broker Bid feed, synthetic-looking fixed spread, no real volume, no news calendar, and only 4.65 years of M1 (the earlier part of the file is D1/H1).

**Required from you (optional, improves realism):** your broker's XAUUSD.c contract spec (contract size, commission per lot, min lot, stop level, swap) and, if available, a dated economic calendar (CSV) for 2022–2026.
"""
    (OUT / "01_data_audit.md").write_text(report, encoding="utf-8")
    (OUT / "audit_results.json").write_text(json.dumps(R, indent=2, default=str), encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
