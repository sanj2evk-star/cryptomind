"""
replay.py - Trade replay and debugger.

Replays past trades step-by-step, showing market conditions,
decisions made, and outcomes. Useful for debugging strategy
behavior and learning from past results.

Usage:
    python app/replay.py              # replay all trades
    python app/replay.py --last 5     # replay last 5 trades
    python app/replay.py --step       # pause between each trade
"""

from __future__ import annotations

import csv
import sys

from config import DATA_DIR

TRADES_FILE = DATA_DIR / "trades.csv"
DECISIONS_FILE = DATA_DIR / "decisions.csv"
EQUITY_FILE = DATA_DIR / "equity.csv"
REJECTED_FILE = DATA_DIR / "rejected.csv"


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def _load_csv(path) -> list[dict]:
    """Load a CSV file as a list of dicts.

    Args:
        path: Path to the CSV file.

    Returns:
        List of row dicts, or empty list if missing.
    """
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def load_trades() -> list[dict]:
    """Load all trades from trades.csv in chronological order."""
    return _load_csv(TRADES_FILE)


def load_decisions() -> list[dict]:
    """Load all decisions from decisions.csv in chronological order."""
    return _load_csv(DECISIONS_FILE)


def load_rejected() -> list[dict]:
    """Load all rejected trades from rejected.csv."""
    return _load_csv(REJECTED_FILE)


def load_equity() -> list[dict]:
    """Load equity curve snapshots."""
    return _load_csv(EQUITY_FILE)


# ---------------------------------------------------------------------------
# Trade-decision matching
# ---------------------------------------------------------------------------

def match_trades_to_decisions(trades: list[dict], decisions: list[dict]) -> list[dict]:
    """Pair each trade with the closest decision by timestamp.

    Matches each trade to the decision with the nearest preceding timestamp.

    Args:
        trades: List of trade dicts.
        decisions: List of decision dicts.

    Returns:
        List of combined dicts with trade + decision fields.
    """
    paired = []

    for trade in trades:
        trade_ts = trade.get("timestamp", "")

        # Find the latest decision at or before this trade
        best_decision = {}
        for d in decisions:
            d_ts = d.get("timestamp", "")
            if d_ts <= trade_ts:
                best_decision = d
            else:
                break

        paired.append({
            "trade": trade,
            "decision": best_decision,
        })

    return paired


# ---------------------------------------------------------------------------
# Replay display
# ---------------------------------------------------------------------------

def format_trade_step(index: int, pair: dict) -> str:
    """Format a single trade step for display.

    Args:
        index: Step number (1-based).
        pair: Dict with 'trade' and 'decision' keys.

    Returns:
        Formatted multi-line string.
    """
    t = pair["trade"]
    d = pair["decision"]

    action = t.get("action", "?")
    price = _safe_float(t.get("price", 0))
    quantity = _safe_float(t.get("quantity", 0))
    pnl = _safe_float(t.get("pnl", 0))
    cash = _safe_float(t.get("cash_after", 0))
    strategy = t.get("strategy", "unknown")
    strength = t.get("strength", "unknown")
    market = t.get("market_condition", "unknown")
    timestamp = t.get("timestamp", "?")[:19]

    confidence = _safe_float(d.get("confidence", 0))
    reasoning = d.get("reasoning", "N/A")
    signals = d.get("signals", "")

    # Outcome label
    if action == "HOLD":
        outcome = "No trade"
    elif pnl > 0:
        outcome = f"WIN (+${pnl:.4f})"
    elif pnl < 0:
        outcome = f"LOSS (${pnl:.4f})"
    else:
        outcome = "Entry" if action == "BUY" else "Flat"

    lines = [
        f"{'=' * 60}",
        f"  Step {index}  |  {timestamp}",
        f"{'=' * 60}",
        f"  Market:     {market}  |  Strategy: {strategy}  |  Signal: {strength}",
        f"  Price:      ${price:,.2f}",
        f"{'─' * 60}",
        f"  Decision:   {action}  (confidence: {confidence:.2f})",
        f"  Signals:    {signals if signals else 'none'}",
        f"  Reasoning:  {reasoning}",
        f"{'─' * 60}",
        f"  Quantity:   {quantity:.6f} BTC",
        f"  P&L:        ${pnl:,.4f}",
        f"  Cash After: ${cash:,.4f}",
        f"  Outcome:    {outcome}",
    ]

    return "\n".join(lines)


def _safe_float(val) -> float:
    """Safely convert a value to float."""
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


# ---------------------------------------------------------------------------
# Replay runner
# ---------------------------------------------------------------------------

def replay(last_n: int = 0, step_mode: bool = False) -> None:
    """Replay trades with full context.

    Args:
        last_n: Only replay the last N trades (0 = all).
        step_mode: If True, pause after each trade for user input.
    """
    trades = load_trades()
    decisions = load_decisions()
    rejected = load_rejected()

    if not trades:
        print("No trades to replay. Run a trading cycle first.")
        return

    if last_n > 0:
        trades = trades[-last_n:]

    pairs = match_trades_to_decisions(trades, decisions)

    # Header
    total = len(pairs)
    actions = [p["trade"].get("action", "HOLD") for p in pairs]
    buys = actions.count("BUY")
    sells = actions.count("SELL")
    holds = actions.count("HOLD")

    pnl_values = [_safe_float(p["trade"].get("pnl", 0)) for p in pairs]
    total_pnl = sum(pnl_values)
    wins = sum(1 for p in pnl_values if p > 0)
    losses = sum(1 for p in pnl_values if p < 0)

    print("\n" + "=" * 60)
    print("  TRADE REPLAY")
    print("=" * 60)
    print(f"  Total entries: {total}  (BUY: {buys}  SELL: {sells}  HOLD: {holds})")
    print(f"  Total P&L:     ${total_pnl:,.4f}  (Wins: {wins}  Losses: {losses})")
    print(f"  Rejected:      {len(rejected)} trades blocked by guards")
    print("=" * 60)

    # Replay each trade
    for i, pair in enumerate(pairs, 1):
        print(format_trade_step(i, pair))

        if step_mode and i < total:
            try:
                input("\n  Press Enter for next trade (Ctrl+C to stop)... ")
            except KeyboardInterrupt:
                print("\n\n  Replay stopped.")
                return

    # Footer
    print("\n" + "=" * 60)
    print("  REPLAY COMPLETE")
    print("=" * 60)

    if rejected:
        print(f"\n  --- Rejected Trades ({len(rejected)}) ---")
        for r in rejected[-10:]:
            ts = r.get("timestamp", "?")[:19]
            act = r.get("action", "?")
            conf = r.get("confidence", "?")
            reason = r.get("reason", "?")
            print(f"  {ts}  {act:4s}  conf={conf}  {reason}")

    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """Parse CLI args and run replay."""
    args = sys.argv[1:]

    last_n = 0
    step_mode = False

    i = 0
    while i < len(args):
        if args[i] == "--last" and i + 1 < len(args):
            last_n = int(args[i + 1])
            i += 2
        elif args[i] == "--step":
            step_mode = True
            i += 1
        else:
            i += 1

    replay(last_n=last_n, step_mode=step_mode)


if __name__ == "__main__":
    main()
