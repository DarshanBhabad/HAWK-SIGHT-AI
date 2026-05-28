"""
optimizer.py — Our own Markowitz portfolio optimizer (Modern Portfolio Theory).

GOAL: from the user's favourite stocks, pick the COMBINATION + share quantities
that gives the best expected return per unit of risk (the max-Sharpe portfolio),
then hand it to the user to approve before any money moves.

WHY THIS IS MORE THAN THE OLD recommender.py:
The old engine scored each stock in isolation. This one understands how stocks
move TOGETHER (their covariance), so it can prefer a mix that diversifies risk
instead of piling into names that all rise and fall as one.

THE MATH (all implemented here by hand; scipy only does the numeric search):
  w   = weights (fraction of money in each stock)
  mu  = expected 3-month returns (from OUR price model)
  Sig = covariance matrix of returns (from price history) scaled to 3 months
  portfolio return = w . mu
  portfolio risk   = sqrt(w^T Sig w)
  Sharpe           = return / risk            (we maximise this)
  subject to:  sum(w) = 1,  0 <= w <= cap     (long-only, diversified)

HONEST GUARDRAILS (this project lives or dies on honesty):
  - Only stocks that clear a basic return + confidence bar are candidates.
  - Expected returns are CAPPED and SHRUNK toward their average, because
    Markowitz is notoriously sensitive to noisy return estimates. This stops
    it betting the farm on one over-optimistic number.
  - A hard per-stock weight cap forces diversification.
  - We never deploy more than MAX_DEPLOY_PCT of cash in one batch.
  - The output is an ESTIMATE shown for approval, never an auto-executed promise.
"""

import sys

# UTF-8 console so any status text doesn't crash a legacy Windows (cp1252) shell.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
from scipy.optimize import minimize

from longterm_model import LongTermPredictor, _fetch

# --- Tunables (chosen for the 3-month horizon; conservative on purpose) ---
HORIZON_DAYS = 63          # trading days in ~3 months (for scaling covariance)
HISTORY_PERIOD = "2y"      # how much price history to estimate co-movement from
MAX_DEPLOY_PCT = 0.50      # never spend more than 50% of cash in one batch
MAX_WEIGHT = 0.35          # never put more than 35% in a single stock (diversify)
MIN_CONFIDENCE = 0.55      # candidate must be >=55% likely to be higher
MIN_EXPECTED_RETURN = 2.0  # candidate's 3-month estimate must beat ~2% (costs)
RETURN_CAP_PCT = 25.0      # cap a single 3-month estimate at 25% (tame outliers)
RETURN_SHRINK = 0.60       # pull estimates 40% toward their mean (robustness)

# Trust tilt: steer the optimizer toward stocks the model genuinely reads well
# (high walk-forward AUC), while still letting weaker names in for diversification.
TRUST_AUC_FULL = 0.75      # walk-forward AUC at/above this = full trust
TRUST_MIN_FACTOR = 0.50    # an untrusted estimate (AUC<=0.5) is discounted to 50%
TRUST_MAX_FACTOR = 1.20    # a strongly-trusted estimate gets a 20% conviction bonus


# ----------------------------------------------------------------------------
# Data helpers
# ----------------------------------------------------------------------------
def _daily_returns(symbols: list[str]) -> "tuple[list[str], np.ndarray]":
    """
    Build a matrix of daily returns for the given symbols, aligned on common
    dates. Returns (symbols_kept, returns_matrix[T x N]). Symbols whose history
    can't be fetched are dropped (and reported back via symbols_kept).
    """
    import pandas as pd
    closes = {}
    for s in symbols:
        try:
            df = _fetch(s, period=HISTORY_PERIOD)
            closes[s] = df["Close"]
        except Exception:
            continue
    if not closes:
        return [], np.empty((0, 0))
    price = pd.DataFrame(closes).dropna()
    rets = price.pct_change().dropna()
    return list(rets.columns), rets.values


def _covariance_3m(returns: np.ndarray) -> np.ndarray:
    """Daily covariance scaled to the ~3-month horizon (i.i.d. approximation)."""
    if returns.shape[0] < 2:
        n = returns.shape[1]
        return np.eye(n) * 1e-4
    cov_daily = np.cov(returns, rowvar=False)
    cov_daily = np.atleast_2d(cov_daily)
    return cov_daily * HORIZON_DAYS


