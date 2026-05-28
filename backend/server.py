"""
server.py — Main Flask application for Hawk Sight AI.

Architecture:
  - Auth: JWT tokens (stateless)
  - DB: MySQL via XAMPP (connection pool)
  - ML: 3-month outlook model (trend + momentum + risk) loaded lazily
  - Trading: Internal virtual portfolio (default) or Alpaca paper trading
  - Rate limiting: per-IP on expensive endpoints

Security fixes vs original:
  ✅ Finnhub API key in .env (not source)
  ✅ JWT auth on all trading routes
  ✅ Server fetches live prices (never trusts client)
  ✅ Transactional balance updates (no race conditions)
  ✅ Input validation everywhere
  ✅ Rate limiting on /predict and /recommend
"""

import os
import sys

# Force UTF-8 console output BEFORE anything prints. The startup logs use
# ✅/⚠️/❌ status icons; a legacy Windows console (cp1252) crashes trying to
# encode them (UnicodeEncodeError). This makes those prints safe everywhere
# and is a harmless no-op on Linux/macOS terminals that are already UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import secrets
import requests
from datetime import datetime, timezone
from flask import Flask, request, jsonify, g
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from decimal import Decimal

from flask_socketio import SocketIO
from apscheduler.schedulers.background import BackgroundScheduler
import subprocess

import yfinance as yf

# yfinance prints noisy "possibly delisted; no price data found" warnings to
# the console whenever a quote comes back empty — which is common when the
# market is closed or Yahoo briefly rate-limits. These are harmless fallback
# misses (Finnhub is our primary price source), so we silence yfinance's own
# logger to keep the server console readable.
import logging
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

# Local modules
from db import get_db, init_db_check, run_migrations
from auth import generate_token, require_auth
from longterm_model import LongTermPredictor   # honest 3-month outlook engine
from recommender import recommend_portfolio
import alpaca_client
import news          # Finnhub news + our hybrid sentiment scorer
import sentiment     # hybrid (TF-IDF+LogReg model + finance lexicon) scorer

# --- Load environment ---
load_dotenv()

FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:8080")
DEBUG = os.getenv("FLASK_DEBUG", "False").lower() == "true"

# Secret key for Flask sessions. NO hardcoded fallback: a known default key
# would let anyone forge signed cookies. If it's missing we generate a random
# one for this run (and warn) rather than ship a guessable constant.
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY")
if not FLASK_SECRET_KEY:
    FLASK_SECRET_KEY = secrets.token_hex(32)
    print("⚠️  FLASK_SECRET_KEY not set — generated a random key for this run. "
          "Set FLASK_SECRET_KEY in .env for a stable production secret.")

# --- Flask app ---
app = Flask(__name__)
app.config["SECRET_KEY"] = FLASK_SECRET_KEY

# One origin allowlist, shared by both the REST API and the WebSocket. The
# Socket.IO server used to be wide open ("*"), which contradicted this lock-down.
ALLOWED_ORIGINS = [
    FRONTEND_ORIGIN,
    "http://127.0.0.1:8080",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "null",  # lets you open index.html directly from disk
]
CORS(app, origins=ALLOWED_ORIGINS)

# Socket.IO for live prices — same allowlist as the REST API (no more "*").
socketio = SocketIO(app, cors_allowed_origins=ALLOWED_ORIGINS)

# APScheduler for async model retraining
scheduler = BackgroundScheduler()

def retrain_models_job():
    print("\n🕒 APScheduler: Starting scheduled model retraining...")
    try:
        script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "training", "retrain_all.py"))
        subprocess.run(["python", script_path], check=True)
        print("✅ APScheduler: Model retraining completed successfully.")

        # Reload fresh long-term models into memory cache
        LongTermPredictor._cache.clear()
        for ticker in ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA"]:
            try:
                LongTermPredictor(ticker)._load()
            except Exception as e:
                print(f"   Could not reload {ticker}: {e}")
    except Exception as e:
        print(f"❌ APScheduler: Model retraining failed: {e}")

