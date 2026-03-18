"""
logger.py - Trade and decision logging.

Appends trading decisions and executed trades to CSV files
in data/ for post-analysis. Creates files with headers if missing.
"""

import csv
import json
from datetime import datetime, timezone

from config import DATA_DIR

DECISIONS_FILE = DATA_DIR / "decisions.csv"
TRADES_FILE = DATA_DIR / "trades.csv"

DECISION_FIELDS = ["timestamp", "action", "confidence", "reasoning", "signals", "risk"]
TRADE_FIELDS = [
    "timestamp", "action", "price", "quantity", "pnl", "cash_after",
    "strategy", "strength", "market_condition",
]


def _ensure_csv(path, fieldnames: list) -> None:
    """Create the CSV file with headers if it doesn't exist.

    Args:
        path: Path to the CSV file.
        fieldnames: List of column header strings.
    """
    if not path.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=fieldnames).writeheader()


def _now() -> str:
    """Return the current UTC timestamp as an ISO string.

    Returns:
        ISO-formatted timestamp string.
    """
    return datetime.now(timezone.utc).isoformat()


def log_decision(decision: dict) -> None:
    """Append a trading decision to decisions.csv.

    Args:
        decision: Claude's parsed decision with action, confidence, reasoning.
    """
    _ensure_csv(DECISIONS_FILE, DECISION_FIELDS)

    row = {
        "timestamp": _now(),
        "action": decision.get("action", "HOLD"),
        "confidence": decision.get("confidence", 0.0),
        "reasoning": decision.get("reasoning", ""),
        "signals": "|".join(decision.get("signals", [])),
        "risk": json.dumps(decision.get("risk", {})),
    }

    with open(DECISIONS_FILE, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=DECISION_FIELDS).writerow(row)


def log_trade(trade_result: dict, decision: dict = None) -> None:
    """Append an executed trade to trades.csv.

    Args:
        trade_result: Result dict from paper_broker.execute_trade().
        decision: Final decision dict from decision_engine (optional).
            Used to extract strategy, strength, and market_condition tags.
    """
    _ensure_csv(TRADES_FILE, TRADE_FIELDS)

    if decision is None:
        decision = {}

    portfolio = trade_result.get("portfolio", {})

    # Derive strategy tag from signal strength
    strength = decision.get("strength", "unknown")
    if strength == "strong":
        strategy = "both"
    elif strength == "weak":
        reasoning = decision.get("reasoning", "").lower()
        if reasoning.startswith("only trend"):
            strategy = "trend"
        elif reasoning.startswith("only mean"):
            strategy = "mean_reversion"
        else:
            strategy = "unknown"
    else:
        strategy = "none"

    row = {
        "timestamp": _now(),
        "action": trade_result.get("action", "HOLD"),
        "price": trade_result.get("price", 0.0),
        "quantity": trade_result.get("quantity", 0.0),
        "pnl": trade_result.get("pnl", 0.0),
        "cash_after": portfolio.get("cash", 0.0),
        "strategy": strategy,
        "strength": decision.get("strength", "unknown"),
        "market_condition": decision.get("market_condition", "unknown"),
    }

    with open(TRADES_FILE, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=TRADE_FIELDS).writerow(row)


def get_recent_trades(n: int = 10) -> list:
    """Read the last N trades from trades.csv.

    Args:
        n: Number of recent trades to return.

    Returns:
        List of trade dicts, most recent first. Empty list if file is missing.
    """
    if not TRADES_FILE.exists():
        return []

    with open(TRADES_FILE, newline="") as f:
        rows = list(csv.DictReader(f))

    return rows[-n:][::-1]
