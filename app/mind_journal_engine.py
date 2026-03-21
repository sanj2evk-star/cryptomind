"""
mind_journal_engine.py — CryptoMind v7.4 Chunk 3: Daily Reflections.

Generates structured daily journal entries with:
    - Key insight of the day
    - Mistakes and lessons
    - Bias shifts observed
    - Mood arc through the session
    - Market observation

Observer module — reads from multiple tables, writes to mind_journal_entries
(observer-owned table).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, date

# Cache control
_cache = None
_cache_ts = 0
_CACHE_TTL = 180  # seconds


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Journal generation
# ---------------------------------------------------------------------------

def _derive_key_insight(trades: list[dict], snapshots: list[dict],
                         memories: list[dict]) -> str:
    """Derive the single most important insight from today's data."""
    if not trades and not snapshots:
        return "Not enough activity yet — still observing."

    # Check trade outcomes
    sells = [t for t in trades if t.get("action") == "SELL"]
    wins = [t for t in sells if (t.get("pnl", 0) or 0) > 0]
    losses = [t for t in sells if (t.get("pnl", 0) or 0) < 0]

    if len(sells) >= 3 and len(wins) == 0:
        return "Every closed trade was a loss — something fundamental needs to change."

    if len(sells) >= 3 and len(losses) == 0:
        return "Perfect day — but don't confuse a good market with good decisions."

    # Check regime consistency
    regimes = [s.get("regime") for s in snapshots if s.get("regime")]
    if regimes:
        unique = set(regimes)
        if len(unique) >= 3:
            return "Market was chaotic — multiple regime changes test patience and discipline."
        if len(unique) == 1 and regimes[0] == "SLEEPING":
            return "Dead market today. Patience is the only profitable strategy in SLEEPING."

    # Check memories for strong signals
    if memories:
        high_conf = [m for m in memories if (m.get("confidence_weight", 0) or 0) > 0.7]
        if high_conf:
            return f"Strong memory reinforced: {high_conf[0].get('lesson_text', 'pattern confirmed')}"

    net_pnl = sum(t.get("pnl", 0) or 0 for t in trades)
    if net_pnl > 0:
        return "Positive session — the system's reads were mostly right."
    elif net_pnl < 0:
        return "Negative session — review what the system got wrong, not just the market."
    else:
        return "Break-even day — the system is holding ground but not finding edge."


def _derive_mistakes(trades: list[dict], snapshots: list[dict]) -> str:
    """Identify notable mistakes or missteps."""
    mistakes = []

    sells = [t for t in trades if t.get("action") == "SELL"]
    bad_sells = [t for t in sells if (t.get("pnl", 0) or 0) < -0.001]

    if bad_sells:
        worst = min(bad_sells, key=lambda t: t.get("pnl", 0) or 0)
        mistakes.append(
            f"Worst loss: {worst.get('pnl', 0):.4f} on {worst.get('strategy', 'unknown')} "
            f"in {worst.get('regime', 'unknown')} regime."
        )

    # Overtrades: too many buys in short period
    buys = [t for t in trades if t.get("action") == "BUY"]
    if len(buys) > 5:
        mistakes.append(f"High trade frequency ({len(buys)} buys) — might be overtrading.")

    # Blocked trades (from snapshots)
    blocked = [s for s in snapshots if s.get("blocked_trade_reason")]
    if len(blocked) > 3:
        reasons = set(s["blocked_trade_reason"] for s in blocked)
        mistakes.append(f"Discipline guard blocked {len(blocked)} trades: {', '.join(list(reasons)[:3])}")

    if not mistakes:
        return "No obvious mistakes detected — either a clean session or not enough data."

    return " | ".join(mistakes)


def _derive_lessons(trades: list[dict], reviews: list[dict]) -> str:
    """Extract lessons from today's activity."""
    lessons = []

    sells = [t for t in trades if t.get("action") == "SELL"]
    if sells:
        strategies = {}
        for t in sells:
            s = t.get("strategy", "unknown")
            pnl = t.get("pnl", 0) or 0
            if s not in strategies:
                strategies[s] = []
            strategies[s].append(pnl)

        for strat, pnls in strategies.items():
            avg = sum(pnls) / len(pnls)
            if avg > 0:
                lessons.append(f"{strat} performed well (avg PnL: {avg:.4f})")
            elif avg < -0.001:
                lessons.append(f"{strat} underperformed (avg PnL: {avg:.4f})")

    # From daily reviews
    if reviews:
        latest = reviews[0]
        if latest.get("what_worked"):
            lessons.append(f"What worked: {latest['what_worked']}")
        if latest.get("what_failed"):
            lessons.append(f"What failed: {latest['what_failed']}")

    if not lessons:
        return "No clear lessons yet — need more trading data."

    return " | ".join(lessons[:4])


