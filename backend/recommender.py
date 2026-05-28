"""
recommender.py — Portfolio recommendation entry point.

WHAT CHANGED:
The heavy lifting now lives in optimizer.py, which uses Modern Portfolio Theory
(Markowitz max-Sharpe) to choose the best COMBINATION of the user's favourites
— considering how the stocks move together (covariance) and tilting toward the
names the model genuinely reads well (walk-forward AUC). The old version here
scored each stock in isolation and could not see diversification.

This module is now a thin ADAPTER: it calls the optimizer and returns the result
in BOTH shapes:
  - the legacy "recommendations" list (so /execute_recommendations, the autobuy
    audit log, and the existing UI keep working unchanged), and
  - the richer MPT fields (picks, sharpe, expected_risk_pct, excluded, ...) for
    the upgraded Auto-Buy screen.
"""

import optimizer


def recommend_portfolio(favorited_symbols: list[str], available_cash: float) -> dict:
    """
    Build the recommended buy combination for a user.

    Returns a dict containing both the legacy keys (recommendations,
    total_investment, estimated_return) and the new MPT keys (picks, excluded,
    expected_return_pct, expected_risk_pct, sharpe, leftover_cash, note).
    """
    opt = optimizer.optimize_portfolio(favorited_symbols, available_cash)

    # --- Map the optimizer output onto the legacy "recommendations" shape ---
    recommendations = []
    for p in opt["picks"]:
        recommendations.append({
            "symbol": p["symbol"],
            "action": "BUY",
            "shares": p["shares"],
            "total_cost": p["cost"],
            "predicted_return": p["expected_return_pct"],
            "confidence": p.get("confidence", 0.0),
            "risk_level": p["risk_level"],
            "score": p["weight_pct"],          # legacy "score" -> portfolio weight
            "weight_pct": p["weight_pct"],
            "trustworthy": p.get("trustworthy", False),
            "reason": "",
        })
    for e in opt["excluded"]:
        recommendations.append({
            "symbol": e["symbol"],
            "action": "SKIP",
            "shares": 0,
            "total_cost": 0.0,
            "predicted_return": 0.0,
            "confidence": 0.0,
            "risk_level": "MEDIUM",
            "score": 0.0,
            "reason": e["reason"],
        })

    return {
        # --- legacy keys (back-compat) ---
        "recommendations": recommendations,
        "total_investment": opt["total_investment"],
        "estimated_return": opt["expected_profit_value"],
        # --- new MPT keys (for the upgraded UI) ---
        "picks": opt["picks"],
        "excluded": opt["excluded"],
        "deployable_cash": opt["deployable_cash"],
        "expected_return_pct": opt["expected_return_pct"],
        "expected_profit_value": opt["expected_profit_value"],
        "expected_risk_pct": opt["expected_risk_pct"],
        "sharpe": opt["sharpe"],
        "leftover_cash": opt["leftover_cash"],
        "note": opt["note"],
    }
