"""
milestone_engine.py — CryptoMind v7.4 Chunk 2: Milestone Detection.

Auto-detects meaningful events from system data and records them as milestones.
Events must be real achievements, not participation trophies.

Milestone categories:
    trade       — trade count thresholds (10, 25, 50, 100, 250, 500)
    recovery    — recovered from significant drawdown
    discipline  — completed session with high discipline
    evolution   — levelled up in mind evolution
    session     — version upgrades, long-running sessions
    learning    — memory depth, adaptation milestones

All milestones are non-cheesy, factual, and grounded.
This module is READ-ONLY for trading tables — writes only to milestones table.
"""

from __future__ import annotations

import time
import threading
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Milestone definitions
# ---------------------------------------------------------------------------

_TRADE_THRESHOLDS = [
    (10,   "First 10 trades completed.",
           "Early data. The system is starting to learn what works."),
    (25,   "25 trades executed.",
           "Enough trades to see patterns. Skill scores becoming meaningful."),
    (50,   "50 trades — evidence base established.",
           "Reliable trade data. Adaptations and corrections have real weight now."),
    (100,  "100 trades completed.",
           "Solid foundation. Personality and skill profile are well-grounded."),
    (250,  "250 trades — deep experience.",
           "Extensive market exposure. Pattern recognition at its best."),
    (500,  "500 trades — veteran system.",
           "Rare depth of experience. Lessons compounded across hundreds of decisions."),
]

_MEMORY_THRESHOLDS = [
    (5,    "First 5 memories stored.",
           "Beginning to remember what worked and what didn't."),
    (20,   "20 memories accumulated.",
           "Building a meaningful experience base."),
    (50,   "50 memories — deep learning history.",
           "Rich lesson archive. Past mistakes becoming future advantages."),
]

_ADAPTATION_THRESHOLDS = [
    (5,    "First 5 adaptations applied.",
           "System has started to self-correct based on evidence."),
    (20,   "20 successful adaptations.",
           "Consistent self-tuning. The system genuinely evolves."),
    (50,   "50 adaptations — deeply self-correcting.",
           "A half-century of evidence-based adjustments."),
]

