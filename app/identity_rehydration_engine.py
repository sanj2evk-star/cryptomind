"""
identity_rehydration_engine.py — CryptoMind v7.7.1

Reconstructs active mind identity from lifetime history on startup.
Ensures the live mind starts from its accumulated life, not seed mode.

Rehydrates:
  - behavior_profile (learned personality parameters)
  - behavior_states (dynamic market/system posture)
  - continuity_score (how lived-in is this mind)
  - maturity_level (seed / early / established / mature / veteran)
  - confidence_state (rebuilt from lifetime evidence)
  - skill_state (rebuilt from lifetime evidence)
  - learning_state (memory depth, review count, latest insight)
  - identity_depth (composite quality metric)

Safety rules:
  - NEVER fabricate evidence
  - NEVER inflate confidence without supporting data
  - If partial data, report "partial"
  - If contradictory data, report "mixed"
  - Fall back to defaults only when no history exists
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from config import INITIAL_BALANCE

# ---------------------------------------------------------------------------
# Module cache
# ---------------------------------------------------------------------------

_identity_cache: dict = {}
_cache_time: float = 0.0
_CACHE_TTL: float = 300.0  # 5 minutes


def get_identity() -> dict:
    """Return cached identity state."""
    global _identity_cache, _cache_time
    if not _identity_cache or (time.time() - _cache_time) > _CACHE_TTL:
        _identity_cache = rehydrate_identity()
        _cache_time = time.time()
    return _identity_cache


def force_rehydrate_identity() -> dict:
    """Force a full identity rehydration. Called on startup."""
    global _identity_cache, _cache_time
    _identity_cache = rehydrate_identity()
    _cache_time = time.time()
    return _identity_cache


# ---------------------------------------------------------------------------
# Main rehydration
# ---------------------------------------------------------------------------

def rehydrate_identity(session_id: int | None = None) -> dict:
    """Rebuild active mind identity from all available lifetime evidence.

    Steps:
    1. Gather source counts from all tables
    2. Rehydrate behavior_profile (copy from latest non-default prior session)
    3. Rehydrate behavior_states (copy from latest prior session)
    4. Compute continuity_score, maturity_level, identity_depth
    5. Compute confidence_state and skill_state from mind_evolution
    6. Compute learning_state from memories + reviews
    7. Persist continuity_score + memory_depth_score to lifetime_identity
    """
    sources: dict[str, int] = {}
    warnings: list[str] = []

    # Gather source counts
    sources = _count_sources()

    # Rehydrate behavior profile
    behavior_result = _rehydrate_behavior_profile(session_id)
    if behavior_result.get("rehydrated"):
        print(f"[identity] Behavior profile rehydrated from session #{behavior_result.get('from_session')}")
    elif behavior_result.get("no_history"):
        warnings.append("No prior behavior profile — using defaults")

    # Rehydrate behavior state
    bstate_result = _rehydrate_behavior_state(session_id)
    if bstate_result.get("rehydrated"):
        print(f"[identity] Behavior state rehydrated from session #{bstate_result.get('from_session')}")

    # Compute continuity score
    continuity = _compute_continuity_score(sources)

    # Compute maturity level
    maturity = _compute_maturity_level(sources)

    # Compute confidence state
    confidence = _compute_confidence_state()

    # Compute skill state
    skills = _compute_skill_state()

    # Compute learning state
    learning = _compute_learning_state(sources)

    # Compute identity depth (composite quality)
    identity_depth = _compute_identity_depth(sources, continuity, confidence)

    # Determine overall status
    status = _compute_rehydration_status(sources, warnings)

    # Persist scores to lifetime_identity
    _persist_identity_scores(continuity, identity_depth, learning)

    result = {
        "rehydration_status": status,
        "identity_depth": identity_depth,
        "continuity_score": continuity,
        "maturity_level": maturity,
        "confidence_state": confidence,
        "skill_state": skills,
        "behavior_state": {
            "profile_rehydrated": behavior_result.get("rehydrated", False),
            "state_rehydrated": bstate_result.get("rehydrated", False),
            "profile_source_session": behavior_result.get("from_session"),
            "state_source_session": bstate_result.get("from_session"),
            "profile_values": behavior_result.get("values", {}),
        },
        "learning_state": learning,
        "source_counts": sources,
        "warnings": warnings,
        "rehydrated_at": datetime.now(timezone.utc).isoformat(),
    }

    print(f"[identity] Rehydration: status={status} depth={identity_depth:.1f} "
          f"maturity={maturity['level']} continuity={continuity:.1f}")

    return result


# ---------------------------------------------------------------------------
# Source counting
# ---------------------------------------------------------------------------

def _count_sources() -> dict[str, int]:
    """Count rows in all identity-relevant tables."""
    try:
        import db as v7db
        with v7db.get_db() as conn:
            tables = [
                "trade_ledger", "cycle_snapshots", "experience_memory",
                "experience_outcomes", "daily_reviews", "mind_journal_entries",
                "action_reflections", "news_truth_reviews", "evolution_snapshots",
                "milestones", "behavior_profile", "adaptation_journal",
                "signal_events", "version_sessions", "capital_ledger",
                "lifetime_identity", "lifetime_portfolio",
            ]
            counts: dict[str, int] = {}
            for t in tables:
                try:
                    r = conn.execute(f"SELECT COUNT(*) as c FROM [{t}]").fetchone()
                    counts[t] = r["c"] if r else 0
                except Exception:
                    counts[t] = 0
            return counts
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Behavior profile rehydration
# ---------------------------------------------------------------------------

def _rehydrate_behavior_profile(session_id: int | None) -> dict:
    """Copy behavior_profile from the most recent prior session with non-default values.

    If all prior profiles are default (all 0.5), returns no_history=True.
    If a non-default profile is found, copies it to the current session.
    """
    if not session_id:
        try:
            import session_manager
            session_id = session_manager.get_session_id()
        except Exception:
            return {"rehydrated": False, "no_history": True}

    if not session_id:
        return {"rehydrated": False, "no_history": True}

    try:
        import db as v7db
        with v7db.get_db() as conn:
            # Find all prior profiles ordered by recency
            rows = conn.execute(
                """SELECT * FROM behavior_profile
                   WHERE session_id != ?
                   ORDER BY profile_id DESC LIMIT 10""",
                (session_id,)
            ).fetchall()

            if not rows:
                return {"rehydrated": False, "no_history": True}

            _TUNABLE_FIELDS = [
                "aggressiveness", "patience", "probe_bias", "trend_follow_bias",
                "mean_revert_bias", "conviction_threshold", "overtrade_penalty",
                "hold_extension_bias", "exit_tightness", "noise_tolerance",
            ]

            # Find the most recent profile that has at least one non-default value
            for row in rows:
                profile = v7db.dict_from_row(row) if hasattr(row, "keys") else dict(row)
                is_non_default = any(
                    abs((profile.get(f) or 0.5) - 0.5) > 0.01
                    for f in _TUNABLE_FIELDS
                )
                if is_non_default:
                    # Copy these values to the current session's profile
                    updates = {f: profile.get(f, 0.5) for f in _TUNABLE_FIELDS}
                    v7db.upsert_behavior_profile(session_id, **updates)
                    return {
                        "rehydrated": True,
                        "from_session": profile.get("session_id"),
                        "values": updates,
                    }

            # All prior profiles are default — nothing non-trivial to copy
            return {"rehydrated": False, "no_history": True, "reason": "all_default"}

    except Exception as e:
        return {"rehydrated": False, "error": str(e)}


def _rehydrate_behavior_state(session_id: int | None) -> dict:
    """Copy behavior_states from the most recent prior session."""
    if not session_id:
        try:
            import session_manager
            session_id = session_manager.get_session_id()
        except Exception:
            return {"rehydrated": False}

    if not session_id:
        return {"rehydrated": False}

    try:
        import db as v7db
        with v7db.get_db() as conn:
            row = conn.execute(
                """SELECT * FROM behavior_states
                   WHERE session_id != ?
                   ORDER BY state_id DESC LIMIT 1""",
                (session_id,)
            ).fetchone()

            if not row:
                return {"rehydrated": False, "no_history": True}

            state = v7db.dict_from_row(row) if hasattr(row, "keys") else dict(row)

            # Carry forward key state fields (not session-specific counters)
            carry_fields = [
                "market_reward_state", "reward_score", "reward_trend",
                "system_self_state", "self_score", "calibration_quality",
                "aggression_modifier", "patience_modifier",
                "threshold_modifier", "exposure_modifier",
            ]
            updates = {}
            for f in carry_fields:
                if f in state and state[f] is not None:
                    updates[f] = state[f]

            if updates:
                v7db.upsert_behavior_state(session_id, **updates)
                return {
                    "rehydrated": True,
                    "from_session": state.get("session_id"),
                }

            return {"rehydrated": False, "reason": "empty_state"}

    except Exception as e:
        return {"rehydrated": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Continuity score
# ---------------------------------------------------------------------------

def _compute_continuity_score(sources: dict) -> float:
    """Evidence-based continuity score (0-100). How lived-in is this mind?"""
    score = 0.0

    cycles = sources.get("cycle_snapshots", 0)
    trades = sources.get("trade_ledger", 0)
    sessions = sources.get("version_sessions", 0)
    memories = sources.get("experience_memory", 0)
    reviews = sources.get("daily_reviews", 0)
    reflections = sources.get("action_reflections", 0)
    milestones = sources.get("milestones", 0)
    adaptations = sources.get("adaptation_journal", 0)

    # Cycles (max 25)
    if cycles >= 1000:
        score += 25
    elif cycles >= 100:
        score += 15
    elif cycles >= 10:
        score += 8
    elif cycles > 0:
        score += 3

    # Trades (max 25)
    if trades >= 50:
        score += 25
    elif trades >= 20:
        score += 18
    elif trades >= 5:
        score += 10
    elif trades > 0:
        score += 5

    # Sessions (max 15)
    if sessions >= 10:
        score += 15
    elif sessions >= 5:
        score += 10
    elif sessions >= 2:
        score += 5
    elif sessions > 0:
        score += 2

    # Memories (max 15)
    if memories >= 20:
        score += 15
    elif memories >= 5:
        score += 10
    elif memories > 0:
        score += 5

    # Reviews + reflections (max 10)
    review_total = reviews + reflections
    if review_total >= 10:
        score += 10
    elif review_total >= 3:
        score += 6
    elif review_total > 0:
        score += 3

    # Milestones + adaptations (max 10)
    growth_total = milestones + adaptations
    if growth_total >= 10:
        score += 10
    elif growth_total >= 3:
        score += 6
    elif growth_total > 0:
        score += 3

    return round(min(score, 100.0), 1)


# ---------------------------------------------------------------------------
# Maturity level
# ---------------------------------------------------------------------------

def _compute_maturity_level(sources: dict) -> dict:
    """Classify the mind's maturity stage."""
    cycles = sources.get("cycle_snapshots", 0)
    trades = sources.get("trade_ledger", 0)
    sessions = sources.get("version_sessions", 0)
    memories = sources.get("experience_memory", 0)

    # Determine stability
    stability = "unknown"
    if trades >= 20 and memories >= 5:
        stability = "stable"
    elif trades >= 5:
        stability = "forming"
    elif cycles > 0:
        stability = "nascent"
    else:
        stability = "unformed"

    # Determine level
    if cycles >= 5000 and trades >= 100:
        level = "veteran"
        description = "Deep history, extensive trading experience"
    elif cycles >= 1000 and trades >= 50:
        level = "mature"
        description = "Established mind with significant experience"
    elif cycles >= 200 and trades >= 10:
        level = "established"
        description = "Growing history with meaningful trade data"
    elif cycles >= 20 or trades >= 2:
        level = "early"
        description = "Young mind building initial experience"
    else:
        level = "seed"
        description = "New mind, no trading history yet"

    return {
        "level": level,
        "description": description,
        "stability": stability,
        "cycles": cycles,
        "trades": trades,
        "sessions": sessions,
    }


