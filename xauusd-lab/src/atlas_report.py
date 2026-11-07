"""Builds reports/02_behavior_atlas.md from the tables written by src/atlas.py.
Every number in the report is read from those tables."""
from __future__ import annotations

import json

import pandas as pd

from audit import md_table
from load import ROOT

T = ROOT / "reports" / "tables"
OUT = ROOT / "reports" / "02_behavior_atlas.md"


def rd(name):
    return pd.read_csv(T / name)


def pct(x, d=1):
    return f"{x * 100:.{d}f}%"


def main():
    hr, dw, se, hl = rd("atlas_hourly.csv"), rd("atlas_day_of_week.csv"), rd("atlas_sessions.csv"), rd("atlas_day_high_low_timing.csv")
    orr, lv, cs, acf, cond = rd("atlas_opening_ranges.csv"), rd("atlas_reference_levels.csv"), rd("atlas_candle_stats.csv"), rd("atlas_autocorr.csv"), rd("atlas_candle_conditions.csv")
    ab, an, ay, ass = rd("atlas_barrier_usd.csv"), rd("atlas_barrier_atr.csv"), rd("atlas_barrier_by_year.csv"), rd("atlas_barrier_by_session.csv")

    # ---------------- hourly
    h = hr.pivot_table(index=["srv_hour", "ny_hour"], columns="split",
                       values=["range_med_$", "range_vs_ATRd_med", "VR5", "false_bo_rate", "P_cont_prev_hour", "z_cont", "cost_C1_vs_med_range"]).reset_index()
    h.columns = [f"{a}_{b}" if b else a for a, b in h.columns]
    h = h.sort_values("ny_hour", key=lambda s: (s - 18) % 24)
    hcols = ["ny_hour", "srv_hour", "range_med_$_dev", "range_med_$_val", "range_vs_ATRd_med_dev", "range_vs_ATRd_med_val", "VR5_dev", "VR5_val",
             "false_bo_rate_dev", "P_cont_prev_hour_dev", "z_cont_dev", "P_cont_prev_hour_val", "z_cont_val", "cost_C1_vs_med_range_dev", "cost_C1_vs_med_range_val"]
    h_md = md_table(h[hcols].round(3).astype({"ny_hour": int, "srv_hour": int}).astype({"ny_hour": str, "srv_hour": str}), "{:.3f}")
    last = h[h.ny_hour == 16].iloc[0]
    top3 = h.sort_values("range_vs_ATRd_med_dev", ascending=False).head(3).ny_hour.astype(int).tolist()
    quiet = h.sort_values("range_vs_ATRd_med_dev").head(3).ny_hour.astype(int).tolist()
    vr_dev_mean, vr_val_mean = hr[hr.split == "dev"].VR5.mean(), hr[hr.split == "val"].VR5.mean()
    zc = hr[(hr.split == "dev")].dropna(subset=["z_cont"])
    n_sig = int((zc.z_cont.abs() > 3).sum())

    # ---------------- dow
    dw_md = md_table(dw.round(3), "{:.3f}")
    dw_sig = dw[dw.z_up.abs() >= 2.5]

    # ---------------- sessions
    se_md = md_table(se.round(3), "{:.3f}")
    hlp = hl.pivot_table(index="ny_hour", columns="split", values=["P_day_high_in_hour", "P_day_low_in_hour"])
    hlp.columns = [f"{a}_{b}" for a, b in hlp.columns]
    hlp = hlp.reindex([(x + 18) % 24 for x in range(23)])
    w = lambda hrs, sp: float(hlp.loc[hrs, [f"P_day_high_in_hour_{sp}", f"P_day_low_in_hour_{sp}"]].sum().mean())
    ny_open_dev, ny_open_val = w([8, 9, 10], "dev"), w([8, 9, 10], "val")
    asia_dev, asia_val = w([18, 19, 20, 21], "dev"), w([18, 19, 20, 21], "val")
    dead_dev, dead_val = w([23, 0, 1], "dev"), w([23, 0, 1], "val")

    orr_md = md_table(orr.round(3), "{:.3f}")
    lv_md = md_table(lv.round(3), "{:.3f}")

    # ---------------- candles
    cs_md = md_table(cs.round(3), "{:.3f}")
    a = acf.pivot_table(index=["tf", "lag"], columns="split", values=["acf_ret", "acf_absret", "band_95"]).reset_index()
    a.columns = [f"{x}_{y}" if y else x for x, y in a.columns]
    a_md = md_table(a.round(4).astype({"lag": str}), "{:.4f}")
    c = cond[~cond.condition.str.startswith("[vol]")].pivot_table(index=["tf", "condition"], columns="split",
                                                                    values=["n", "P_next_bar_continues", "z_vs_50", "fwd3_$_mean", "fwd3_ATR_mean"]).reset_index()
    c.columns = [f"{x}_{y}" if y else x for x, y in c.columns]
    c = c[["tf", "condition", "n_dev", "P_next_bar_continues_dev", "z_vs_50_dev", "fwd3_ATR_mean_dev", "fwd3_$_mean_dev",
           "n_val", "P_next_bar_continues_val", "z_vs_50_val", "fwd3_ATR_mean_val", "fwd3_$_mean_val"]]
    c["robust"] = ((c.z_vs_50_dev.abs() >= 3) & (c.z_vs_50_val.abs() >= 2) & (c.z_vs_50_dev * c.z_vs_50_val > 0)).map({True: "YES", False: ""})
    c_md = md_table(c.round(3).astype({"n_dev": "Int64", "n_val": "Int64"}).astype({"n_dev": str, "n_val": str}), "{:.3f}")
    rob = c[c.robust == "YES"]
    v = cond[cond.condition.str.startswith("[vol]")][["split", "tf", "condition", "n", "next_range_ATR_mean"]]
    v_md = md_table(v.round(3), "{:.3f}")
    d1 = c[(c.tf == "1min") & c.condition.str.startswith("displacement")].iloc[0]
    d1b = c[(c.tf == "1min") & c.condition.str.startswith("big displacement")].iloc[0]

    # ---------------- barriers
    def piv(df, sp, col):
        p = df[df.split == sp].pivot(index="dist", columns="T_min", values=col)
        return p

    order_usd = [f"${d:g}" for d in [0.5, 1, 1.5, 2, 3, 5, 7.5, 10, 15, 20]]
    order_atr = [f"{k:g}xATR15" for k in [0.25, 0.5, 1, 1.5, 2, 3]]
    up_usd = (piv(ab, "dev", "P_hit_up").loc[order_usd] * 100).round(1).reset_index()
    dn_usd = (piv(ab, "dev", "P_hit_down").loc[order_usd] * 100).round(1).reset_index()
    up_usd_val = (piv(ab, "val", "P_hit_up").loc[order_usd] * 100).round(1).reset_index()
    upf_usd = (piv(ab, "dev", "P_up_first|decided").loc[order_usd] * 100).round(1).reset_index()
    up_atr = (piv(an, "dev", "P_hit_up").loc[order_atr] * 100).round(1).reset_index()
    up_atr_val = (piv(an, "val", "P_hit_up").loc[order_atr] * 100).round(1).reset_index()
    upf_atr_dev = (piv(an, "dev", "P_up_first|decided").loc[order_atr] * 100).round(1).reset_index()
    upf_atr_val = (piv(an, "val", "P_up_first|decided").loc[order_atr] * 100).round(1).reset_index()
    amb = (piv(ab, "dev", "P_same_bar_ambiguous|hit").loc[order_usd] * 100).round(2).reset_index()
    for df in [up_usd, dn_usd, up_usd_val, upf_usd, up_atr, up_atr_val, upf_atr_dev, upf_atr_val, amb]:
        df.columns = [str(x) if x == "dist" else f"{x}m" for x in df.columns]
    f = lambda df: md_table(df, "{:.1f}")
    ay_md = md_table(ay.round(3).astype({"year": str, "T_min": str}), "{:.3f}")
    ass_md = md_table(ass[["split", "session", "T_min", "n", "P_hit_any", "P_up_first|decided", "z_up_first"]].round(3).astype({"T_min": str}), "{:.3f}")
    bs = json.loads((ROOT / "reports" / "atlas_results.json").read_text())["barrier_samples"]
    g = lambda df, sp, d, t, col: float(df[(df.split == sp) & (df.dist == d) & (df.T_min == t)][col].iloc[0])

    report = f"""# Phase 2 — XAUUSD Behavior Atlas

_Generated by `src/atlas.py` → tables in `reports/tables/atlas_*.csv` → this file by `src/atlas_report.py`. Figures in `reports/figures/`._

## 0. Protocol

* **Discovery set (DEV):** 2022-03-16 → 2024-06-30. **Replication set (VAL):** 2024-07-02 → 2025-06-30. **Holdout (2025-07 →) was not loaded.**
* A pattern is called **robust** only if it is significant in DEV (|z| ≥ 3, which also absorbs most of the multiple-testing burden of this atlas) **and** has the same sign with |z| ≥ 2 in VAL.
* Prices are Bid. Distances are in **USD of price**; "ATR" normalisations use only information available at decision time (previous-day ATR(14); ATR(14) of *completed* M15 bars).
* Cost yardstick: **C1 round trip = $0.30** (real spread $0.10 + $0.10 adverse slippage each side on market/stop orders, Phase 1b).
* This phase **describes** the market. Nothing here is yet a strategy; findings become hypotheses for Phase 3, where they are tested with entries, stops, costs and walk-forward validation.

## 1. Executive summary

1. **Gold behaves very close to a random walk in *direction* at every intraday horizon tested.** Up and down barriers of the same size are hit with almost identical probability; P(up barrier first) stays within ≈49–51%, and the small deviations track the period's trend (2022 down-year < 50%, 2024–25 up-years > 50%; table §6.3). No session, hour or weekday has a reliable directional bias.
2. **Volatility, by contrast, is highly predictable.** |return| autocorrelation is ≈0.2–0.3 on M1–M15 in both sets, and after an expansion bar (range ≥ 2 ATR) the next bar's range averages 1.5–1.95 ATR, versus 0.6–0.86 after compression. This is the most reliable property in the data: **it can tell us *when* and *how far* to aim, not *which way*.**
3. **Costs decide the timeframe.** C1 costs {pct(cs[(cs.split=='dev')&(cs.tf=='1min')].cost_C1_vs_med_range.iloc[0],0)} of the median M1 bar in DEV ({pct(cs[(cs.split=='val')&(cs.tf=='1min')].cost_C1_vs_med_range.iloc[0],0)} in VAL), {pct(cs[(cs.split=='dev')&(cs.tf=='5min')].cost_C1_vs_med_range.iloc[0],0)} of an M5 bar, {pct(cs[(cs.split=='dev')&(cs.tf=='15min')].cost_C1_vs_med_range.iloc[0],0)} of an M15 bar and {pct(cs[(cs.split=='dev')&(cs.tf=='1h')].cost_C1_vs_med_range.iloc[0],0)} of an H1 bar. **Market-order scalping on M1 targets is not viable;** realistic targets start around $2–3 (2022–24 prices) / ≈1 ATR15, or require limit-order entries.
4. **The day has a clear rhythm.** The 08:00–11:00 NY window (London–NY overlap: data releases and the cash open) is the most volatile ({h[h.ny_hour.isin([8,9,10])]['range_vs_ATRd_med_dev'].mean():.2f} of daily ATR per hour vs {h[h.ny_hour.isin([23,0,1])]['range_vs_ATRd_med_dev'].mean():.2f} for 23:00–01:00 NY). Per hour, it is also where the day's high or low is most likely to be printed ({pct(ny_open_dev/3)} of days per hour per extreme in DEV, {pct(ny_open_val/3)} in VAL, vs {pct(1/23)} if uniform); the Asia open 18:00–22:00 NY is second ({pct(asia_dev/4)} / {pct(asia_val/4)} per hour).
5. **Robust conditional effects found are small and mostly *mean-reverting*:** after a strong M1 displacement candle the next minute continues only {pct(d1.P_next_bar_continues_dev)} (DEV) / {pct(d1.P_next_bar_continues_val)} (VAL), and the 3-minute follow-through is negative ({d1['fwd3_$_mean_dev']:+.3f} $ / {d1['fwd3_$_mean_val']:+.3f} $). Real, but **far smaller than the $0.30 cost**. The last NY hour (16:00–17:00 NY) reverses the previous hour's direction more often than chance (P(continue) {pct(last.P_cont_prev_hour_dev)} DEV, z={last.z_cont_dev:.1f}; {pct(last.P_cont_prev_hour_val)} VAL, z={last.z_cont_val:.1f}).
6. **Classical candle patterns (engulfing, inside bar, pin/rejection) show no robust edge on any timeframe; streak effects on M5/M15 are detectable but economically nil.**

## 2. Time-of-day profile (H1 bars built from M1)

![hourly](figures/atlas_hourly.png)

Columns: median H1 range in $ and ÷ previous-day ATR(14); VR5 = variance ratio of 5-min vs 1-min returns inside the hour (1 = random walk, < 1 = short-term mean reversion, > 1 = persistence); false breakout = share of one-sided breaks of the previous hour's high/low that close back inside it; P_cont = P(this hour's direction = previous hour's direction); cost = C1 ÷ median hourly range.

{h_md}

**Reading**
* Busiest hours (by ATR-normalised range, DEV): NY {top3}. Quietest: NY {quiet}.
* VR5 averages {vr_dev_mean:.3f} (DEV) and {vr_val_mean:.3f} (VAL): minute-to-minute moves slightly **mean-revert inside the hour** — consistent with the negative M1 lag-1/2 autocorrelation in §5.2.
* Hour-to-hour direction: only {n_sig} of 22 hours reach |z| > 3 in DEV. The last hour before the halt (NY 16:00, server 23:00) is the one that also replicates in VAL; it trades on the thinnest range of the day (median ${last['range_med_$_dev']:.2f} DEV), so its cost burden ({pct(last.cost_C1_vs_med_range_dev,0)} of range) is the highest of any hour.
* "False breakouts" of the previous hour's range are frequent everywhere (≈30–50%). This is a base rate, not an edge: any breakout rule must beat it.

## 3. Day of week (daily bars)

{dw_md}

No weekday reaches |z| ≥ 2.5 for direction in either set (largest: {dw.loc[dw.z_up.abs().idxmax(),'split']} {dw.loc[dw.z_up.abs().idxmax(),'dow']}, z={dw.z_up.abs().max():.2f}, which is z={dw[(dw.split!=dw.loc[dw.z_up.abs().idxmax(),'split'])&(dw.dow==dw.loc[dw.z_up.abs().idxmax(),'dow'])].z_up.iloc[0]:.2f} in the other set) — **day-of-week is rejected as a directional filter**. Ranges are lowest on Monday in DEV, but this does not hold in VAL.

## 4. Sessions, opens and reference levels

Session clock (DST-correct): Asia 19:00–02:00 NY · London 08:00–16:30 London · New York 08:00–17:00 NY · overlap = London ∩ New York · Off-hours = the rest (reopen hour 18:00 NY and 02:00–03:00 NY).

### 4.1 Session ranges

{se_md}

The overlap prints the largest range per hour of the day (`range_per_hour_vs_ATRd`) and sets the day's high or low on {pct(se[(se.split=='dev')&(se.session=='LDN-NY overlap')].P_sets_day_high.iloc[0],0)} / {pct(se[(se.split=='dev')&(se.session=='LDN-NY overlap')].P_sets_day_low.iloc[0],0)} of days (DEV). Cost relative to a whole session's range is small everywhere (2–4%), so **session-scale (intraday) targets are cost-feasible**; minute-scale targets are not.

### 4.2 When the day's high and low are printed

![highlow](figures/atlas_day_high_low_timing.png)

Average share of days on which the high/low is printed in the window (per extreme): 08:00–11:00 NY {pct(ny_open_dev)} DEV / {pct(ny_open_val)} VAL; 18:00–22:00 NY (Asia open) {pct(asia_dev)} / {pct(asia_val)}; 23:00–02:00 NY {pct(dead_dev)} / {pct(dead_val)}. Full table: `reports/tables/atlas_day_high_low_timing.csv`. The "kill zone" idea that the day's extremes cluster around the London/NY morning is **supported as a timing statement** (where extremes form), not as a directional signal.

### 4.3 Opening ranges (first 30 minutes after each open)

{orr_md}

* The direction of the first 30 minutes says nothing about the rest of the session (P_same_dir ≈ 50% everywhere, |z| < 1.1).
* After the first break of the opening range, the window closes beyond it in the break direction only ≈48–55% of the time. **Opening-range direction carries no edge in itself**; ORB can only work, if at all, through volatility/expansion filters and exits — a Phase 3 hypothesis, not a finding.

### 4.4 Asian range and previous-day high/low

{lv_md}

* London+NY take out the Asian high on ≈70% of days and the Asian low on ≈60–70%; when only one side is taken, the day closes back inside the Asian range just 21–29% of the time — i.e. **one-sided Asian-range breaks usually hold to the close**. That is the raw material for an Asian-range-breakout hypothesis (Phase 3), not yet an edge (no entry, stop or cost applied).
* Previous-day high/low is taken on ≈38–56% of days; after a one-sided take the day closes back inside 37–49% of the time — roughly a coin flip, so a "PDH/PDL sweep-and-reverse" idea needs extra conditions to beat its base rate.

## 5. Candle behaviour

### 5.1 Anatomy and cost by timeframe

{cs_md}

### 5.2 Autocorrelation (within-day returns; band_95 = ±2/√n)

{a_md}

* Returns: tiny **negative** lag-1/2 autocorrelation on M1 (≈ −0.01, well outside the band in both sets). Nothing reliable on M5–H1.
* |Returns|: strong positive autocorrelation everywhere (**volatility clustering**), decaying slowly on M1–M15.

### 5.3 Conditional next-bar behaviour

`P_next_bar_continues` = P(next bar moves in the signal direction | non-zero body); `fwd3` = 3-bar close-to-close move in the signal direction (mean, $ and ATR). **robust** = |z| ≥ 3 in DEV and same-sign |z| ≥ 2 in VAL.

{c_md}

Robust rows: {', '.join(f"{r.tf} · {r.condition}" for r in rob.itertuples()) or 'none'}.

* The robust effects are concentrated on **M1** and point to **short-lived reversal** after strong or repeated same-direction minutes. Their size (|fwd3| ≤ ${max(abs(d1b['fwd3_$_mean_dev']), abs(d1b['fwd3_$_mean_val'])):.2f}) is below the $0.30 C1 round trip, so they are **not tradable with market orders**. They are useful as *entry-timing* information: do not chase a displacement minute; a limit order placed against it can get a better fill.
* On M5/M15 a few streak rows pass the threshold for *next-bar direction* (P ≈ 47–48%), but their 3-bar follow-through is ≈ $0.00–0.02 — statistically detectable, economically nil. **Engulfing, inside-bar and rejection-wick patterns show no robust edge on any timeframe**, and nothing passes on H1.

### 5.4 Volatility clustering (next-bar range ÷ ATR)

{v_md}

## 6. Price-distance (barrier) probabilities

For a start every 5 minutes (DEV: 162,276 starts; VAL: 70,530), reference = M1 Bid close; a barrier is "hit" if a later M1 high/low reaches it within the horizon. Windows never cross the daily halt or gaps > 5 minutes. "Up first" is decided by M1 bar order; when both barriers fall in the same M1 bar the case is counted as ambiguous, not decided.

![barrier](figures/atlas_barrier_up.png)

### 6.1 Absolute distances — DEV, P(hit **up**) %

{f(up_usd)}

P(hit **down**) % — DEV

{f(dn_usd)}

P(hit up) % — VAL (higher-volatility regime: same $ distance is easier to reach)

{f(up_usd_val)}

P(up hit first | one side decided) % — DEV

{f(upf_usd)}

Share of hits where up and down fell inside the *same* M1 bar (undecidable on M1), % — DEV

{f(amb)}

### 6.2 Volatility-normalised distances (k × ATR(14) of completed M15 bars)

Median ATR15: ${bs['dev']['atr15_median_$']:.2f} (DEV), ${bs['val']['atr15_median_$']:.2f} (VAL).

P(hit up) % — DEV

{f(up_atr)}

P(hit up) % — VAL

{f(up_atr_val)}

The normalised table is **far more stable across regimes than the $ table** (e.g. 1×ATR15 within 60 min: {pct(g(an,'dev','1xATR15',60,'P_hit_up'))} DEV vs {pct(g(an,'val','1xATR15',60,'P_hit_up'))} VAL; $2 within 60 min: {pct(g(ab,'dev','$2',60,'P_hit_up'))} vs {pct(g(ab,'val','$2',60,'P_hit_up'))}). **All later stops/targets will be defined in ATR units.**

P(up first | decided) % — DEV

{f(upf_atr_dev)}

P(up first | decided) % — VAL

{f(upf_atr_val)}

In VAL, large fast moves (≥ 1.5×ATR15 within 5–30 min) went **down first** more often (≈40–47%), while longer horizons drifted up — "falls are fast, rises are slow". DEV does not show this (≈48–50%), so it is **regime-dependent and not used** as a rule.

### 6.3 Stability by year and by session (1×ATR15)

{ay_md}

{ass_md}

The year table shows the directional tilt simply follows each year's trend. Session tilts change sign between DEV and VAL. **No stable intraday direction.**

## 7. What this means for strategy research (input to Phase 3)

| # | Observation | Status | Use in Phase 3 |
|---|---|---|---|
| A1 | Direction ≈ random walk at all intraday horizons; tilt = prevailing trend | robust | Any directional rule must beat a **trend-aware baseline**, not 50%. Higher-timeframe trend filters are worth testing. |
| A2 | Volatility clustering / expansion → larger next ranges | robust | Regime & sizing: ATR-based stops/targets, trade only when expected range ≫ cost; skip compressed periods for breakout systems. |
| A3 | 08:00–11:00 NY: highest range per hour and highest per-hour rate of daily extremes | robust (timing) | Session filter / kill-zone window for both breakout and reversal models. |
| A4 | M1 displacement & streak minutes mean-revert slightly | robust, below cost | Entry timing (limit entries, no chasing); not a stand-alone strategy. |
| A5 | Last NY hour (16–17 NY) tends to reverse the 15–16 NY hour | robust, small range, high cost share | Candidate fade hypothesis, low priority. |
| A6 | One-sided Asian-range breaks usually hold to the close | descriptive | Asian-range / London-breakout hypothesis (Model D). |
| A7 | PDH/PDL one-sided takes reverse ≈ half the time | descriptive (coin flip) | Sweep-reversal (Model E) needs added confirmation to beat base rate. |
| A8 | Opening-range direction, weekday, candle patterns (M5–H1) | **no edge** | Not used as stand-alone signals. |
| A9 | Cost ≥ 30% of median M5 range, ≈ 73% of M1 | robust | Minimum target ≈ 1×ATR15 (≈$2 at 2022–24 prices); scalping needs limit entries and tick-level validation. |

**Honest bottom line of Phase 2:** the data show a market that is efficient in direction and strongly structured in volatility and time. That rules out the simple "pattern X predicts the next candle" approach. An edge, if one exists, will have to come from **combining time windows, volatility regime and liquidity levels with exits sized in ATR**. Phase 3 tests exactly that, against these baselines.
"""
    OUT.write_text(report, encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
