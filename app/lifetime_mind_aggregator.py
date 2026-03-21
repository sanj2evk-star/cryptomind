"""
lifetime_mind_aggregator.py — CryptoMind v7.4 Chunk 2: Lifetime Continuity.

Aggregates mind evolution data across all sessions to provide:
    - Lifetime totals (cycles, trades, hours, sessions)
    - Cross-session evolution curve
    - Long-term skill averages
    - Session comparison (current vs best vs average)

Reuses mind_evolution's compute functions — does NOT duplicate logic.
This module is READ-ONLY.
"""

from __future__ import annotations

import time
import threading
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_state: dict = {}
_last_compute: float = 0
_COMPUTE_INTERVAL = 120  # 2 min

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def compute() -> dict:
    """Aggregate lifetime mind stats across all sessions.

    Returns dict with: lifetime, current_session, best_session, skill_averages,
    evolution_curve, computed_at.
    """
    global _state, _last_compute

    now = time.time()
    if (now - _last_compute) < _COMPUTE_INTERVAL and _state:
        return _state

    try:
        import db
        import session_manager

        sid = session_manager.get_session_id()
        system = db.get_system_state() or {}
        sessions = db.get_all_sessions()

        # --- Lifetime totals ---
        total_sessions = len(sessions)
        completed = sum(1 for s in sessions if not s.get("is_active"))
        total_cycles = system.get("total_lifetime_cycles", 0)
        total_trades = system.get("total_lifetime_trades", 0)
        total_hours = float(system.get("system_age_hours", 0))

        lifetime_pnl = sum(float(s.get("realized_pnl", 0)) for s in sessions)
        lifetime_buys = sum(int(s.get("total_buys", 0)) for s in sessions)
        lifetime_sells = sum(int(s.get("total_sells", 0)) for s in sessions)

        # --- Current session stats ---
        current = None
        for s in sessions:
            if s.get("is_active"):
                current = s
                break

        current_session = {}
        if current:
            current_session = {
                "session_id":   current["session_id"],
                "version":      current.get("app_version", "?"),
                "cycles":       current.get("total_cycles", 0),
                "trades":       current.get("total_trades", 0),
                "buys":         current.get("total_buys", 0),
                "sells":        current.get("total_sells", 0),
                "pnl":          round(float(current.get("realized_pnl", 0)), 6),
                "started_at":   current.get("started_at"),
            }

        # --- Best session (by PnL) ---
        best_session = {}
        if sessions:
            best = max(sessions, key=lambda s: float(s.get("realized_pnl", 0)))
            if float(best.get("realized_pnl", 0)) > 0:
                best_session = {
                    "session_id": best["session_id"],
                    "version":    best.get("app_version", "?"),
                    "trades":     best.get("total_trades", 0),
                    "pnl":        round(float(best.get("realized_pnl", 0)), 6),
                }

        # --- Skill averages from evolution snapshots ---
        skill_averages = _compute_skill_averages(db)

        # --- Evolution curve (from snapshots) ---
        evolution_curve = _compute_evolution_curve(db)

        # --- Current evolution state ---
        current_evo = {}
        try:
            import mind_evolution
            evo = mind_evolution.compute_evolution_score()
            current_evo = {
                "score":      evo.get("evolution_score", 0),
                "level":      evo.get("mind_level", {}).get("level", "Seed"),
                "confidence": evo.get("confidence", {}).get("score", 0),
            }
        except Exception:
            pass

        result = {
            "lifetime": {
                "total_sessions":   total_sessions,
                "completed_sessions": completed,
                "total_cycles":     total_cycles,
                "total_trades":     total_trades,
                "total_hours":      round(total_hours, 2),
                "total_buys":       lifetime_buys,
                "total_sells":      lifetime_sells,
                "lifetime_pnl":     round(lifetime_pnl, 6),
                "avg_trades_per_session": round(total_trades / max(total_sessions, 1), 1),
                "avg_pnl_per_session": round(lifetime_pnl / max(total_sessions, 1), 6),
            },
            "current_session":   current_session,
            "best_session":      best_session,
            "current_evolution": current_evo,
            "skill_averages":    skill_averages,
            "evolution_curve":   evolution_curve,
            "computed_at":       datetime.now(timezone.utc).isoformat(),
        }

        with _lock:
            _state = result
            _last_compute = time.time()

        return result

    except Exception as e:
        return {"error": str(e), "lifetime": {}, "computed_at": datetime.now(timezone.utc).isoformat()}


def _compute_skill_averages(db_mod) -> dict:
    """Average skill scores across all evolution snapshots."""
    try:
        snapshots = db_mod.get_evolution_history(limit=500)
        if not snapshots:
            return {"warming_up": True, "message": "No evolution snapshots yet."}

        skills = [
            "discipline_score", "risk_control_score", "timing_score",
            "adaptation_score", "regime_reading_score", "opportunity_score",
            "consistency_score", "self_correction_score", "patience_score",
        ]
        labels = [
            "Discipline", "Risk Control", "Timing", "Adaptation",
            "Regime Reading", "Opportunity Sensing", "Consistency",
            "Self-Correction", "Patience",
        ]

        n = len(snapshots)
        averages = []
        for skill, label in zip(skills, labels):
            vals = [int(s.get(skill, 0)) for s in snapshots]
            avg = sum(vals) / max(n, 1)
            best = max(vals) if vals else 0
            latest = vals[0] if vals else 0  # snapshots are newest-first
            trend = "improving" if latest > avg else "declining" if latest < avg * 0.9 else "stable"
            averages.append({
                "name":    label,
                "key":     skill,
                "average": round(avg, 1),
                "best":    best,
                "latest":  latest,
                "trend":   trend,
                "samples": n,
            })

        return {
            "warming_up": n < 3,
            "skills":     averages,
            "snapshots":  n,
        }
    except Exception:
        return {"warming_up": True, "message": "Error computing skill averages."}


def _compute_evolution_curve(db_mod) -> list[dict]:
    """Build a simplified evolution score timeline for charting."""
    try:
        snapshots = db_mod.get_evolution_history(limit=200)
        if not snapshots:
            return []
        # Return newest-last for charting
        return [
            {
                "cycle":     s.get("cycle_number", 0),
                "score":     s.get("evolution_score", 0),
                "level":     s.get("mind_level", "Seed"),
                "timestamp": s.get("timestamp"),
                "session_id": s.get("session_id"),
            }
            for s in reversed(snapshots)
        ]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

def get() -> dict:
    if not _state:
        return compute()
    return _state


def get_lifetime_summary() -> dict:
    """Quick summary for dashboard strips."""
    s = get()
    lt = s.get("lifetime", {})
    return {
        "total_trades":   lt.get("total_trades", 0),
        "total_sessions": lt.get("total_sessions", 0),
        "total_hours":    lt.get("total_hours", 0),
        "lifetime_pnl":   lt.get("lifetime_pnl", 0),
    }
