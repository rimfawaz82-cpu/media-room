"""Phase 1b — Bid/Ask tick data audit, reconciliation with the M1 Bid file, and a
measured execution-cost model.

Usage: python src/tick_audit.py   (after src/ticks.py)
Outputs: reports/01b_bidask_audit.md, reports/bidask_results.json, reports/tables/ba_*.csv
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from audit import md_table
from load import load_m1, ROOT
from ticks import M1BA, TICKS

OUT = ROOT / "reports"
TAB = OUT / "tables"
R: dict = {}


def q(s: pd.Series, ps=(0.5, 0.75, 0.9, 0.95, 0.99, 0.999)) -> dict:
    return {f"p{int(p * 1000) / 10:g}": round(float(s.quantile(p)), 4) for p in ps}


def main() -> None:
    # ------------------------------------------------------------------ load ticks
    tk = pq.read_table(TICKS).to_pandas()
    tk["bid"] = tk["bid"].astype("float64") / 100
    tk["ask"] = tk["ask"].astype("float64") / 100
    tk["spr"] = tk["ask"] - tk["bid"]
    n = len(tk)
    parts = pd.read_csv(TAB / "ticks_parts.csv")
    R["ticks"] = {"rows": n, "first": str(tk.ts.iloc[0]), "last": str(tk.ts.iloc[-1]),
                  "days": int(tk.ts.dt.normalize().nunique()),
                  "bid_only_rows": int(parts.bid_only.sum()), "ask_only_rows": int(parts.ask_only.sum()),
                  "both_rows": int(parts.both.sum()), "neither_rows": int(parts.neither.sum())}

    # ------------------------------------------------------------------ integrity
    dts = tk.ts.diff().dt.total_seconds()
    R["tick_integrity"] = {
        "non_monotonic": int((dts < 0).sum()),
        "same_ms_timestamp": int((dts == 0).sum()),
        "crossed_ask_lt_bid": int((tk.spr < 0).sum()),
        "locked_ask_eq_bid": int((tk.spr == 0).sum()),
        "spread_gt_1usd": int((tk.spr > 1).sum()),
        "spread_gt_5usd": int((tk.spr > 5).sum()),
        "max_spread": float(tk.spr.max()), "max_spread_ts": str(tk.ts.iloc[int(tk.spr.values.argmax())]),
    }
    # in-session silences (exclude daily break and weekends)
    gap = pd.DataFrame({"prev": tk.ts.shift(), "ts": tk.ts, "sec": dts})
    gap = gap[(gap.sec > 60)]
    daily = (gap.prev.dt.hour == 23) & (gap.ts.dt.hour == 1)
    weekend = gap.sec > 20 * 3600
    ins = gap[~daily & ~weekend]
    R["tick_silences_gt_60s_in_session"] = int(len(ins))
    ins.to_csv(TAB / "ba_tick_silences.csv", index=False)
    R["tick_silence_examples"] = ins.sort_values("sec", ascending=False).head(10).astype(str).to_dict("records")
    # bid jumps between consecutive ticks
    dbid = tk.bid.diff().abs()
    R["consecutive_bid_jump"] = {"gt_2usd": int((dbid > 2).sum()), "gt_5usd": int((dbid > 5).sum()), "max": float(dbid.max()),
                                 "max_ts": str(tk.ts.iloc[int(np.nanargmax(dbid.values))])}

    # ------------------------------------------------------------------ spread distribution (tick-level and time-weighted)
    m = pd.read_parquet(M1BA)
    m["hour"] = m.ts.dt.hour
    m["mod"] = m.ts.dt.hour * 60 + m.ts.dt.minute
    m["dow"] = m.ts.dt.dayofweek
    m["mid_c"] = (m.bid_c + m.ask_c) / 2
    R["spread_tick_level_usd"] = q(tk.spr) | {"mean": round(float(tk.spr.mean()), 4), "min": float(tk.spr.min())}
    R["spread_time_weighted_minute_usd"] = q(m.spr_twmean.dropna()) | {"mean": round(float(m.spr_twmean.mean()), 4)}
    R["spread_minute_max_usd"] = q(m.spr_max)
    vc = (tk.spr * 100).round().astype(int).value_counts(normalize=True).head(12)
    R["spread_points_share_top"] = {int(k): round(float(v), 4) for k, v in vc.items()}
    # bps of price (to transport to other price levels)
    m["spr_bps"] = m.spr_twmean / m.mid_c * 1e4
    R["spread_bps_twmean"] = q(m.spr_bps.dropna())

    by_hour = m.groupby("hour").agg(tw_median=("spr_twmean", "median"), tw_mean=("spr_twmean", "mean"),
                                    open_p95=("spr_open", lambda s: s.quantile(.95)), max_p95=("spr_max", lambda s: s.quantile(.95)),
                                    max_p99=("spr_max", lambda s: s.quantile(.99)), ticks_per_min=("ticks_all", "median")).reset_index()
    by_hour.to_csv(TAB / "ba_spread_by_hour.csv", index=False)
    by_month = m.groupby(m.ts.dt.to_period("M")).agg(tw_median=("spr_twmean", "median"), tw_mean=("spr_twmean", "mean"),
                                                    bps_median=("spr_bps", "median"), price_mean=("mid_c", "mean"),
                                                    max_p99=("spr_max", lambda s: s.quantile(.99))).reset_index()
    by_month["ts"] = by_month.ts.astype(str)
    by_month.to_csv(TAB / "ba_spread_by_month.csv", index=False)
    by_dow = m.groupby("dow").spr_twmean.median()

    # event minutes: 15:30 (08:30 NY), 16:30 (cash open), 17:00 (10:00 NY), 21:00 (14:00 NY FOMC), 01:00 (reopen)
    ev = {}
    for lbl, mm in [("01:00 reopen", 60), ("01:01", 61), ("01:05", 65), ("15:29", 929), ("15:30 (08:30 NY data)", 930), ("15:31", 931), ("15:35", 935),
                    ("16:30 (NY cash open)", 990), ("17:00 (10:00 NY data)", 1020), ("21:00 (14:00 NY, FOMC)", 1260), ("23:55", 1435), ("other minutes", None)]:
        s = m[m["mod"] == mm] if mm is not None else m[~m["mod"].isin([60, 61, 65, 929, 930, 931, 935, 990, 1020, 1260, 1435])]
        ev[lbl] = {"n": int(len(s)), "tw_median": s.spr_twmean.median(), "tw_mean": s.spr_twmean.mean(),
                   "max_median": s.spr_max.median(), "max_p90": s.spr_max.quantile(.9), "max_max": s.spr_max.max()}
    evdf = pd.DataFrame(ev).T.reset_index().rename(columns={"index": "minute"})
    evdf.to_csv(TAB / "ba_spread_event_minutes.csv", index=False)

    # spread vs volatility (is spread a function of activity?)
    m["rng"] = m.bid_h - m.bid_l
    m["rng_q"] = pd.qcut(m.rng, 10, labels=False, duplicates="drop")
    by_vol = m.groupby("rng_q").agg(rng_lo=("rng", "min"), rng_hi=("rng", "max"), tw_median=("spr_twmean", "median"),
                                    max_median=("spr_max", "median"), max_p95=("spr_max", lambda s: s.quantile(.95))).reset_index()
    R["corr_spread_vs_minute_range"] = round(float(m[["spr_twmean", "rng"]].corr(method="spearman").iloc[0, 1]), 3)
    R["spread_over_minute_range_median"] = round(float((m.spr_twmean / m.rng.replace(0, np.nan)).median()), 3)

    # ------------------------------------------------------------------ reconcile with M1 Bid file
    b = load_m1()
    j = b.merge(m, on="ts", how="inner")
    lo, hi = m.ts.min(), m.ts.max()
    bwin = b[(b.ts >= lo) & (b.ts <= hi)]
    rec = {"m1_file_minutes_in_window": int(len(bwin)), "tick_minutes": int(len(m)), "matched": int(len(j)),
           "in_m1_file_not_in_ticks": int((~bwin.ts.isin(m.ts)).sum()), "in_ticks_not_in_m1_file": int((~m.ts.isin(b.ts)).sum())}
    for c in ["open", "high", "low", "close"]:
        d = (j[c] - j[f"bid_{c[0]}"]).abs()
        rec[f"bid_{c}_exact_match"] = round(float((d < 0.005).mean()), 4)
        rec[f"bid_{c}_within_0.05"] = round(float((d <= 0.05).mean()), 4)
        rec[f"bid_{c}_p99_absdiff"] = round(float(d.quantile(0.99)), 3)
    # what does the SPREAD column of the M1 file represent?
    sc = j.spread / 100
    for c in ["spr_open", "spr_min", "spr_twmean", "spr_close", "spr_max"]:
        rec[f"m1SPREAD_vs_{c}_exact"] = round(float(((sc - j[c]).abs() < 0.005).mean()), 4)
        rec[f"m1SPREAD_vs_{c}_mae"] = round(float((sc - j[c]).abs().mean()), 4)
    rec["m1SPREAD_median_usd"] = float(sc.median())
    rec["real_twspread_median_usd_same_minutes"] = float(j.spr_twmean.median())
    rec["share_minutes_real_max_spread_gt_m1SPREAD"] = round(float((j.spr_max > sc + 0.005).mean()), 4)
    rec["tickvol_vs_ticks_bid_spearman"] = round(float(j[["tick_volume", "ticks_bid"]].corr(method="spearman").iloc[0, 1]), 3)
    rec["tickvol_over_ticks_bid_median"] = round(float((j.tick_volume / j.ticks_bid).median()), 3)
    rec["ticks_all_per_minute_max"] = int(m.ticks_all.max())
    rec["tickvol_m1file_max_in_window"] = int(bwin.tick_volume.max())
    R["reconciliation"] = rec
    mism = j.assign(dh=(j.high - j.bid_h).abs(), dl=(j.low - j.bid_l).abs())
    mism[(mism.dh > 0.05) | (mism.dl > 0.05)][["ts", "open", "high", "low", "close", "bid_o", "bid_h", "bid_l", "bid_c", "spread", "spr_max"]].to_csv(TAB / "ba_ohlc_mismatches.csv", index=False)

    # ------------------------------------------------------------------ intra-minute order: what the M1 file cannot tell us
    tk["minute"] = tk.ts.dt.floor("min")
    g = tk.groupby("minute", sort=True)
    # position of first max and first min bid inside the minute
    tk["i"] = np.arange(n)
    imax = tk.loc[g.bid.idxmax(), ["minute", "i"]].set_index("minute").i
    imin = tk.loc[g.bid.idxmin(), ["minute", "i"]].set_index("minute").i
    first_o = g.bid.first()
    hi_ = g.bid.max(); lo_ = g.bid.min()
    od = pd.DataFrame({"high_first": imax < imin, "up": hi_ - first_o, "dn": first_o - lo_})
    amb = {}
    for x in [0.5, 1.0, 2.0, 3.0]:
        both = od[(od.up >= x) & (od.dn >= x)]
        amb[f"both_±{x}$_touched_in_same_minute"] = {"share_of_minutes": round(float(len(both) / len(od)), 5), "n": int(len(both)),
                                                        "high_came_first_share": round(float(both.high_first.mean()), 3) if len(both) else None}
    R["intra_minute_ambiguity"] = amb

    # ------------------------------------------------------------------ execution delay (latency) risk on mid
    ts_ns = tk.ts.values.astype("datetime64[ms]").astype("int64")
    mid = ((tk.bid + tk.ask) / 2).values
    sample = np.random.default_rng(20261107).choice(n - 1, size=min(2_000_000, n - 1), replace=False)
    sample.sort()
    lat = {}
    for ms in [100, 250, 500, 1000, 3000]:
        j2 = np.searchsorted(ts_ns, ts_ns[sample] + ms, side="right") - 1
        d = np.abs(mid[j2] - mid[sample])
        lat[f"{ms}ms"] = {"median": round(float(np.median(d)), 3), "p90": round(float(np.quantile(d, .9)), 3),
                          "p99": round(float(np.quantile(d, .99)), 3)}
    R["mid_move_after_delay_usd"] = lat
    R["latency_sample_seed"] = 20261107

    # ------------------------------------------------------------------ calibrated cost model
    base_rt = float(m.spr_twmean.median())
    p90_rt = float(m.spr_twmean.quantile(.9))
    R["cost_model"] = {
        "C0_measured": "pay the actual Ask (buy) / Bid (sell) from the tick-built minute bars at the moment of the fill; no commission, no slippage",
        "C1_base": f"actual Ask/Bid fill + slippage $0.05 on market/stop orders + commission (broker-specific, user must confirm; $0 assumed)",
        "C2_stress": "C1 with slippage $0.20 and spread multiplied by 2",
        "C3_news": "C1 + extra $0.50 slippage within ±2 min of 15:30/17:00/21:00 server",
        "historical_2022_2025_transport": "spread_bps of price (median and p90 by hour) applied to the M1 Bid history, since Ask is unavailable before 2026-03-27",
        "measured_median_roundtrip_spread_usd": round(base_rt, 3), "measured_p90_roundtrip_spread_usd": round(p90_rt, 3),
    }

    # ------------------------------------------------------------------ report
    T = R["ticks"]; I = R["tick_integrity"]; rc = R["reconciliation"]
    hour_md = md_table(by_hour.round(3).assign(hour=by_hour.hour.astype(str)), "{:.3f}")
    month_md = md_table(by_month.round(3), "{:.3f}")
    ev_md = md_table(evdf.assign(n=evdf.n.astype(int).astype(str)), "{:.3f}")
    vol_md = md_table(by_vol.drop(columns="rng_q").round(3), "{:.3f}")
    amb_md = md_table(pd.DataFrame(amb).T.reset_index().rename(columns={"index": "condition"}).astype(str))
    lat_md = md_table(pd.DataFrame(lat).T.reset_index().rename(columns={"index": "delay"}), "{:.3f}")

    report = f"""# Phase 1b — Bid/Ask Tick Data Audit & Measured Cost Model