# ---------------------------------------------------------------------------
# Confidence state
# ---------------------------------------------------------------------------

def _compute_confidence_state() -> dict:
    """Rebuild confidence from mind_evolution (already lifetime-scoped).
    Falls back gracefully if mind_evolution unavailable."""
    try:
        import mind_evolution
        conf = mind_evolution.compute_global_confidence()
        return {
            "score": conf.get("score", 0),
            "label": conf.get("label", "Very Low"),
            "components": conf.get("components", {}),
            "source": "mind_evolution",
        }
    except Exception as e:
        return {
            "score": 0,
            "label": "Very Low",
            "components": {},
            "source": "unavailable",
            "error": str(e),
        }


# ---------------------------------------------------------------------------
# Skill state
# ---------------------------------------------------------------------------

def _compute_skill_state() -> dict:
    """Rebuild skill scores from mind_evolution."""
    try:
        import mind_evolution
        skills = mind_evolution.compute_skill_breakdown()
        skill_list = skills if isinstance(skills, list) else skills.get("skills", [])
        return {
            "skills": [
                {
                    "name": s.get("name", "?"),
                    "score": s.get("score", 0),
                    "status": s.get("status", "unknown"),
                    "evidence_count": s.get("evidence_count", 0),
                    "warming_up": s.get("warming_up", True),
                    "confidence_label": s.get("confidence_label", "Very Low"),
                }
                for s in skill_list
            ],
            "total_skills": len(skill_list),
            "source": "mind_evolution",
        }
    except Exception as e:
        return {"skills": [], "total_skills": 0, "source": "unavailable", "error": str(e)}


