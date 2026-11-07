"""Builds reports/07_final_holdout.md and the equity figure from src/holdout.py outputs."""
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from audit import md_table
from load import ROOT

TAB, FIG = ROOT / "reports" / "tables", ROOT / "reports" / "figures"
INK, MUTED, SURFACE, S1, S2 = "#1f1f1e", "#6b6a66", "#fcfcfb", "#2a78d6", "#eb6834"


def main():
    R = pd.read_csv(TAB / "holdout_summary.csv")
    T = pd.read_csv(TAB / "holdout_trades.csv", parse_dates=["entry_day", "exit_day"])
    E = pd.read_csv(TAB / "holdout_equity.csv", parse_dates=[0], index_col=0)
    J = json.load(open(ROOT / "reports" / "holdout_results.json"))
    pref = J["price_ref"]
    T["pnl_$/oz"] = T.exit - T.entry
    T["R"] = T["pnl_$/oz"] / T.risk
    T["return_%"] = T["pnl_$/oz"] / pref * 100
    T["days"] = (T.exit_day - T.entry_day).dt.days
    top_share = T["pnl_$/oz"].max() / T["pnl_$/oz"].sum()

    fig, ax = plt.subplots(figsize=(9, 4.4), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    for s in ["left", "bottom"]:
        ax.spines[s].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.yaxis.grid(True, color="#e6e5e1", linewidth=0.6)
    ax.plot(E.index, E["buy_hold_%"], color=S2, lw=2, label="Buy & hold")
    ax.plot(E.index, E["xae_swing_%"], color=S1, lw=2, label="XAE-Swing v1")
    for col, c in [("xae_swing_%", S1), ("buy_hold_%", S2)]:
        ax.annotate(f"{E[col].iloc[-1]:+.1f}%", (E.index[-1], E[col].iloc[-1]), xytext=(6, 0), textcoords="offset points", color=INK, fontsize=8.5, va="center")
    ax.axhline(0, color=MUTED, lw=0.8)
    ax.set_ylabel("cumulative return, % of avg. price (1× notional)", fontsize=8, color=MUTED)
    ax.set_title("Final untouched holdout 2025-07 → 2026-11 — after costs and CFI swap", fontsize=9.5, color=INK, loc="left")
    ax.legend(frameon=False, fontsize=8.5, loc="upper left")
    fig.tight_layout()
    fig.savefig(FIG / "holdout_equity.png", dpi=150, facecolor=SURFACE)
    plt.close(fig)

    base = R[(R["mode"] == "continuous") & R.scenario.str.startswith("base")].iloc[0]
    bh = R[R["mode"] == "benchmark"].iloc[0]
    n = J["null"]
    rep = f"""# Phase 7 — Final untouched holdout test (single run)

_Rules: `rules/xae_swing_v1.json`, frozen before this run. Code: `src/holdout.py` (run once), report `src/holdout_report.py`._
_One code defect was found and fixed after the run: the **buy-and-hold benchmark** had accidentally been given the strategy's trailing stop. This changed only the benchmark row; the strategy rules and its numbers are unchanged._

## 0. Plain-language result

* On data it had never seen (2025-07-01 → 2026-11-06, {J['holdout'][0]} to {J['holdout'][1]}), the frozen **XAE-Swing v1** returned **{base['total_return_%']:+.1f}%** (1× notional, after costs and the real CFI swap), with a maximum drawdown of **{base['maxDD_%']:.1f}%**, invested {base['exposure_%']:.0f}% of the time.
* Buy-and-hold over the same period returned **{bh['total_return_%']:+.1f}%** with a **{bh['maxDD_%']:.1f}%** drawdown. The system stayed **flat through the peak and the crash of the first half of 2026**.
* Versus random long timing with the same trade lengths: p = **{n['p_value']:.3f}** (random median {n['random_median_%']:+.1f}%, 95th percentile {n['random_p95_%']:+.1f}%).
* **But only {int(base.trades)} trades**, and one trade (Aug → Oct 2025) produced {top_share * 100:.0f}% of the profit. The result is **consistent with the research, not proof by itself**.

![equity](figures/holdout_equity.png)

## 1. Results

{md_table(R.round(2), "{:.2f}")}

(‘continuous’ and ‘fresh start’ are identical because the system happened to be flat on 2025-07-01.)

## 2. Every holdout trade

{md_table(T[["entry_day", "exit_day", "days", "entry", "exit", "pnl_$/oz", "R", "return_%", "reason"]].astype({"entry_day": str, "exit_day": str}).round(2), "{:.2f}")}

P&L by quarter (% of average price): {J['by_quarter_%']}

Trade P&L above is price only; the totals in §1 also include swap.

## 3. Known behaviour revealed by the holdout (not changed — rules stay frozen)

After the stop-out on 2025-12-29 the frozen rule `re_entry_after_stop` kept the system flat until a close below the 10-day low. That never happened during the January 2026 advance (daily close ≈ $4,333 on 2026-01-02 → ≈ $5,417 on 2026-01-28), so the system **missed that rally**, and for the same reason it was also **out during the subsequent fall**. In this window the rule was neutral-to-helpful; in a steadier trend it would cost money. Any change to it is a *v2* idea that can only be judged on **new data (paper trading)**, never on this holdout.

## 4. Verdict

| Question | Answer |
|---|---|
| Did the frozen rules make money out of sample? | Yes: {base['total_return_%']:+.1f}% (stress costs + 8% swap: {R[(R['mode'] == 'continuous') & R.scenario.str.startswith('stress')]['total_return_%'].iloc[0]:+.1f}%) |
| Better risk-adjusted than holding gold? | Yes in this window: Sharpe {base.sharpe:.2f} vs {bh.sharpe:.2f}; drawdown {base['maxDD_%']:.1f}% vs {bh['maxDD_%']:.1f}% |
| Statistically conclusive? | **No.** {int(base.trades)} trades; most profit from one trade. Combined with research (21 trades, p ≈ 0.06) the evidence is encouraging but small. |
| Ready for real money? | **Not yet.** Next: risk/position sizing (Phase 8), then forward paper trading with pre-set pass/fail criteria (Phase 9). |

**Executive verdict: REVISE → proceed to paper trading.** XAE-Swing v1 is the only idea out of ≈ 140 tested that survived development, robustness and the untouched holdout. It is a slow, low-frequency system (≈ 4–5 trades a year), not the daily scalping system originally hoped for — the data did not support one after realistic costs.
"""
    (ROOT / "reports" / "07_final_holdout.md").write_text(rep, encoding="utf-8")
    print("ok", top_share)


if __name__ == "__main__":
    main()