# ----------------------------------------------------------------------------
# The optimizer (max-Sharpe with constraints) — written by hand
# ----------------------------------------------------------------------------
def _max_sharpe_weights(mu: np.ndarray, cov: np.ndarray, max_weight: float) -> np.ndarray:
    """Find long-only weights that maximise Sharpe = (w.mu)/sqrt(w^T cov w)."""
    n = len(mu)
    if n == 1:
        return np.array([1.0])

    # If the cap is too tight to sum to 1 (cap*n < 1), loosen it just enough.
    cap = max(max_weight, 1.0 / n + 1e-9)

    def neg_sharpe(w):
        ret = float(w @ mu)
        var = float(w @ cov @ w)
        vol = np.sqrt(var) if var > 1e-12 else 1e-6
        return -ret / vol

    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
    bounds = [(0.0, cap)] * n
    w0 = np.repeat(1.0 / n, n)

    res = minimize(neg_sharpe, w0, method="SLSQP", bounds=bounds,
                   constraints=constraints, options={"maxiter": 500, "ftol": 1e-9})

    if not res.success or not np.isfinite(res.x).all():
        # Robust fallback: weight by positive expected return.
        w = np.clip(mu, 0, None)
        w = w if w.sum() > 0 else np.ones(n)
        return w / w.sum()

    w = np.clip(res.x, 0, None)
    return w / w.sum() if w.sum() > 0 else np.repeat(1.0 / n, n)