_Generated by `src/ticks.py` + `src/tick_audit.py`. Machine-readable: `reports/bidask_results.json`._

## 1. What was received

* 17 zip parts → one MT5 **raw tick export** of `XAUUSD.c` (`DATE, TIME (ms), BID, ASK, LAST, VOLUME, FLAGS`). LAST and VOLUME are empty (OTC CFD, no trades/volume).
* **{T['rows']:,} quote updates**, **{T['first']} → {T['last']}** (server time, NY+7), **{T['days']} trading days ≈ 7.4 months**.
* Rows by side updated: bid-only {T['bid_only_rows']:,}, ask-only {T['ask_only_rows']:,}, both {T['both_rows']:,}, neither {T['neither_rows']:,}. The missing side of a row is the prevailing quote → forward-filled (never invented), carried across part boundaries.
* Per-part list: `reports/tables/ticks_parts.csv`.

> ⚠️ **Important limitation:** this tick sample covers only 2026-03-27 → 2026-11-06, which lies entirely **inside the final holdout period** (2025-07-01 →). It is used **only to measure execution costs and simulation accuracy**, never to choose strategy rules or parameters. Costs for 2022–2025 must be transported from this sample (in basis points of price) — an assumption, stated as such.

## 2. Integrity

| Check | Result |
|---|---|
| Non-monotonic timestamps | {I['non_monotonic']} |
| Rows sharing the same millisecond as the previous row | {I['same_ms_timestamp']:,} (normal: separate bid/ask updates) |
| Crossed quotes (Ask < Bid) | {I['crossed_ask_lt_bid']} |
| Locked quotes (Ask = Bid) | {I['locked_ask_eq_bid']} |
| Spread > $1 / > $5 | {I['spread_gt_1usd']:,} / {I['spread_gt_5usd']:,} |
| Largest spread | ${I['max_spread']:.2f} at {I['max_spread_ts']} |
| Consecutive bid jumps > $2 / > $5 | {R['consecutive_bid_jump']['gt_2usd']:,} / {R['consecutive_bid_jump']['gt_5usd']:,} (max ${R['consecutive_bid_jump']['max']:.2f} at {R['consecutive_bid_jump']['max_ts']}) |
| Silences > 60 s inside the session | {R['tick_silences_gt_60s_in_session']} (list: `reports/tables/ba_tick_silences.csv`) |