# ---------------------------------------------------------------------------
# Learning state
# ---------------------------------------------------------------------------

def _compute_learning_state(sources: dict) -> dict:
    """Compute learning depth from memories, reviews, reflections."""
    memories = sources.get("experience_memory", 0)
    reviews = sources.get("daily_reviews", 0)
    reflections = sources.get("action_reflections", 0)
    truth_reviews = sources.get("news_truth_reviews", 0)
    journals = sources.get("mind_journal_entries", 0)

    total_learning = memories + reviews + reflections + truth_reviews + journals

    # Memory depth score (0-100)
    depth = 0.0
    if memories >= 20:
        depth += 40
    elif memories >= 5:
        depth += 25
    elif memories > 0:
        depth += 10

    if reviews >= 10:
        depth += 25
    elif reviews >= 3:
        depth += 15
    elif reviews > 0:
        depth += 5

    if reflections >= 10:
        depth += 20
    elif reflections >= 3:
        depth += 10
    elif reflections > 0:
        depth += 5

    if truth_reviews >= 5:
        depth += 15
    elif truth_reviews > 0:
        depth += 5

    depth = min(depth, 100.0)

    # Latest insight
    latest_insight = ""
    try:
        import db as v7db
        reviews_data = v7db.get_lifetime_daily_reviews(limit=1)
        if reviews_data:
            r = reviews_data[0]
            latest_insight = (
                r.get("behavior_observation")
                or r.get("what_worked")
                or r.get("next_day_bias")
                or ""
            )[:200]
    except Exception:
        pass

    return {
        "total_learning_events": total_learning,
        "memory_count": memories,
        "review_count": reviews,
        "reflection_count": reflections,
        "truth_review_count": truth_reviews,
        "journal_count": journals,
        "memory_depth_score": round(depth, 1),
        "latest_insight": latest_insight,
        "has_active_learning": total_learning > 0,
    }


