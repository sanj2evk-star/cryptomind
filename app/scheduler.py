"""
scheduler.py - Trading loop scheduler.

Runs the trading cycle every hour in a loop with graceful
shutdown on Ctrl+C. Also supports a single manual run.
"""

import time
from datetime import datetime, timezone

INTERVAL_SECONDS = 60 * 60  # 1 hour


def run_loop(trading_fn) -> None:
    """Run the trading function every hour until interrupted.

    Catches exceptions within each cycle so the loop continues.
    Press Ctrl+C to stop gracefully.

    Args:
        trading_fn: Callable that executes one trading cycle.
    """
    print(f"Scheduler started. Running every {INTERVAL_SECONDS // 60} minutes.")
    print("Press Ctrl+C to stop.\n")

    try:
        while True:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            print(f"--- Cycle started at {now} ---")

            try:
                trading_fn()
            except Exception as e:
                print(f"[scheduler] Cycle failed: {e}")

            print(f"Next cycle in {INTERVAL_SECONDS // 60} minutes...\n")
            time.sleep(INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print("\nScheduler stopped by user.")


def run_once(trading_fn) -> None:
    """Run the trading function a single time.

    Args:
        trading_fn: Callable that executes one trading cycle.
    """
    trading_fn()