def _derive_mood_arc(mind_states: list[dict]) -> str:
    """Describe the mood progression through the session."""
    if not mind_states:
        return "No mood data captured yet."

    moods = [s.get("mind_state", "idle_waiting") for s in reversed(mind_states)]
    if len(moods) < 2:
        return f"Mood: {moods[0].replace('_', ' ')} (single reading)."

    unique_moods = []
    for m in moods:
        if not unique_moods or unique_moods[-1] != m:
            unique_moods.append(m)

    labels = [m.replace("_", " ") for m in unique_moods[:6]]
    return "Mood arc: " + " → ".join(labels)


def _derive_bias_shifts(intents: list[dict]) -> str:
    """Track how session intent/posture shifted during the day."""
    if not intents:
        return "No posture shifts recorded."

    if len(intents) == 1:
        return f"Steady posture: {intents[0].get('intent', 'neutral')} all session."

    unique = []
    for it in reversed(intents):
        intent = it.get("intent", "neutral")
        if not unique or unique[-1] != intent:
            unique.append(intent)

    if len(unique) == 1:
        return f"Consistent posture: {unique[0]} throughout."

    return "Posture shifts: " + " → ".join(unique[:5])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate(session_id: int = None) -> dict:
    """Generate today's journal entry.

    Returns the entry dict (also persists to DB).
    """
    global _cache, _cache_ts
    import time
    now = time.time()
    if _cache and (now - _cache_ts) < _CACHE_TTL:
        return _cache

    import db
    import session_manager

    sid = session_id or session_manager.get_session_id()
    if not sid:
        return {"warming_up": True, "error": "No active session"}

    today = date.today().isoformat()

    # Gather data
    trades_list, _ = db.get_trades(session_id=sid, limit=200)
    snapshots = db.get_recent_snapshots(sid, limit=200)
    memories = db.get_active_memories(session_id=sid, limit=20)
    reviews = db.get_daily_reviews(session_id=sid, limit=3)
    mind_states = db.get_mind_state_history(session_id=sid, limit=50)
    intents = db.get_session_intents(session_id=sid, limit=20)

    # Derive sections
    key_insight = _derive_key_insight(trades_list, snapshots, memories)
    mistakes = _derive_mistakes(trades_list, snapshots)
    lessons = _derive_lessons(trades_list, reviews)
    mood_arc = _derive_mood_arc(mind_states)
    bias_shifts = _derive_bias_shifts(intents)

    # Market summary line
    regimes = [s.get("regime", "SLEEPING") for s in snapshots if s.get("regime")]
    regime_counts = {}
    for r in regimes:
        regime_counts[r] = regime_counts.get(r, 0) + 1
    dominant = max(regime_counts, key=regime_counts.get) if regime_counts else "unknown"
    market_summary = f"Dominant regime: {dominant}. {len(snapshots)} cycles observed."

    # Trades reflection
    sells = [t for t in trades_list if t.get("action") == "SELL"]
    net_pnl = sum(t.get("pnl", 0) or 0 for t in trades_list)
    wins = len([t for t in sells if (t.get("pnl", 0) or 0) > 0])
    wr = round(wins / max(len(sells), 1) * 100, 1)
    trades_ref = f"{len(trades_list)} trades, {len(sells)} exits, {wr}% win rate, net PnL {net_pnl:+.4f}"

    confidence = 0.3
    if len(trades_list) >= 5:
        confidence = 0.5
    if len(snapshots) >= 20:
        confidence = min(confidence + 0.2, 0.9)

    entry = {
        "journal_date": today,
        "session_id": sid,
        "entry_type": "daily",
        "key_insight": key_insight,
        "mistakes_text": mistakes,
        "lessons_text": lessons,
        "bias_shifts_text": bias_shifts,
        "market_summary": market_summary,
        "mood_arc": mood_arc,
        "trades_reflection": trades_ref,
        "confidence": round(confidence, 2),
        "warming_up": len(snapshots) < 5 and len(trades_list) < 2,
    }

    # Persist to DB
    try:
        data_json = json.dumps({
            "total_trades": len(trades_list),
            "total_sells": len(sells),
            "net_pnl": round(net_pnl, 6),
            "win_rate": wr,
            "dominant_regime": dominant,
            "snapshots_count": len(snapshots),
        })
        db.insert_journal_entry(
            session_id=sid,
            journal_date=today,
            entry_type="daily",
            key_insight=key_insight,
            mistakes_text=mistakes,
            lessons_text=lessons,
            bias_shifts_text=bias_shifts,
            market_summary=market_summary,
            mood_arc=mood_arc,
            trades_reflection=trades_ref,
            confidence=round(confidence, 2),
            data_json=data_json,
        )
    except Exception:
        pass

    _cache = entry
    _cache_ts = now
    return entry


def get_journal_history(session_id: int = None, limit: int = 10) -> list[dict]:
    """Get past journal entries."""
    import db
    return db.get_journal_entries(session_id=session_id, limit=limit)
