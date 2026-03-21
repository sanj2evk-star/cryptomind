"""
daily_review.py — CryptoMind v7 Daily Review Generator.

Generates end-of-day machine reflections. Calm, factual, concise, intelligent.
No marketing fluff. No romanticized commentary.

Reviews are stored in DB and surfaced in UI.
Can be triggered automatically (every 24h) or on demand via API.
"""

from __future__ import annotations

from datetime import datetime, date, timezone

import db
import session_manager

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REVIEW_HOUR_UTC = 0  # Generate review at midnight UTC (can be adjusted)


# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

_last_review_date: str = ""  # YYYY-MM-DD of last generated review


# ---------------------------------------------------------------------------
# Auto-check — called from trading loop
# ---------------------------------------------------------------------------

def check_daily_review(current_hour_utc: int = None) -> dict | None:
    """Check if it's time to generate a daily review.

    Called each cycle. Returns review dict if generated, None otherwise.
    """
    global _last_review_date

    now = datetime.now(timezone.utc)
    today = now.date().isoformat()

    if current_hour_utc is None:
        current_hour_utc = now.hour

    # Only generate once per day, after REVIEW_HOUR_UTC
    if today == _last_review_date:
        return None

    if current_hour_utc < REVIEW_HOUR_UTC:
        return None

    # Check if review already exists for today
    session_id = session_manager.get_session_id()
    if not session_id:
        return None

    existing = db.get_daily_reviews(session_id=session_id, limit=1)
    if existing and existing[0].get("review_date") == today:
        _last_review_date = today
        return None

    # Generate review
    review = generate_review(today)
    _last_review_date = today
    return review


# ---------------------------------------------------------------------------
# Review generation — can also be called on demand
# ---------------------------------------------------------------------------

def generate_review(review_date: str = None) -> dict:
    """Generate a daily review for the given date (default: today).

    Returns the review dict and stores it in DB.
    """
    session_id = session_manager.get_session_id()
    if not session_id:
        return {"error": "No active session"}

    if not review_date:
        review_date = date.today().isoformat()

    # Gather data
    trades, total = db.get_trades(session_id=session_id, limit=500)

    # Filter to today's trades (or all if very few)
    today_trades = [t for t in trades if t.get("timestamp", "").startswith(review_date)]
    if len(today_trades) < 2:
        today_trades = trades[:50]  # Use recent trades if today is thin

    sells = [t for t in today_trades if t.get("action") == "SELL"]
    buys = [t for t in today_trades if t.get("action") == "BUY"]
    wins = [t for t in sells if (t.get("pnl") or 0) > 0]
    losses = [t for t in sells if (t.get("pnl") or 0) < 0]
    net_pnl = sum(t.get("pnl", 0) for t in sells)

    # Strategy analysis
    strat_pnl: dict[str, float] = {}
    strat_count: dict[str, int] = {}
    for t in today_trades:
        s = t.get("strategy", "unknown")
        strat_count[s] = strat_count.get(s, 0) + 1
        if t.get("action") == "SELL":
            strat_pnl[s] = strat_pnl.get(s, 0) + (t.get("pnl", 0))

    best_strat = max(strat_pnl, key=strat_pnl.get) if strat_pnl else "none"
    worst_strat = min(strat_pnl, key=strat_pnl.get) if strat_pnl else "none"

    # Regime analysis
    regime_counts: dict[str, int] = {}
    for t in today_trades:
        r = t.get("regime", "SLEEPING")
        regime_counts[r] = regime_counts.get(r, 0) + 1
    strongest_regime = max(regime_counts, key=regime_counts.get) if regime_counts else "SLEEPING"
    weakest_regime = min(regime_counts, key=regime_counts.get) if regime_counts else "SLEEPING"

    # Entry type analysis
    probe_trades = [t for t in today_trades if "probe" in t.get("entry_type", "")]
    full_trades = [t for t in today_trades if t.get("entry_type", "full") == "full"]

    # Pattern analysis
    best_pattern = _find_best_pattern(sells)
    failed_pattern = _find_failed_pattern(sells)

    # --- Generate narrative sections ---
    market_obs = _market_observation(regime_counts, today_trades)
    behavior_obs = _behavior_observation(
        len(buys), len(sells), len(probe_trades), len(full_trades), net_pnl
    )
    what_worked = _what_worked(wins, best_strat, strat_pnl, probe_trades)
    what_failed = _what_failed(losses, worst_strat, strat_pnl)
    next_bias = _next_day_bias(net_pnl, len(wins), len(losses), strongest_regime)

    # Confidence in review quality
    confidence = min(0.9, len(today_trades) / 20)

    # Store review
    review_data = {
        "review_date": review_date,
        "trades_count": len(today_trades),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "net_pnl": round(net_pnl, 6),
        "best_strategy": best_strat,
        "worst_strategy": worst_strat,
        "best_pattern": best_pattern,
        "failed_pattern": failed_pattern,
        "what_worked": what_worked,
        "what_failed": what_failed,
        "behavior_observation": behavior_obs,
        "market_observation": market_obs,
        "next_day_bias": next_bias,
        "confidence": round(confidence, 2),
    }

    review_id = db.insert_daily_review(session_id, **review_data)

    # Update system state
    db.upsert_system_state(
        last_daily_review_at=datetime.now(timezone.utc).isoformat()
    )

    print(f"[daily_review] Generated review #{review_id} for {review_date}: "
          f"{len(today_trades)} trades, PnL ${net_pnl:.6f}")

    return {"review_id": review_id, **review_data}