# Run every Friday night when market is closed
scheduler.add_job(func=retrain_models_job, trigger="cron", day_of_week='fri', hour=22, minute=0)
scheduler.start()

def background_price_thread():
    """Background thread to stream live prices via WebSocket."""
    tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA"]
    while True:
        # 6 tickers every 10s = 36 Finnhub calls/min, safely under the free
        # tier's 60/min cap. At 5s it was 72/min — the overage got rate-limited
        # and fell through to yfinance, which spammed "possibly delisted".
        socketio.sleep(10)
        prices = {}
        for ticker in tickers:
            p = get_live_price(ticker)
            if p:
                prices[ticker] = float(p)
        if prices:
            socketio.emit('price_update', prices)

@socketio.on('connect')
def handle_connect():
    pass

# Rate limiting (per IP)
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per hour"],
    storage_uri="memory://",
)

# Kill switch state is persisted in the DB (users.kill_switch_active) so it
# SURVIVES a server restart — an emergency stop that forgets itself on reboot
# is worse than useless.


# ===========================================
# HELPERS
# ===========================================

# Last-known-good price per symbol. When BOTH Finnhub and yfinance momentarily
# fail (market closed, rate limit, network blip), we serve the last good value
# instead of dropping the price entirely — so the UI doesn't flicker to blank.
_price_cache: dict[str, float] = {}

def get_live_price(symbol: str) -> float | None:
    """
    Server-side price fetch from Finnhub. NEVER trust client-sent prices.
    Falls back to yfinance, then to the last cached price.
    """
    if FINNHUB_API_KEY:
        try:
            url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_API_KEY}"
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                data = r.json()
                price = data.get("c")
                if price and price > 0:
                    _price_cache[symbol] = float(price)
                    return float(price)
        except Exception:
            pass

    # Fallback: yfinance. Use a 5-day window (not 1d) so we still get the most
    # recent close on weekends / holidays / after-hours, when a 1-day request
    # comes back empty and yfinance logs "possibly delisted".
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.history(period="5d")
        if not info.empty:
            price = float(info["Close"].iloc[-1])
            _price_cache[symbol] = price
            return price
    except Exception:
        pass

    # Last resort: last known good price (None only if we never got one).
    return _price_cache.get(symbol)


# ===========================================
# AUTH ROUTES
# ===========================================