# Evolution levels (from mind_evolution)
_LEVEL_ORDER = [
    "Seed", "Novice", "Apprentice", "Monk", "Ranger",
    "Sniper", "Operator", "Strategist", "Mastermind", "Oracle",
]

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_last_check: float = 0
_CHECK_INTERVAL = 300  # check every 5 min
_known_milestones: set = set()  # title hashes we've already recorded

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def check_and_record(session_id: int = None) -> list[dict]:
    """Check for new milestones and record any found.

    Returns list of newly created milestones (may be empty).
    """
    global _last_check

    now = time.time()
    if (now - _last_check) < _CHECK_INTERVAL:
        return []
    _last_check = now

    try:
        import db
        import session_manager
        sid = session_id or session_manager.get_session_id()
        if not sid:
            return []

        # Load existing milestones to avoid duplicates
        existing = db.get_milestones(limit=200)
        existing_titles = {m["title"] for m in existing}
        with _lock:
            _known_milestones.update(existing_titles)

        new_milestones = []

        # Get current data
        trade_summary = db.get_trade_summary(session_id=sid)
        system = db.get_system_state() or {}
        total_trades = trade_summary.get("total", 0)
        lifetime_trades = system.get("total_lifetime_trades", total_trades)
        memories = db.get_active_memories(limit=200)
        journal = db.get_adaptation_journal(session_id=sid, limit=200)
        allowed_adaptations = sum(
            1 for j in journal if j.get("allowed_or_blocked") == "allowed"
        )

        # Get evolution info
        evo_score = 0
        evo_level = "Seed"
        try:
            import mind_evolution
            evo = mind_evolution.compute_evolution_score()
            evo_score = evo.get("evolution_score", 0)
            evo_level = evo.get("mind_level", {}).get("level", "Seed")
        except Exception:
            pass

        # --- Check trade milestones ---
        for threshold, title, desc in _TRADE_THRESHOLDS:
            if lifetime_trades >= threshold and title not in _known_milestones:
                m = _record(db, sid, title, desc, "trade", evo_score, evo_level)
                if m:
                    new_milestones.append(m)

        # --- Check memory milestones ---
        mem_count = len(memories)
        for threshold, title, desc in _MEMORY_THRESHOLDS:
            if mem_count >= threshold and title not in _known_milestones:
                m = _record(db, sid, title, desc, "learning", evo_score, evo_level)
                if m:
                    new_milestones.append(m)

        # --- Check adaptation milestones ---
        for threshold, title, desc in _ADAPTATION_THRESHOLDS:
            if allowed_adaptations >= threshold and title not in _known_milestones:
                m = _record(db, sid, title, desc, "learning", evo_score, evo_level)
                if m:
                    new_milestones.append(m)

        # --- Check evolution level-ups ---
        for i, level in enumerate(_LEVEL_ORDER):
            if level == evo_level and i > 0:
                # Record reaching this level
                title = f"Reached {level} level."
                if title not in _known_milestones:
                    desc = f"Evolution score crossed the {level} threshold at {evo_score} points."
                    m = _record(db, sid, title, desc, "evolution", evo_score, evo_level)
                    if m:
                        new_milestones.append(m)

        # --- Check win rate milestone ---
        win_rate = float(trade_summary.get("win_rate", 0))
        if total_trades >= 20 and win_rate >= 0.6:
            title = f"60%+ win rate over {total_trades} trades."
            if title not in _known_milestones:
                m = _record(db, sid, title,
                            f"Sustained {win_rate*100:.0f}% win rate — consistent edge.",
                            "trade", evo_score, evo_level)
                if m:
                    new_milestones.append(m)

        # --- Check recovery milestone ---
        net_pnl = float(trade_summary.get("net_pnl", 0))
        worst = float(trade_summary.get("worst_trade", 0))
        if worst < -0.5 and net_pnl > 0:
            title = "Recovered from drawdown into profit."
            if title not in _known_milestones:
                m = _record(db, sid, title,
                            f"Took a ${abs(worst):.4f} hit but recovered to +${net_pnl:.4f} net.",
                            "recovery", evo_score, evo_level)
                if m:
                    new_milestones.append(m)

        # --- Check session longevity ---
        sessions = db.get_all_sessions()
        completed_sessions = sum(1 for s in sessions if not s.get("is_active"))
        for threshold, label in [(3, "3 sessions completed."), (5, "5 sessions completed."), (10, "10 sessions completed.")]:
            if completed_sessions >= threshold and label not in _known_milestones:
                m = _record(db, sid, label,
                            f"System has run through {completed_sessions} full sessions. Continuity building.",
                            "session", evo_score, evo_level)
                if m:
                    new_milestones.append(m)

        # Feed new milestones to mind feed
        if new_milestones:
            try:
                import mind_feed_engine
                for ms in new_milestones:
                    mind_feed_engine.on_narration(
                        f"Milestone: {ms['title']}",
                        detail=ms.get("description"),
                    )
            except Exception:
                pass

        return new_milestones

    except Exception as e:
        print(f"[milestone_engine] Error: {e}")
        return []


def _record(db_mod, session_id: int, title: str, description: str,
            milestone_type: str, evo_score: int, evo_level: str) -> dict | None:
    """Insert milestone and add to known set. Returns dict or None."""
    try:
        import session_manager
        version = session_manager.get_version()
        mid = db_mod.insert_milestone(
            session_id=session_id,
            title=title,
            description=description,
            milestone_type=milestone_type,
            evolution_score_at=evo_score,
            mind_level_at=evo_level,
            version_tag=version,
        )
        with _lock:
            _known_milestones.add(title)
        print(f"[milestone] {title}")
        return {
            "milestone_id": mid,
            "title":        title,
            "description":  description,
            "type":         milestone_type,
            "evo_score":    evo_score,
            "evo_level":    evo_level,
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

def get_milestones(limit: int = 30) -> list[dict]:
    """Retrieve milestones from DB."""
    try:
        import db
        return db.get_milestones(limit=limit)
    except Exception:
        return []


def get_summary() -> dict:
    """Quick milestone summary."""
    milestones = get_milestones(limit=200)
    types = {}
    for m in milestones:
        t = m.get("milestone_type", "other")
        types[t] = types.get(t, 0) + 1
    return {
        "total":      len(milestones),
        "by_type":    types,
        "latest":     milestones[0] if milestones else None,
    }
