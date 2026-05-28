"""
sentiment.py — Hybrid financial-news sentiment scorer.

TWO BRAINS, ONE ANSWER:
  1. CORE  — our own trained TF-IDF + LogisticRegression model
             (models/sentiment_model.pkl, ~0.81 macro-F1 on Financial PhraseBank).
  2. ASSIST — a small, transparent finance lexicon (word list) that catches
             unmistakable bullish/bearish headline words. The ML model was
             trained on formal report sentences, so terse headline words like
             "plunge", "fraud", "beats", "record" often slip past it and it
             defaults to "neutral". The lexicon is the safety net.

DECISION RULE (kept simple and explainable):
  - If the ML model is CONFIDENT and not neutral -> trust the ML model.
  - If the ML model is unsure / says "neutral" BUT the lexicon sees a clear
    bullish or bearish signal -> go with the lexicon (and we record which
    keywords triggered it, so every decision can be explained).
  - Otherwise -> neutral.

HONEST LIMITATION: a word list can misread phrasing like "no fraud found"
(sees "fraud"). We add a light negation guard, and crucially the lexicon only
ASSISTS — it never overrides a confident ML call — so its blast radius is small.
"""

import os
import re
import joblib

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(os.path.dirname(_BACKEND_DIR), "models")
_MODEL_PATH = os.path.join(MODELS_DIR, "sentiment_model.pkl")

# Only the ML model decides confidently above this probability.
_ML_CONFIDENT = 0.60

# --- The finance lexicon (deliberately only UNMISTAKABLE words, to keep the
#     assist's blast radius small). Single words and short phrases. ---
_BULLISH = {
    "beats", "beat", "surge", "surges", "surged", "soar", "soars", "soared",
    "jump", "jumps", "jumped", "rally", "rallies", "rallied", "record",
    "upgrade", "upgrades", "upgraded", "raises", "raised", "gain", "gains",
    "gained", "outperform", "outperforms", "rebound", "rebounds", "tops",
    "topped", "exceeds", "exceeded", "strong", "growth", "profit", "profitable",
    "all-time high", "record revenue", "record profit", "raises guidance",
    "better than expected", "beats estimates", "buy rating",
}
_BEARISH = {
    "plunge", "plunges", "plunged", "fraud", "recall", "recalls", "recalled",
    "lawsuit", "sued", "probe", "investigation", "miss", "misses", "missed",
    "downgrade", "downgrades", "downgraded", "slump", "slumps", "slumped",
    "tumble", "tumbles", "tumbled", "bankruptcy", "bankrupt", "loss", "losses",
    "warning", "plummet", "plummets", "plummeted", "slashes", "slash", "crash",
    "crashes", "scandal", "layoffs", "default", "halts", "halted", "weak",
    "plunging", "profit warning", "job cuts", "below expectations",
    "cuts guidance", "sell rating", "data breach",
}

_NEGATORS = {"no", "not", "without", "denies", "denied", "avoids", "avoided"}
_WORD_RE = re.compile(r"[a-z][a-z'\-]+")


def _lexicon_signal(text: str):
    """
    Return (net, hits) where net = (#bullish - #bearish) and hits lists the
    matched keywords. A light negation guard skips a keyword if immediately
    preceded by a negator (e.g. 'no fraud').
    """
    low = " " + text.lower() + " "
    tokens = _WORD_RE.findall(low)
    bull_hits, bear_hits = [], []

    # phrases first (substring match)
    for phrase in (w for w in _BULLISH if " " in w):
        if phrase in low:
            bull_hits.append(phrase)
    for phrase in (w for w in _BEARISH if " " in w):
        if phrase in low:
            bear_hits.append(phrase)

    # single words (with a 1-word negation lookback)
    for i, tok in enumerate(tokens):
        prev = tokens[i - 1] if i > 0 else ""
        if prev in _NEGATORS:
            continue
        if tok in _BULLISH:
            bull_hits.append(tok)
        elif tok in _BEARISH:
            bear_hits.append(tok)

    net = len(bull_hits) - len(bear_hits)
    return net, sorted(set(bull_hits + bear_hits))


class _Scorer:
    """Loads the trained model once and scores text with the hybrid rule."""

    def __init__(self):
        self._pipeline = None
        self._classes = None

    def _ensure_loaded(self):
        if self._pipeline is None:
            if not os.path.exists(_MODEL_PATH):
                raise FileNotFoundError(
                    f"Sentiment model not found at {_MODEL_PATH}. "
                    f"Run: python training/train_sentiment.py"
                )
            bundle = joblib.load(_MODEL_PATH)
            self._pipeline = bundle["pipeline"]
            self._classes = list(bundle["classes"])

    def score(self, text: str) -> dict:
        """Score one headline -> {label, confidence, source, keywords, probs}."""
        self._ensure_loaded()
        text = (text or "").strip()
        if not text:
            return {"label": "neutral", "confidence": 0.0, "source": "empty",
                    "keywords": [], "probs": {}}

        proba = self._pipeline.predict_proba([text])[0]
        probs = {c: float(p) for c, p in zip(self._classes, proba)}
        ml_label = max(probs, key=probs.get)
        ml_conf = probs[ml_label]

        net, hits = _lexicon_signal(text)

        # Decision rule
        if ml_label != "neutral" and ml_conf >= _ML_CONFIDENT:
            label, source, conf = ml_label, "model", ml_conf
        elif net != 0:
            # ML unsure or neutral, but lexicon has a clear lean -> assist.
            label = "positive" if net > 0 else "negative"
            source = "lexicon-assist"
            # confidence grows a little with the number of keyword hits
            conf = min(0.55 + 0.1 * (abs(net) - 1), 0.85)
        else:
            label, source, conf = ml_label, "model", ml_conf

        return {"label": label, "confidence": round(float(conf), 3),
                "source": source, "keywords": hits, "probs": probs}


_scorer = _Scorer()


def score_text(text: str) -> dict:
    """Public: score a single piece of text."""
    return _scorer.score(text)


def warm_up():
    """Load the model now (called at server startup so first request is fast)."""
    _scorer._ensure_loaded()


def aggregate(labels) -> dict:
    """
    Turn a list of per-article labels into a 0-100 'mood' + counts + overall.
    Mood = 50 is perfectly balanced; 100 = all positive; 0 = all negative.
    Neutral articles pull the mood toward the middle (50).
    """
    labels = list(labels)
    n = len(labels)
    counts = {"positive": labels.count("positive"),
              "negative": labels.count("negative"),
              "neutral": labels.count("neutral")}
    if n == 0:
        return {"mood": 50, "label": "neutral", "counts": counts, "total": 0}

    net = (counts["positive"] - counts["negative"]) / n   # -1 .. +1
    mood = int(round(50 + 50 * net))
    mood = max(0, min(100, mood))
    if mood >= 60:
        overall = "positive"
    elif mood <= 40:
        overall = "negative"
    else:
        overall = "neutral"
    return {"mood": mood, "label": overall, "counts": counts, "total": n}


if __name__ == "__main__":
    # Quick manual check
    tests = [
        "Company beats earnings estimates and raises guidance",
        "Firm faces fraud investigation and shares plunge",
        "The company will hold its annual meeting next month",
        "No fraud found in company audit, regulators say",
        "Tesla recalls thousands of vehicles over safety defect",
        "Apple unveils record quarterly revenue",
    ]
    for t in tests:
        r = score_text(t)
        kw = f"  keywords={r['keywords']}" if r["keywords"] else ""
        print(f"[{r['label']:>8} {r['confidence']*100:4.0f}% via {r['source']:>13}] {t}{kw}")