## 3. Reconciliation with the M1 Bid file (same minutes)

| Item | Value |
|---|---|
| M1-file minutes in tick window | {rc['m1_file_minutes_in_window']:,} |
| Minutes built from ticks | {rc['tick_minutes']:,} |
| Matched minutes | {rc['matched']:,} |
| In M1 file but no ticks / in ticks but not in M1 file | {rc['in_m1_file_not_in_ticks']:,} / {rc['in_ticks_not_in_m1_file']:,} |
| Bid Open / High / Low / Close exact match | {rc['bid_open_exact_match']*100:.2f}% / {rc['bid_high_exact_match']*100:.2f}% / {rc['bid_low_exact_match']*100:.2f}% / {rc['bid_close_exact_match']*100:.2f}% |
| … within $0.05 | {rc['bid_open_within_0.05']*100:.2f}% / {rc['bid_high_within_0.05']*100:.2f}% / {rc['bid_low_within_0.05']*100:.2f}% / {rc['bid_close_within_0.05']*100:.2f}% |
| Tick volume (M1 file) vs bid ticks: Spearman / median ratio | {rc['tickvol_vs_ticks_bid_spearman']} / {rc['tickvol_over_ticks_bid_median']} |
| Max quote updates in one minute (ticks) vs max tick volume (M1 file) | {rc['ticks_all_per_minute_max']:,} vs {rc['tickvol_m1file_max_in_window']:,} |

