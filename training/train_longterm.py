"""
train_longterm.py — Train the honest 3-month "outlook" model for each stock.

This replaces the old "predict tomorrow" approach with "will it be higher in
~3 months?", which is a question that actually has a measurable answer.

It prints, for each stock:
  - the model's accuracy
  - the baseline ("it was simply up X% of the time anyway")
  - the model's REAL skill above that baseline (on data it never saw)
  - whether acting on it beat just buying and holding

Run:
    python training/train_longterm.py            # all default tickers
    python training/train_longterm.py AAPL MSFT  # specific tickers
"""

import os
import sys
import json

# Keep the ✅/⚠️ status output from crashing on a legacy Windows console (cp1252).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Make backend/ importable from training/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from longterm_model import LongTermPredictor, MODELS_DIR

DEFAULT_TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA"]


def main(tickers):
    results = []
    print("=" * 78)
    print("LONG-TERM OUTLOOK MODEL  —  'Will this stock be higher in ~3 months?'")
    print("=" * 78)

    for t in tickers:
        try:
            m = LongTermPredictor.train_and_save(t)
        except Exception as e:
            print(f"\n{t}: FAILED — {e}")
            results.append({"ticker": t, "error": str(e)})
            continue

        results.append(m)
        _tv = {"beats": "BEATS buy & hold", "matches": "matches buy & hold",
               "loses": "loses to buy & hold"}
        _rv = {"better": "BETTER risk-adjusted", "matches": "matches risk-adjusted",
               "worse": "worse risk-adjusted"}
        verdict = _tv.get(m["total_return_verdict"], m["total_return_verdict"])
        risk_verdict = _rv.get(m["risk_adjusted_verdict"], m["risk_adjusted_verdict"])
        useful = "✅ USEFUL" if m["useful"] else "⚠️  not yet useful"
        skill_pct = m["skill_above_baseline"] * 100
        signal = "✅ real ranking signal" if m.get("robust_signal") else "no robust edge"
        print(f"\n{t}   {useful}")
        print(f"  Accuracy: {m['model_accuracy']*100:.1f}%  "
              f"(it was simply up {m['base_rate_up']*100:.1f}% of the time anyway)")
        print(f"  Real skill above baseline: {skill_pct:+.1f}%   Brier: {m['brier_score']:.3f}")
        print(f"  Ranking quality (AUC): split {m.get('test_auc', 0.5):.3f}   "
              f"walk-forward {m.get('walk_forward_auc', 0.5):.3f}  ({m.get('walk_forward_folds', 0)} windows)  "
              f"-> {signal}")
        print(f"  Walk-forward skill (robust, {m.get('walk_forward_folds', 0)} windows): "
              f"{m.get('walk_forward_skill', 0.0)*100:+.1f}%")
        print(f"  Total return — Strategy: {m['strategy_return_pct']:+.1f}%   "
              f"Buy & hold: {m['buy_and_hold_return_pct']:+.1f}%   -> {verdict}")
        print(f"  Risk-adjusted — Sharpe {m['strategy_sharpe']:.2f} vs {m['buy_and_hold_sharpe']:.2f}   "
              f"MaxDD {m['strategy_max_drawdown_pct']:.0f}% vs {m['buy_and_hold_max_drawdown_pct']:.0f}%   "
              f"-> {risk_verdict}")

    # Save a combined summary
    with open(os.path.join(MODELS_DIR, "longterm_results.json"), "w") as f:
        json.dump(results, f, indent=2)

    valid = [r for r in results if "error" not in r]
    print("\n" + "=" * 78)
    if valid:
        avg_skill = sum(r["skill_above_baseline"] for r in valid) / len(valid) * 100
        avg_wf_skill = sum(r.get("walk_forward_skill", 0.0) for r in valid) / len(valid) * 100
        avg_wf_auc = sum(r.get("walk_forward_auc", 0.5) for r in valid) / len(valid)
        beats = sum(1 for r in valid if r["beats_buy_and_hold"])
        better_ra = sum(1 for r in valid if r["better_risk_adjusted"])
        robust = sum(1 for r in valid if r.get("robust_signal"))
        useful = sum(1 for r in valid if r["useful"])
        print(f"SUMMARY (single split): avg real skill above baseline = {avg_skill:+.1f}%")
        print(f"SUMMARY (walk-forward, robust): avg skill = {avg_wf_skill:+.1f}%   avg AUC = {avg_wf_auc:.3f}")
        print(f"  beat buy-and-hold (total return) on {beats}/{len(valid)} stocks")
        print(f"  better risk-adjusted (Sharpe + drawdown) on {better_ra}/{len(valid)} stocks")
        print(f"  real ranking signal (walk-forward AUC >= 0.55) on {robust}/{len(valid)} stocks")
        print(f"  flagged USEFUL on {useful}/{len(valid)} stocks")
        print("  Honest note: 3-month UP/DOWN skill is near 0 by nature (high base rate).")
        print("  The model's real value is AUC (ranking) + risk-adjusted timing, NOT direction.")
    print("=" * 78)


if __name__ == "__main__":
    tickers = [t.upper() for t in sys.argv[1:]] if len(sys.argv) > 1 else DEFAULT_TICKERS
    main(tickers)