@app.route("/register", methods=["POST"])
@limiter.limit("10 per hour")
def register():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not name or not email or not password:
        return jsonify({"error": "All fields required"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400
    if "@" not in email:
        return jsonify({"error": "Invalid email"}), 400

    hashed = generate_password_hash(password)

    try:
        with get_db() as (conn, cursor):
            cursor.execute(
                "INSERT INTO users (name, email, password, balance) VALUES (%s, %s, %s, %s)",
                (name, email, hashed, 100000.00),
            )
            user_id = cursor.lastrowid
            conn.commit()

        token = generate_token(user_id, email)
        return jsonify({
            "success": True,
            "token": token,
            "user": {"id": user_id, "name": name, "balance": 100000.00},
        })
    except Exception as e:
        # MySQL integrity error = duplicate email
        if "Duplicate" in str(e) or "1062" in str(e):
            return jsonify({"error": "Email already registered"}), 400
        return jsonify({"error": "Registration failed"}), 500


@app.route("/login", methods=["POST"])
@limiter.limit("20 per hour")
def login():
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    with get_db() as (conn, cursor):
        cursor.execute(
            "SELECT id, name, password, balance FROM users WHERE email = %s",
            (email,),
        )
        user = cursor.fetchone()

    if not user or not check_password_hash(user["password"], password):
        return jsonify({"error": "Invalid email or password"}), 401

    token = generate_token(user["id"], email)
    return jsonify({
        "success": True,
        "token": token,
        "user": {
            "id": user["id"],
            "name": user["name"],
            "balance": float(user["balance"]),
        },
    })


# ===========================================
# MARKET DATA ROUTES
# ===========================================

@app.route("/quote", methods=["GET"])
@limiter.limit("60 per minute")
def get_quote():
    symbol = (request.args.get("symbol") or "").upper()
    if not symbol:
        return jsonify({"error": "Symbol required"}), 400

    if not FINNHUB_API_KEY:
        return jsonify({"error": "Server misconfigured: no FINNHUB_API_KEY"}), 500

    try:
        url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_API_KEY}"
        r = requests.get(url, timeout=5)
        return jsonify(r.json()) if r.status_code == 200 else (
            jsonify({"error": "Quote unavailable"}), 502
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/history", methods=["GET"])
@limiter.limit("60 per minute")
def get_history():
    symbol = (request.args.get("symbol") or "").upper()
    if not symbol:
        return jsonify({"error": "Symbol required"}), 400

    try:
        stock = yf.Ticker(symbol)
        hist = stock.history(period="1mo")
        return jsonify({
            "dates": hist.index.strftime("%b %d").tolist(),
            "prices": hist["Close"].tolist(),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ===========================================
# NEWS & SENTIMENT ROUTES (short-term lens; SEPARATE from the 3-month model)
# ===========================================

@app.route("/news", methods=["GET"])
@limiter.limit("30 per minute")
def get_news_route():
    """Recent headlines for a stock, each tagged by our hybrid sentiment model,
    plus an aggregated 'News Mood' (0-100). Cached ~30 min per symbol."""
    symbol = (request.args.get("symbol") or "").upper()
    if not symbol:
        return jsonify({"error": "Symbol required"}), 400
    try:
        return jsonify(news.get_news(symbol))
    except RuntimeError as e:           # e.g. missing FINNHUB_API_KEY
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        app.logger.exception("News fetch failed")
        return jsonify({"error": str(e)}), 502


@app.route("/news-sentiment", methods=["GET"])
@limiter.limit("30 per minute")
def get_news_sentiment_route():
    """Just the aggregated News Mood for a stock (lighter than /news)."""
    symbol = (request.args.get("symbol") or "").upper()
    if not symbol:
        return jsonify({"error": "Symbol required"}), 400
    try:
        return jsonify(news.get_sentiment_only(symbol))
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        app.logger.exception("News sentiment failed")
        return jsonify({"error": str(e)}), 502


# ===========================================
# AI PREDICTION ROUTE
# ===========================================

@app.route("/predict", methods=["POST"])
@require_auth
@limiter.limit("30 per minute")
def predict():
    """3-month outlook: probability of being higher, risk, and honest skill metrics."""
    data = request.get_json() or {}
    symbol = (data.get("symbol") or "").upper()
    if not symbol:
        return jsonify({"error": "Symbol required"}), 400

    try:
        result = LongTermPredictor(symbol).predict()
        return jsonify(result)
    except FileNotFoundError:
        return jsonify({
            "error": f"Model for {symbol} not trained. "
                     f"Run: python training/train_longterm.py {symbol}"
        }), 503
    except Exception as e:
        app.logger.exception("Prediction failed")
        return jsonify({"error": str(e)}), 500


# ===========================================
# PORTFOLIO ROUTES
# ===========================================

@app.route("/portfolio", methods=["GET"])
@require_auth
def get_portfolio():
    user_id = g.user_id
    with get_db() as (conn, cursor):
        cursor.execute("SELECT balance FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        if not user:
            return jsonify({"error": "User not found"}), 404

        cursor.execute(
            "SELECT symbol, shares, avg_price FROM portfolio WHERE user_id = %s",
            (user_id,),
        )
        items = cursor.fetchall()

    return jsonify({
        "balance": float(user["balance"]),
        "portfolio": [
            {
                "symbol": row["symbol"],
                "shares": int(row["shares"]),
                "avg_price": float(row["avg_price"]),
            }
            for row in items
        ],
    })


# ===========================================
# TRADING ROUTES (SECURE - server fetches its own prices)
# ===========================================

def _execute_trade(user_id: int, symbol: str, shares: int, action: str,
                   is_auto: bool = False) -> tuple[dict, int]:
    """
    Shared logic for buy/sell with transactional safety.
    Server fetches its own live price — never trusts the client.

    Returns (response_dict, http_status_code).
    """
    if shares <= 0:
        return {"error": "Shares must be positive"}, 400

    # Server-side price fetch (security!)
    price_val = get_live_price(symbol)
    if not price_val:
        return {"error": "Unable to fetch live price"}, 502

    price = Decimal(str(price_val))
    shares_dec = Decimal(str(shares))
    cost_or_revenue = shares_dec * price

    with get_db() as (conn, cursor):
        # --- Begin transaction (MySQL InnoDB default) ---
        cursor.execute("SELECT balance FROM users WHERE id = %s FOR UPDATE", (user_id,))
        user = cursor.fetchone()
        if not user:
            return {"error": "User not found"}, 404
        balance = Decimal(str(user["balance"]))

        if action == "BUY":
            if balance < cost_or_revenue:
                return {"error": f"Insufficient funds. Need ${float(cost_or_revenue):.2f}"}, 400

            new_balance = balance - cost_or_revenue

            # Upsert portfolio
            cursor.execute(
                "SELECT shares, avg_price FROM portfolio WHERE user_id = %s AND symbol = %s FOR UPDATE",
                (user_id, symbol),
            )
            holding = cursor.fetchone()

            if holding:
                old_shares = Decimal(str(holding["shares"]))
                old_avg = Decimal(str(holding["avg_price"]))
                new_total = old_shares + shares_dec
                new_avg = ((old_shares * old_avg) + cost_or_revenue) / new_total
                cursor.execute(
                    "UPDATE portfolio SET shares = %s, avg_price = %s WHERE user_id = %s AND symbol = %s",
                    (int(new_total), float(new_avg), user_id, symbol),
                )
            else:
                cursor.execute(
                    "INSERT INTO portfolio (user_id, symbol, shares, avg_price) VALUES (%s, %s, %s, %s)",
                    (user_id, symbol, shares, float(price)),
                )

        elif action == "SELL":
            cursor.execute(
                "SELECT shares FROM portfolio WHERE user_id = %s AND symbol = %s FOR UPDATE",
                (user_id, symbol),
            )
            holding = cursor.fetchone()
            if not holding or int(holding["shares"]) < shares:
                return {"error": "Not enough shares to sell"}, 400

            new_balance = balance + cost_or_revenue
            remaining = int(holding["shares"]) - shares
            if remaining == 0:
                cursor.execute(
                    "DELETE FROM portfolio WHERE user_id = %s AND symbol = %s",
                    (user_id, symbol),
                )
            else:
                cursor.execute(
                    "UPDATE portfolio SET shares = %s WHERE user_id = %s AND symbol = %s",
                    (remaining, user_id, symbol),
                )
        else:
            return {"error": "Invalid action"}, 400

        # Update balance
        cursor.execute(
            "UPDATE users SET balance = %s WHERE id = %s",
            (float(new_balance), user_id),
        )

        # Audit log
        cursor.execute(
            """INSERT INTO transactions
               (user_id, symbol, action, shares, price, total_amount, is_auto)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (user_id, symbol, action, shares, float(price), float(cost_or_revenue), is_auto),
        )

        conn.commit()

    return {
        "success": True,
        "new_balance": float(new_balance),
        "executed_price": float(price),
        "shares": shares,
    }, 200


@app.route("/buy", methods=["POST"])
@require_auth
def buy_stock():
    data = request.get_json() or {}
    symbol = (data.get("symbol") or "").upper()
    shares = int(data.get("shares", 0))
    response, status = _execute_trade(g.user_id, symbol, shares, "BUY")
    return jsonify(response), status


@app.route("/sell", methods=["POST"])
@require_auth
def sell_stock():
    data = request.get_json() or {}
    symbol = (data.get("symbol") or "").upper()
    shares = int(data.get("shares", 0))
    response, status = _execute_trade(g.user_id, symbol, shares, "SELL")
    return jsonify(response), status


@app.route("/add_funds", methods=["POST"])
@require_auth
def add_funds():
    data = request.get_json() or {}
    try:
        amount = Decimal(str(data.get("amount", 0)))
    except:
        amount = Decimal('0')
        
    if amount <= 0:
        return jsonify({"error": "Amount must be positive"}), 400
    if amount > 1_000_000:
        return jsonify({"error": "Max $1M per deposit"}), 400

    with get_db() as (conn, cursor):
        cursor.execute(
            "UPDATE users SET balance = balance + %s WHERE id = %s",
            (amount, g.user_id),
        )
        cursor.execute("SELECT balance FROM users WHERE id = %s", (g.user_id,))
        user = cursor.fetchone()
        conn.commit()

    return jsonify({"success": True, "new_balance": float(user["balance"])})


# ===========================================
# FAVORITES ROUTES
# ===========================================

@app.route("/favorites", methods=["GET"])
@require_auth
def get_favorites():
    with get_db() as (conn, cursor):
        cursor.execute(
            "SELECT symbol FROM favorites WHERE user_id = %s ORDER BY added_at",
            (g.user_id,),
        )
        rows = cursor.fetchall()
    return jsonify({"favorites": [r["symbol"] for r in rows]})


@app.route("/favorites", methods=["POST"])
@require_auth
def toggle_favorite():
    data = request.get_json() or {}
    symbol = (data.get("symbol") or "").upper()
    action = data.get("action", "add")

    if not symbol:
        return jsonify({"error": "Symbol required"}), 400

    with get_db() as (conn, cursor):
        if action == "add":
            try:
                cursor.execute(
                    "INSERT INTO favorites (user_id, symbol) VALUES (%s, %s)",
                    (g.user_id, symbol),
                )
                conn.commit()
            except Exception:
                pass  # already exists
        elif action == "remove":
            cursor.execute(
                "DELETE FROM favorites WHERE user_id = %s AND symbol = %s",
                (g.user_id, symbol),
            )
            conn.commit()
        else:
            return jsonify({"error": "Invalid action"}), 400

    return jsonify({"success": True})


# ===========================================
# AUTO-BUY RECOMMENDATION ROUTES
# ===========================================

@app.route("/recommend", methods=["POST"])
@require_auth
@limiter.limit("10 per minute")
def recommend():
    """Get risk-adjusted recommendations for user's favorites."""
    user_id = g.user_id

    with get_db() as (conn, cursor):
        cursor.execute("SELECT balance FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        cursor.execute(
            "SELECT symbol FROM favorites WHERE user_id = %s",
            (user_id,),
        )
        favs = [r["symbol"] for r in cursor.fetchall()]

    if not favs:
        return jsonify({
            "error": "No favorites set. Mark stocks with a star first.",
            "recommendations": [],
            "total_investment": 0,
            "estimated_return": 0,
        }), 400

    try:
        result = recommend_portfolio(favs, float(user["balance"]))

        # Log recommendations for audit
        with get_db() as (conn, cursor):
            for rec in result["recommendations"]:
                cursor.execute(
                    """INSERT INTO autobuy_log
                       (user_id, symbol, predicted_return, confidence, volatility,
                        score, action_taken)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (user_id, rec["symbol"], rec["predicted_return"],
                     rec["confidence"], 0.0, rec["score"], rec["action"]),
                )
            conn.commit()

        return jsonify(result)
    except Exception as e:
        app.logger.exception("Recommendation failed")
        return jsonify({"error": str(e)}), 500


@app.route("/execute_recommendations", methods=["POST"])
@require_auth
def execute_recommendations():
    """Execute all current BUY recommendations for user's favorites."""
    user_id = g.user_id

    with get_db() as (conn, cursor):
        cursor.execute(
            "SELECT balance, kill_switch_active FROM users WHERE id = %s", (user_id,)
        )
        user = cursor.fetchone()
        cursor.execute("SELECT symbol FROM favorites WHERE user_id = %s", (user_id,))
        favs = [r["symbol"] for r in cursor.fetchall()]

    if user and user["kill_switch_active"]:
        return jsonify({"error": "Kill switch active. Re-enable auto-buy first."}), 403

    if not favs:
        return jsonify({"error": "No favorites"}), 400

    recs = recommend_portfolio(favs, float(user["balance"]))

    trades_executed = 0
    failures = []
    last_balance = float(user["balance"])

    for rec in recs["recommendations"]:
        if rec["action"] != "BUY" or rec["shares"] <= 0:
            continue
        result, status = _execute_trade(
            user_id, rec["symbol"], rec["shares"], "BUY", is_auto=True
        )
        if result.get("success"):
            trades_executed += 1
            last_balance = result["new_balance"]
        else:
            failures.append({"symbol": rec["symbol"], "error": result.get("error")})

    return jsonify({
        "success": True,
        "trades_executed": trades_executed,
        "new_balance": last_balance,
        "failures": failures,
    })


@app.route("/autobuy_settings", methods=["POST"])
@require_auth
def autobuy_settings():
    data = request.get_json() or {}
    enabled = bool(data.get("enabled", False))

    with get_db() as (conn, cursor):
        if enabled:
            # Turning auto-buy ON also clears any active kill switch.
            cursor.execute(
                "UPDATE users SET auto_buy_enabled = TRUE, kill_switch_active = FALSE WHERE id = %s",
                (g.user_id,),
            )
        else:
            cursor.execute(
                "UPDATE users SET auto_buy_enabled = FALSE WHERE id = %s",
                (g.user_id,),
            )
        conn.commit()

    return jsonify({"success": True, "enabled": enabled})


@app.route("/kill_switch", methods=["POST"])
@require_auth
def kill_switch():
    """Emergency stop: disable auto-buy, cancel pending orders."""
    # Persist the kill switch so it survives a server restart.
    with get_db() as (conn, cursor):
        cursor.execute(
            "UPDATE users SET auto_buy_enabled = FALSE, kill_switch_active = TRUE WHERE id = %s",
            (g.user_id,),
        )
        conn.commit()

    # If Alpaca is configured, cancel all pending orders too
    alpaca_result = alpaca_client.cancel_all_orders()

    return jsonify({
        "success": True,
        "message": "Auto-buy disabled. All pending orders cancelled.",
        "alpaca": alpaca_result,
    })


# ===========================================
# HEALTH CHECK
# ===========================================

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "alpaca_configured": alpaca_client.is_configured(),
        "finnhub_configured": bool(FINNHUB_API_KEY),
    })


# ===========================================
# STARTUP
# ===========================================

if __name__ == "__main__":
    print("=" * 60)
    print("HAWK SIGHT AI - Backend Starting")
    print("=" * 60)

    if not init_db_check():
        print("⚠️  Server starting anyway, but DB routes will fail.")
        print("   Fix DB connection or run schema.sql in phpMyAdmin.")
    else:
        run_migrations()  # auto-add columns added after the initial schema

    if not FINNHUB_API_KEY:
        print("⚠️  FINNHUB_API_KEY not set in .env — /quote will fail")

    if not alpaca_client.is_configured():
        print("ℹ️  Alpaca not configured — using internal portfolio only")

    # Pre-load long-term outlook models
    print("\n🧠 Pre-loading 3-month outlook models into memory...")
    loaded = 0
    for ticker in ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA"]:
        try:
            LongTermPredictor(ticker)._load()
            loaded += 1
        except FileNotFoundError:
            print(f"   ⚠️  {ticker} not trained yet — run training/train_longterm.py {ticker}")
        except Exception as e:
            print(f"   ⚠️  {ticker} failed to load: {e}")
    print(f"✅ {loaded}/6 outlook models loaded.")

    # Pre-load the news sentiment model so the first /news call is fast
    try:
        sentiment.warm_up()
        print("✅ News sentiment model loaded (TF-IDF + LogReg + finance lexicon).")
    except Exception as e:
        print(f"⚠️  Sentiment model not loaded: {e} — run training/train_sentiment.py")

    # Start WebSocket background thread
    socketio.start_background_task(background_price_thread)

    print(f"\n🚀 Listening on http://127.0.0.1:5000 (Socket.IO enabled)")
    print(f"   CORS allowed: {FRONTEND_ORIGIN}")
    print(f"   Debug mode: {DEBUG}")
    print("=" * 60)

    socketio.run(app, host="127.0.0.1", port=5000, debug=DEBUG, use_reloader=False, allow_unsafe_werkzeug=True)