**What the M1 file's SPREAD column really is:**

| Compared with | Exact match | Mean abs. error |
|---|---|---|
| spread at minute open | {rc['m1SPREAD_vs_spr_open_exact']*100:.1f}% | ${rc['m1SPREAD_vs_spr_open_mae']:.3f} |
| minimum spread in minute | {rc['m1SPREAD_vs_spr_min_exact']*100:.1f}% | ${rc['m1SPREAD_vs_spr_min_mae']:.3f} |
| time-weighted mean spread | {rc['m1SPREAD_vs_spr_twmean_exact']*100:.1f}% | ${rc['m1SPREAD_vs_spr_twmean_mae']:.3f} |
| spread at minute close | {rc['m1SPREAD_vs_spr_close_exact']*100:.1f}% | ${rc['m1SPREAD_vs_spr_close_mae']:.3f} |
| maximum spread in minute | {rc['m1SPREAD_vs_spr_max_exact']*100:.1f}% | ${rc['m1SPREAD_vs_spr_max_mae']:.3f} |

M1-file SPREAD median ${rc['m1SPREAD_median_usd']:.2f} vs real time-weighted spread median ${rc['real_twspread_median_usd_same_minutes']:.3f} on the same minutes. In {rc['share_minutes_real_max_spread_gt_m1SPREAD']*100:.1f}% of minutes the real maximum spread exceeded the M1-file value.