# ----------------------------------------------------------------------------
# Public: build the recommended combination
# ----------------------------------------------------------------------------
def optimize_portfolio(favorited_symbols: list[str], available_cash: float) -> dict:
    """
    Produce the max-Sharpe combination of the user's favourites + share counts.
    Returns a dict ready for the approve-then-buy UI.
    """
    out = {
        "picks": [],            # stocks we'd buy (symbol, shares, cost, weight, ...)
        "excluded": [],         # favourites left out, with the honest reason
        "total_investment": 0.0,
        "deployable_cash": round(available_cash * MAX_DEPLOY_PCT, 2),
        "expected_return_pct": 0.0,
        "expected_profit_value": 0.0,
        "expected_risk_pct": 0.0,
        "sharpe": 0.0,
        "leftover_cash": 0.0,
        "note": "",
    }
    if not favorited_symbols or available_cash <= 0:
        out["note"] = "No favourites or no cash to deploy."
        return out

    # --- Step 1: predict each favourite & gate to candidates ---
    candidates = []  # dicts with model info
    for sym in favorited_symbols:
        try:
            p = LongTermPredictor(sym).predict()
        except Exception as e:
            out["excluded"].append({"symbol": sym, "reason": f"No prediction ({e})"})
            continue
        er = p["expected_return_pct"]
        conf = p["confidence"]
        if er < MIN_EXPECTED_RETURN:
            out["excluded"].append({"symbol": sym,
                                    "reason": f"Estimate {er:+.1f}% too low to justify a trade"})
        elif conf < MIN_CONFIDENCE:
            out["excluded"].append({"symbol": sym,
                                    "reason": f"Confidence {conf*100:.0f}% below {int(MIN_CONFIDENCE*100)}%"})
        else:
            candidates.append({
                "symbol": sym,
                "expected_return_pct": er,
                "confidence": conf,
                "price": p["current_price"],
                "risk_level": p.get("volatility_level", "MEDIUM"),
                "trustworthy": bool(p.get("trustworthy", False)),
                "walk_forward_auc": float(p.get("walk_forward_auc", 0.5)),
            })

    if not candidates:
        out["note"] = "None of your favourites currently clear the buy bar — better to hold cash."
        return out

    # --- Step 2: covariance from history (aligned to candidate order) ---
    syms = [c["symbol"] for c in candidates]
    kept, rets = _daily_returns(syms)
    # keep only candidates we have history for, in the matrix's order
    if kept:
        candidates = sorted(candidates, key=lambda c: kept.index(c["symbol"])) \
            if set(syms) >= set(kept) else [c for c in candidates if c["symbol"] in kept]
        candidates = [c for c in candidates if c["symbol"] in kept]
        order = {s: i for i, s in enumerate(kept)}
        candidates.sort(key=lambda c: order[c["symbol"]])
        cov = _covariance_3m(rets)
    else:
        cov = np.eye(len(candidates)) * 1e-4

    n = len(candidates)
    prices = np.array([c["price"] for c in candidates], dtype=float)

    # --- Step 3: expected returns, capped, TRUST-TILTED, then shrunk (robust) ---
    mu_raw = np.array([min(c["expected_return_pct"], RETURN_CAP_PCT) / 100.0
                       for c in candidates])
    # Trust tilt: favour stocks the model genuinely reads well (walk-forward AUC).
    # Untrusted estimates are discounted, strongly-trusted ones get a small bonus.
    # NOTE: this steers ONLY the optimizer's weighting. The expected return we
    # DISPLAY later uses mu_raw (the honest, untilted model estimate).
    auc = np.array([c["walk_forward_auc"] for c in candidates])
    span = max(TRUST_AUC_FULL - 0.5, 1e-6)
    trust_factor = TRUST_MIN_FACTOR + np.clip((auc - 0.5) / span, 0.0, 1.0) \
        * (TRUST_MAX_FACTOR - TRUST_MIN_FACTOR)
    for c, tf in zip(candidates, trust_factor):
        c["trust_factor"] = round(float(tf), 2)
    mu_tilted = mu_raw * trust_factor
    t_mean = mu_tilted.mean()
    mu = t_mean + RETURN_SHRINK * (mu_tilted - t_mean)   # James–Stein-style shrink

    # --- Step 4: solve for the best combination ---
    if cov.shape != (n, n):
        cov = np.eye(n) * 1e-4
    weights = _max_sharpe_weights(mu, cov, MAX_WEIGHT)

    # --- Step 5: weights -> whole shares within the deployable budget ---
    deployable = available_cash * MAX_DEPLOY_PCT
    alloc_cash = weights * deployable
    shares = np.floor(np.divide(alloc_cash, prices, out=np.zeros_like(prices),
                                where=prices > 0)).astype(int)

    # Spend leftover cash greedily on the highest-conviction affordable stock.
    spent = float((shares * prices).sum())
    leftover = deployable - spent
    conviction = mu_tilted * np.array([c["confidence"] for c in candidates])
    for _ in range(50):
        affordable = [i for i in range(n) if prices[i] <= leftover + 1e-9]
        if not affordable:
            break
        i = max(affordable, key=lambda j: conviction[j])
        shares[i] += 1
        leftover -= prices[i]

    # --- Step 6: assemble picks + honest portfolio stats on realised weights ---
    realised_cash = shares * prices
    total = float(realised_cash.sum())
    for i, c in enumerate(candidates):
        if shares[i] <= 0:
            out["excluded"].append({"symbol": c["symbol"],
                                    "reason": "Allocation rounded below 1 share"})
            continue
        out["picks"].append({
            "symbol": c["symbol"],
            "shares": int(shares[i]),
            "price": round(c["price"], 2),
            "cost": round(float(realised_cash[i]), 2),
            "weight_pct": round(100.0 * realised_cash[i] / total, 1) if total > 0 else 0.0,
            "expected_return_pct": round(c["expected_return_pct"], 1),
            "confidence": round(c["confidence"], 3),
            "risk_level": c["risk_level"],
            "trustworthy": c["trustworthy"],
            "trust_factor": c.get("trust_factor", 1.0),
        })

    if total > 0:
        rw = realised_cash / total
        port_ret = float(rw @ mu_raw)                       # honest (capped) estimate
        port_var = float(rw @ cov @ rw)
        port_vol = float(np.sqrt(port_var)) if port_var > 0 else 0.0
        out["total_investment"] = round(total, 2)
        out["expected_return_pct"] = round(port_ret * 100, 1)
        out["expected_profit_value"] = round(total * port_ret, 2)
        out["expected_risk_pct"] = round(port_vol * 100, 1)
        out["sharpe"] = round(port_ret / port_vol, 2) if port_vol > 0 else 0.0

    out["leftover_cash"] = round(max(leftover, 0.0), 2)
    n_picks = len(out["picks"])
    out["note"] = (
        f"Best risk-adjusted mix of {n_picks} stock(s), chosen from "
        f"{len(favorited_symbols)} favourite(s) using how they move together. "
        f"Expected ~3-month return is an estimate, not a promise."
    )
    out["picks"].sort(key=lambda p: -p["weight_pct"])
    return out


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    favs = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA"]
    cash = 10000.0
    print(f"Optimising a ${cash:,.0f} portfolio from favourites: {favs}\n")
    r = optimize_portfolio(favs, cash)
    print("PICKS (the recommended combination):")
    for p in r["picks"]:
        tw = "[TRUSTED]" if p["trustworthy"] else ""
        print(f"  {p['symbol']:5} x{p['shares']:<4} @ ${p['price']:<8.2f} "
              f"= ${p['cost']:>9.2f}  ({p['weight_pct']:>4.1f}%)  "
              f"est {p['expected_return_pct']:+.1f}%  risk={p['risk_level']:<6} {tw}")
    print("\nEXCLUDED:")
    for e in r["excluded"]:
        print(f"  {e['symbol']:5} — {e['reason']}")
    print(f"\nTotal invested : ${r['total_investment']:,.2f}  (of ${r['deployable_cash']:,.2f} deployable)")
    print(f"Leftover cash  : ${r['leftover_cash']:,.2f}")
    print(f"Expected return: {r['expected_return_pct']:+.1f}%  (~${r['expected_profit_value']:,.2f})")
    print(f"Expected risk  : {r['expected_risk_pct']:.1f}%   Sharpe: {r['sharpe']}")
    print(f"\n{r['note']}")