# ---------------------------------------------------------------------------
# Narrative generators — factual, concise, no fluff
# ---------------------------------------------------------------------------

def _market_observation(regime_counts: dict, trades: list) -> str:
    """Market summary section."""
    if not regime_counts:
        return "Insufficient data for market assessment."

    dominant = max(regime_counts, key=regime_counts.get)
    total = sum(regime_counts.values())

    parts = []
    if dominant == "SLEEPING":
        dom_pct = regime_counts.get("SLEEPING", 0) / total * 100
        parts.append(f"Market spent {dom_pct:.0f}% of time in SLEEPING state.")
        parts.append("Low volatility, compressed ranges, limited opportunity set.")
    elif dominant == "ACTIVE":
        parts.append("Active market conditions dominated the session.")
        parts.append("Clear directional signals with tradeable ranges.")
    elif dominant == "WAKING_UP":
        parts.append("Market transitioning between states.")
        parts.append("Volatility building but direction still forming.")
    elif dominant == "BREAKOUT":
        parts.append("Breakout conditions detected during session.")
        parts.append("Elevated volatility with momentum-driven moves.")

    if "SLEEPING" in regime_counts and "ACTIVE" in regime_counts:
        parts.append("Mixed regime environment — required adaptive positioning.")

    return " ".join(parts)


def _behavior_observation(buys: int, sells: int, probes: int,
                          full: int, net_pnl: float) -> str:
    """System behavior summary."""
    total = buys + sells
    parts = []

    if total == 0:
        return "System stayed completely flat. No entries or exits."

    if total < 3:
        parts.append("Low activity session. System was selective.")
    elif total > 15:
        parts.append("High activity session. Multiple entries and exits.")
    else:
        parts.append("Moderate activity. Balanced entry/exit cadence.")

    if probes > full and probes > 0:
        parts.append(f"Probe entries ({probes}) exceeded full entries ({full}).")
        parts.append("System leaned exploratory over committed.")
    elif full > probes and full > 0:
        parts.append(f"Full conviction entries ({full}) dominated over probes ({probes}).")

    if net_pnl > 0:
        parts.append("Net positive session.")
    elif net_pnl < 0:
        parts.append("Net negative session. Review entry quality.")
    else:
        parts.append("Break-even session.")

    return " ".join(parts)


def _what_worked(wins: list, best_strat: str, strat_pnl: dict,
                 probes: list) -> str:
    """What worked today."""
    parts = []

    if not wins:
        return "No winning trades to analyze."

    parts.append(f"{len(wins)} winning trade(s).")

    if best_strat != "none" and strat_pnl.get(best_strat, 0) > 0:
        parts.append(f"{best_strat} was the top performer (${strat_pnl[best_strat]:.6f}).")

    probe_wins = [t for t in wins if "probe" in t.get("entry_type", "")]
    if probe_wins:
        parts.append(f"Probe entries produced {len(probe_wins)} winner(s).")

    return " ".join(parts)


def _what_failed(losses: list, worst_strat: str, strat_pnl: dict) -> str:
    """What failed today."""
    if not losses:
        return "No losing trades. Clean session."

    parts = [f"{len(losses)} losing trade(s)."]

    if worst_strat != "none" and strat_pnl.get(worst_strat, 0) < 0:
        parts.append(f"{worst_strat} was the weakest (${strat_pnl[worst_strat]:.6f}).")

    # Check for common failure patterns
    sleeping_losses = [t for t in losses if t.get("regime") == "SLEEPING"]
    if sleeping_losses:
        parts.append(f"{len(sleeping_losses)} loss(es) in SLEEPING market — consider reducing activity.")

    return " ".join(parts)


def _next_day_bias(net_pnl: float, wins: int, losses: int,
                   strongest_regime: str) -> str:
    """Suggested posture for next session."""
    if wins > losses * 2:
        bias = "Cautiously optimistic. Winning streak but don't over-extend."
    elif losses > wins * 2:
        bias = "Defensive. Tighten entry criteria and reduce exposure."
    elif net_pnl > 0:
        bias = "Neutral-to-bullish. Continue current approach with discipline."
    elif net_pnl < 0:
        bias = "Neutral-to-cautious. Review entries before adding."
    else:
        bias = "Neutral. Wait for clearer signals before committing."

    if strongest_regime == "SLEEPING":
        bias += " Market was quiet — watch for regime shift."
    elif strongest_regime == "BREAKOUT":
        bias += " Momentum present — be ready for continuation or reversal."

    return bias


def _find_best_pattern(sells: list) -> str:
    """Find the best performing pattern from sells."""
    if not sells:
        return "none"
    best = max(sells, key=lambda t: t.get("pnl", 0))
    if best.get("pnl", 0) <= 0:
        return "none"
    return f"{best.get('strategy', '?')} in {best.get('regime', '?')} ({best.get('entry_type', 'full')})"


def _find_failed_pattern(sells: list) -> str:
    """Find the worst performing pattern from sells."""
    if not sells:
        return "none"
    worst = min(sells, key=lambda t: t.get("pnl", 0))
    if worst.get("pnl", 0) >= 0:
        return "none"
    return f"{worst.get('strategy', '?')} in {worst.get('regime', '?')} ({worst.get('entry_type', 'full')})"


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def get_latest_review() -> dict | None:
    """Get the most recent daily review for UI display."""
    return db.get_latest_review()


def get_review_history(limit: int = 10) -> list[dict]:
    """Get review history."""
    session_id = session_manager.get_session_id()
    return db.get_daily_reviews(session_id=session_id, limit=limit)