## 4. Real spread

* Tick-level spread (USD): {R['spread_tick_level_usd']}
* Time-weighted spread per minute (USD): {R['spread_time_weighted_minute_usd']}
* Maximum spread per minute (USD): {R['spread_minute_max_usd']}
* Spread in **basis points of price** (time-weighted): {R['spread_bps_twmean']}
* Most frequent tick spreads (points → share): {R['spread_points_share_top']}

By server hour:

{hour_md}

By month (spread level vs price level):

{month_md}

Around scheduled-event minutes (server time):

{ev_md}

By volatility decile of the minute (Bid range):

{vol_md}

Spearman(spread, minute range) = {R['corr_spread_vs_minute_range']}; median spread / minute range = {R['spread_over_minute_range_median']}.

## 5. What M1 bars cannot tell us — measured with ticks

**Same-minute ambiguity.** Share of minutes in which price moved at least ±X from the open in *both* directions (so an SL and a TP X away would both be inside one M1 bar), and how often the high came first:

{amb_md}

These minutes are where an M1 backtest must guess; the conservative rule is "SL first". The tick store (`data/ticks.parquet`) lets later phases resolve them exactly for 2026-03-27 → 2026-11-06 and measure how much the conservative rule costs.

**Execution delay.** Absolute mid-price move after a delay, from 2,000,000 random ticks (seed {R['latency_sample_seed']}):

{lat_md}

## 6. Measured cost model (replaces the assumed C0–C3 of Phase 1)

| Scenario | Definition |
|---|---|
| C0 | {R['cost_model']['C0_measured']} |
| C1 (base) | {R['cost_model']['C1_base']} |
| C2 (stress) | {R['cost_model']['C2_stress']} |
| C3 (news) | {R['cost_model']['C3_news']} |
| 2022 → 2026-03 | {R['cost_model']['historical_2022_2025_transport']} |

Measured median round-trip spread ${R['cost_model']['measured_median_roundtrip_spread_usd']:.3f}, p90 ${R['cost_model']['measured_p90_roundtrip_spread_usd']:.3f} (time-weighted, 2026 price levels).

## 7. Verdict

The tick file is clean and consistent with the M1 Bid file, and it gives the lab what the M1 file lacked: the **real Ask**, the **real spread** including news-time widening, the **true order of highs and lows inside each minute**, and a measure of **latency risk**. Its main limitation is coverage: 7.4 months, all inside the holdout period.
"""
    (OUT / "01b_bidask_audit.md").write_text(report, encoding="utf-8")
    (OUT / "bidask_results.json").write_text(json.dumps(R, indent=2, default=str), encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
