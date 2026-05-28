"""
train_sentiment.py — Train OUR OWN financial news sentiment model.

This is the NLP half of Hawk Sight. It reads a finance sentence (a headline)
and predicts: positive / negative / neutral. We train it ourselves so it is
genuinely our work and fully explainable — no downloaded black box.

METHOD (kept in the same honest, interpretable family as the price model):
    TF-IDF  ->  Logistic Regression
  - TF-IDF turns text into numbers that reflect how important each word is.
  - Logistic Regression learns which words push toward positive / negative.
  - We use word + 2-word phrases (bigrams) so "not good" or "lower profit"
    are understood, not just single words.

DATA: Financial PhraseBank (Malo et al., 2014) — finance sentences labelled by
experts. We train on the 75%-agreement file (good label quality + decent size).

AN HONEST NOTE ON BALANCING (important, and the OPPOSITE of the price model):
The data is ~62% neutral. A lazy model could just shout "neutral" and score 62%
accuracy while being useless at spotting market-moving good/bad news. For the
PRICE model we removed class balancing (we WANTED to match the high base rate).
Here the goal is the reverse — we must DETECT the rarer positive/negative
headlines — so we DO use class_weight="balanced" and judge the model on
macro-F1 (which weights all three classes equally), not raw accuracy.

Run:
    python training/train_sentiment.py
"""

import os
import sys
import json
import joblib

# UTF-8 console so status icons don't crash a legacy Windows (cp1252) terminal.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, f1_score, classification_report, confusion_matrix

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_THIS_DIR)
MODELS_DIR = os.path.join(_ROOT, "models")
DATA_FILE = os.path.join(_THIS_DIR, "data", "financial_phrasebank", "Sentences_75Agree.txt")

LABELS = ["negative", "neutral", "positive"]


def load_dataset(path: str):
    """Parse 'sentence@label' lines (latin-1 encoded) into texts + labels."""
    texts, labels = [], []
    with open(path, encoding="latin-1") as f:
        for line in f:
            line = line.strip()
            if "@" not in line:
                continue
            sentence, label = line.rsplit("@", 1)
            label = label.strip().lower()
            if label in LABELS and sentence.strip():
                texts.append(sentence.strip())
                labels.append(label)
    return texts, labels


def main():
    if not os.path.exists(DATA_FILE):
        print(f"❌ Dataset not found at {DATA_FILE}")
        print("   Run the dataset download step first.")
        sys.exit(1)

    texts, labels = load_dataset(DATA_FILE)
    print("=" * 72)
    print("TRAINING OUR OWN FINANCIAL SENTIMENT MODEL  (TF-IDF + Logistic Reg.)")
    print("=" * 72)
    print(f"Loaded {len(texts)} labelled finance sentences.")
    counts = {l: labels.count(l) for l in LABELS}
    print(f"Label mix: {counts}  (neutral dominates — see macro-F1, not just accuracy)\n")

    # Stratified split so each class keeps its proportion in train and test.
    X_tr, X_te, y_tr, y_te = train_test_split(
        texts, labels, test_size=0.2, random_state=42, stratify=labels
    )

    # TF-IDF (1- and 2-word phrases) + class-balanced Logistic Regression.
    pipe = Pipeline([
        ("tfidf", TfidfVectorizer(
            ngram_range=(1, 2),     # capture "not good", "record profit"
            min_df=2,               # ignore ultra-rare typos
            sublinear_tf=True,      # dampen very frequent words
            strip_accents="unicode",
        )),
        ("clf", LogisticRegression(
            max_iter=2000,
            C=1.0,
            class_weight="balanced",  # the fix for the 62% neutral imbalance
        )),
    ])
    pipe.fit(X_tr, y_tr)

    # --- Honest evaluation on the held-out 20% ---
    pred = pipe.predict(X_te)
    acc = accuracy_score(y_te, pred)
    macro_f1 = f1_score(y_te, pred, average="macro", labels=LABELS)
    print("HELD-OUT TEST RESULTS (data the model never saw):")
    print(f"  Accuracy : {acc*100:.1f}%")
    print(f"  Macro-F1 : {macro_f1:.3f}   <-- the metric that matters (all 3 classes equal)\n")
    print(classification_report(y_te, pred, labels=LABELS, digits=3))
    print("Confusion matrix (rows = true, cols = predicted), order = neg/neu/pos:")
    print(confusion_matrix(y_te, pred, labels=LABELS))

    # --- Sanity check on a few obvious headlines ---
    samples = [
        "Company beats earnings estimates and raises guidance",
        "Firm faces fraud investigation and shares plunge",
        "The company will hold its annual meeting next month",
        "Profit declined sharply amid weak demand",
        "Analysts upgrade the stock to buy on strong growth",
    ]
    print("\nSanity check on example headlines:")
    probs = pipe.predict_proba(samples)
    classes = list(pipe.named_steps["clf"].classes_)
    for s, pr in zip(samples, probs):
        top = classes[pr.argmax()]
        print(f"  [{top:>8}  {pr.max()*100:4.0f}%]  {s}")

    # --- Refit on ALL data for deployment (use every labelled example) ---
    final = Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=2,
                                  sublinear_tf=True, strip_accents="unicode")),
        ("clf", LogisticRegression(max_iter=2000, C=1.0, class_weight="balanced")),
    ])
    final.fit(texts, labels)

    os.makedirs(MODELS_DIR, exist_ok=True)
    bundle_path = os.path.join(MODELS_DIR, "sentiment_model.pkl")
    joblib.dump({"pipeline": final, "classes": list(final.named_steps["clf"].classes_)},
                bundle_path)

    meta = {
        "method": "TF-IDF (1-2 grams) + LogisticRegression(class_weight=balanced)",
        "dataset": "Financial PhraseBank — Sentences_75Agree",
        "n_samples": len(texts),
        "label_mix": counts,
        "test_accuracy": acc,
        "test_macro_f1": macro_f1,
        "classes": LABELS,
    }
    with open(os.path.join(MODELS_DIR, "sentiment_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\n✅ Saved model -> {bundle_path}")
    print("✅ Saved metrics -> models/sentiment_meta.json")


if __name__ == "__main__":
    main()