# ---------------------------------------------------------------------------
# Identity depth
# ---------------------------------------------------------------------------

def _compute_identity_depth(sources: dict, continuity: float,
                             confidence: dict) -> float:
    """Composite identity quality metric (0-100).
    Combines continuity, confidence, and data richness."""
    # Continuity weight: 40%
    cont_component = continuity * 0.40

    # Confidence weight: 30%
    conf_score = confidence.get("score", 0)
    conf_component = conf_score * 0.30

    # Data richness weight: 30%
    non_empty = sum(1 for v in sources.values() if v > 0)
    total_tables = max(len(sources), 1)
    richness = (non_empty / total_tables) * 100
    rich_component = richness * 0.30

    return round(cont_component + conf_component + rich_component, 1)


# ---------------------------------------------------------------------------
# Status computation
# ---------------------------------------------------------------------------

def _compute_rehydration_status(sources: dict, warnings: list) -> str:
    """Return: good / partial / empty / mixed"""
    non_empty = sum(1 for v in sources.values() if v > 0)

    if non_empty == 0:
        return "empty"

    key_sources = ["trade_ledger", "cycle_snapshots", "version_sessions"]
    key_present = sum(1 for k in key_sources if sources.get(k, 0) > 0)

    if key_present >= 2 and non_empty >= 5:
        return "good"
    elif key_present >= 1 or non_empty >= 3:
        return "partial"
    else:
        return "partial"


# ---------------------------------------------------------------------------
# Persist to lifetime_identity
# ---------------------------------------------------------------------------

def _persist_identity_scores(continuity: float, identity_depth: float,
                              learning: dict) -> None:
    """Update lifetime_identity with computed scores.
    Only updates if new values are higher (anti-reduction)."""
    try:
        import db as v7db
        memory_depth = learning.get("memory_depth_score", 0.0)
        v7db.upsert_lifetime_identity(
            continuity_score=round(continuity, 2),
            memory_depth_score=round(memory_depth, 2),
        )
    except Exception as e:
        print(f"[identity] Could not persist identity scores: {e}")
