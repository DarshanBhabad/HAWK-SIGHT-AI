"""
auth.py — JWT token handling and route protection.

Why JWT? Stateless, no session storage needed, scales horizontally.
Token is signed with FLASK_SECRET_KEY so users can't forge them.

Important: tokens are NOT encrypted, just signed. Don't put secrets inside.
"""

import os
import jwt
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import request, jsonify, g

# NO hardcoded fallback secret. A known default would let anyone forge a valid
# token and impersonate any user. If JWT_SECRET is missing we generate a random
# one for this run (and warn). Tokens then invalidate on restart — fine for dev,
# and a loud nudge to set a stable JWT_SECRET in .env for production.
JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    JWT_SECRET = secrets.token_hex(32)
    print("⚠️  JWT_SECRET not set — generated a random one for this run. "
          "Existing logins will be invalid after a restart. "
          "Set JWT_SECRET in .env for production.")

JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", 24))
JWT_ALGORITHM = "HS256"


def generate_token(user_id: int, email: str) -> str:
    """Create a signed JWT for an authenticated user."""
    payload = {
        "user_id": user_id,
        "email": email,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict | None:
    """Verify and decode a JWT. Returns None if invalid/expired."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def require_auth(f):
    """
    Decorator that requires a valid JWT in the Authorization header.

    Usage:
        @app.route('/protected')
        @require_auth
        def protected():
            user_id = g.user_id  # set by decorator
            ...
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or malformed token"}), 401

        token = auth_header.split(" ", 1)[1]
        payload = decode_token(token)
        if payload is None:
            return jsonify({"error": "Invalid or expired token"}), 401

        # Make user info available to the route via Flask's g object
        g.user_id = payload["user_id"]
        g.email = payload["email"]
        return f(*args, **kwargs)
    return wrapper
