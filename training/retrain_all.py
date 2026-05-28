"""
retrain_all.py — Master retraining script.

Run this weekly (or via the scheduler in server.py) to retrain the 3-month
outlook models on the latest market data.

Usage:
    python training/retrain_all.py
    python training/retrain_all.py AAPL MSFT  # subset
"""

import os
import sys
import subprocess

TRAINING_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA"]


def run_step(name: str, script: str, args: list[str]):
    print(f"\n{'#' * 70}")
    print(f"# {name}")
    print(f"{'#' * 70}")
    cmd = [sys.executable, os.path.join(TRAINING_DIR, script)] + args
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"⚠️ {name} returned non-zero exit code")
    return result.returncode == 0


def main():
    tickers = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_TICKERS
    tickers = [t.upper() for t in tickers]

    # Train the 3-month outlook models (the honest, only engine)
    run_step("Training 3-month outlook models", "train_longterm.py", tickers)

    print(f"\n{'=' * 70}")
    print("✅ RETRAINING COMPLETE")
    print(f"{'=' * 70}")
    print("Next steps:")
    print("  - Check models/longterm_results.json for measured skill")
    print("  - Restart backend server to load new models")


if __name__ == "__main__":
    main()
