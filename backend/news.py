"""
news.py — Stock news feed + news-mood, powered by OUR sentiment model.

Pipeline:
  Finnhub company-news  ->  hybrid sentiment scorer (sentiment.py)  ->  per-stock
  "News Mood" (0-100) + a list of headlines each tagged positive/negative/neutral.

Caching: Finnhub's free tier is rate-limited and scoring costs a little CPU, so
we cache each symbol's result for CACHE_TTL seconds. The dashboard can be
refreshed freely without hammering the API.

This is intentionally SEPARATE from the 3-month price model: news mood is a
short-term lens shown ALONGSIDE the long-term outlook, never blended into it.
"""

import os
import time
import requests
from datetime import datetime, timedelta, timezone

import sentiment

FINNHUB_URL = "https://finnhub.io/api/v1/company-news"
LOOKBACK_DAYS = 7
MAX_ARTICLES = 25          # score/show at most this many recent headlines
CACHE_TTL = 1800           # 30 minutes
HTTP_TIMEOUT = 12

_cache = {}                # symbol -> (fetched_at_epoch, payload)


def _api_key() -> str:
    return os.getenv("FINNHUB_API_KEY", "")


def _fetch_raw(symbol: str) -> list:
    """Call Finnhub company-news for the last LOOKBACK_DAYS. Returns raw list."""
    key = _api_key()
    if not key:
        raise RuntimeError("FINNHUB_API_KEY not set in environment (.env).")
    today = datetime.now(timezone.utc).date()
    params = {
        "symbol": symbol.upper(),
        "from": (today - timedelta(days=LOOKBACK_DAYS)).isoformat(),
        "to": today.isoformat(),
        "token": key,
    }
    resp = requests.get(FINNHUB_URL, params=params, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []


def _build(symbol: str) -> dict:
    """Fetch, score, and aggregate news for one symbol (no caching here)."""
    raw = _fetch_raw(symbol)
    # newest first, drop entries without a headline, cap the count
    raw = [a for a in raw if a.get("headline")]
    raw.sort(key=lambda a: a.get("datetime", 0), reverse=True)
    raw = raw[:MAX_ARTICLES]

    articles, labels = [], []
    for a in raw:
        headline = a.get("headline", "").strip()
        # Score the headline (the most signal-dense part).
        s = sentiment.score_text(headline)
        labels.append(s["label"])
        ts = a.get("datetime", 0)
        articles.append({
            "headline": headline,
            "summary": (a.get("summary") or "").strip()[:300],
            "source": a.get("source", ""),
            "url": a.get("url", ""),
            "image": a.get("image", ""),
            "datetime": int(ts),
            "published_iso": (datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                              if ts else ""),
            "sentiment": s["label"],
            "sentiment_confidence": s["confidence"],
            "sentiment_source": s["source"],   # "model" | "lexicon-assist"
            "keywords": s["keywords"],
        })

    mood = sentiment.aggregate(labels)
    return {
        "symbol": symbol.upper(),
        "sentiment": mood,                      # {mood, label, counts, total}
        "articles": articles,
        "lookback_days": LOOKBACK_DAYS,
        "generated_iso": datetime.now(timezone.utc).isoformat(),
    }


def get_news(symbol: str, force: bool = False) -> dict:
    """Public: cached news + sentiment for a symbol."""
    symbol = symbol.upper()
    now = time.time()
    if not force and symbol in _cache:
        fetched_at, payload = _cache[symbol]
        if now - fetched_at < CACHE_TTL:
            out = dict(payload)
            out["cached"] = True
            return out
    payload = _build(symbol)
    _cache[symbol] = (now, payload)
    out = dict(payload)
    out["cached"] = False
    return out


def get_sentiment_only(symbol: str) -> dict:
    """Public: just the mood summary (uses the same cache)."""
    data = get_news(symbol)
    return {
        "symbol": data["symbol"],
        "sentiment": data["sentiment"],
        "article_count": data["sentiment"]["total"],
        "lookback_days": data["lookback_days"],
        "cached": data.get("cached", False),
    }


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    sentiment.warm_up()
    d = get_news("AAPL")
    print(f"AAPL — News Mood: {d['sentiment']['mood']}/100 ({d['sentiment']['label']})  "
          f"counts={d['sentiment']['counts']}  total={d['sentiment']['total']}")
    for a in d["articles"][:8]:
        kw = f"  kw={a['keywords']}" if a["keywords"] else ""
        print(f"  [{a['sentiment']:>8} via {a['sentiment_source']:>13}] {a['headline'][:80]}{kw}")
