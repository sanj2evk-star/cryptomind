"""
action_narrator.py — CryptoMind v7.4 Observer Core: Trade Narrator.

Read-only narration of existing trading activity.
Does NOT make decisions, does NOT modify trades.
Reads from auto_trader state and trade_ledger,
and produces human-readable commentary about what happened and why.

Tone: calm, clear, anti-dopamine.  Explains reasoning without hype.
"""

from __future__ import annotations

from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Narration templates (keyed by action + context)
# ---------------------------------------------------------------------------

_BUY_NARRATIONS = {
    "high_conf":     "Entered with conviction.  Signals aligned, size reflects it.",
    "medium_conf":   "Modest entry.  Signal is there, but not screaming.",
    "low_conf":      "Small position.  More of a toe-in than a conviction play.",
    "probe":         "Probe trade.  Testing the water with minimal size.",
    "breakout":      "Breakout entry.  Volatility is high — staying alert.",
    "sleeping_probe": "Probe during quiet market.  Exploring, not committing.",
}

_SELL_NARRATIONS = {
    "profit":        "Took profit.  Not greedy — locking in what the market gave.",
    "stop":          "Cut the loss.  Discipline over hope.",
    "target":        "Hit the target.  Clean exit.",
    "hold_timeout":  "Held too long.  Exiting to free up capital.",
    "strategy_kill": "Strategy got killed.  Exiting as part of risk protocol.",
}

_HOLD_NARRATIONS = {
    "sleeping":      "Market is asleep.  Nothing to do.",
    "cooldown":      "In cooldown.  Waiting for the timer.",
    "no_edge":       "No edge.  Sitting on hands.",
    "filtered":      "Signal was there but got filtered.  Not clean enough.",
    "exposed":       "Already fully exposed.  No room for more.",
}

# ---------------------------------------------------------------------------
# Core narration
# ---------------------------------------------------------------------------

def narrate_trade(action: str, price: float, score: float,
                  confidence: float, strategy: str, regime: str,
                  entry_type: str = "full", pnl: float = 0.0,
                  reason: str = "", market_state: str = "SLEEPING",
                  hold_cycles: int = 0) -> dict:
    """Generate narration for a trade event.

    Returns dict with: action, narration, detail, mood_hint.
    """
    if action == "BUY":
        return _narrate_buy(price, score, confidence, strategy, regime,
                            entry_type, market_state)
    elif action == "SELL":
        return _narrate_sell(price, score, confidence, strategy, regime,
                             pnl, reason, hold_cycles)
    else:
        return _narrate_hold(score, confidence, strategy, regime,
                             reason, market_state)


def _narrate_buy(price, score, conf, strategy, regime, entry_type, mkt_state):
    if entry_type == "probe":
        key = "sleeping_probe" if mkt_state == "SLEEPING" else "probe"
    elif conf >= 0.70:
        key = "high_conf"
    elif conf >= 0.50:
        key = "medium_conf"
    else:
        key = "low_conf"

    if mkt_state == "BREAKOUT":
        key = "breakout"

    narration = _BUY_NARRATIONS.get(key, _BUY_NARRATIONS["medium_conf"])

    detail = (
        f"Bought via {strategy} in {regime} at ${price:,.2f}.  "
        f"Score {score:.0f}/100, confidence {conf*100:.0f}%.  "
        f"Entry: {entry_type}."
    )

    return {
        "action":    "BUY",
        "narration": narration,
        "detail":    detail,
        "mood_hint": "confident_steady" if conf > 0.6 else "focused_selective",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _narrate_sell(price, score, conf, strategy, regime, pnl, reason, hold_cycles):
    if pnl > 0:
        key = "profit"
    elif "kill" in (reason or "").lower() or "killed" in (reason or "").lower():
        key = "strategy_kill"
    elif hold_cycles > 80:
        key = "hold_timeout"
    else:
        key = "stop"

    narration = _SELL_NARRATIONS.get(key, _SELL_NARRATIONS["profit" if pnl > 0 else "stop"])

    pnl_word = "profit" if pnl > 0 else "loss"
    detail = (
        f"Sold via {strategy} in {regime} at ${price:,.2f}.  "
        f"P&L: {'+'if pnl>0 else ''}{pnl:.4f} ({pnl_word}).  "
        f"Held for {hold_cycles} cycles."
    )

    return {
        "action":    "SELL",
        "narration": narration,
        "detail":    detail,
        "mood_hint": "confident_steady" if pnl > 0 else "recovering_learning",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _narrate_hold(score, conf, strategy, regime, reason, mkt_state):
    if mkt_state == "SLEEPING":
        key = "sleeping"
    elif "cooldown" in (reason or "").lower():
        key = "cooldown"
    elif "exposure" in (reason or "").lower() or "cap" in (reason or "").lower():
        key = "exposed"
    elif "filter" in (reason or "").lower() or "edge" in (reason or "").lower():
        key = "filtered"
    else:
        key = "no_edge"

    narration = _HOLD_NARRATIONS.get(key, _HOLD_NARRATIONS["no_edge"])

    detail = (
        f"Held.  Score {score:.0f}/100, confidence {conf*100:.0f}%.  "
        f"Regime: {regime}.  Reason: {reason or 'no clear edge'}."
    )

    return {
        "action":    "HOLD",
        "narration": narration,
        "detail":    detail,
        "mood_hint": "idle_waiting" if mkt_state == "SLEEPING" else "calm_observing",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Batch narration (for recent trades)
# ---------------------------------------------------------------------------

def narrate_recent_trades(trades: list[dict], limit: int = 5) -> list[dict]:
    """Narrate a list of recent trade dicts from trade_ledger / CSV.

    Returns list of narration dicts (newest first).
    """
    results = []
    for t in trades[:limit]:
        action = (t.get("action") or "HOLD").upper()
        if action not in ("BUY", "SELL"):
            continue
        n = narrate_trade(
            action=action,
            price=float(t.get("price", 0)),
            score=float(t.get("score", 0)),
            confidence=float(t.get("confidence", 0)),
            strategy=t.get("strategy", "?"),
            regime=t.get("regime", "?"),
            entry_type=t.get("entry_type", "full"),
            pnl=float(t.get("pnl", 0)),
            reason=t.get("reason", ""),
        )
        n["trade_id"] = t.get("trade_id")
        results.append(n)
    return results
