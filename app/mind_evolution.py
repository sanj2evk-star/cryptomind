"""
mind_evolution.py — CryptoMind v7.3.1 Mind Evolution Layer.

READ-ONLY intelligence module. Does NOT alter trading behavior.
Measures, scores, stores, and exposes how the system's mind is evolving.

v7.3.1 Calibration:
    - Evidence multiplier prevents inflated scores on thin data
    - Global maturity cap prevents high scores before enough trades
    - Per-skill confidence scoring
    - Level gates require both score AND evidence
    - "Why this level" + "What's needed for next" explainers

Core components:
    1. Evolution Score (0-1000) — weighted composite from real evidence
    2. Mind Level — named progression from Seed to Oracle
    3. Skill Breakdown — 9 sub-scores (0-100) with confidence + evidence
    4. Confidence Layer — global + per-skill trust measurement
    5. Growth History — persistent snapshots over time
    6. Recent Learning Feed — what improved/regressed recently
    7. Version/Session Timeline — brain evolution by version
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import db
import session_manager

# ---------------------------------------------------------------------------
# Evidence Multiplier Buckets
# ---------------------------------------------------------------------------

EVIDENCE_MULTIPLIER_BUCKETS = [
    (10,  0.35),
    (25,  0.50),
    (50,  0.65),
    (100, 0.80),
    (200, 0.92),
]

def _evidence_multiplier(sample_count: int) -> float:
    """Map sample count to evidence multiplier (0.35 – 1.0)."""
    for threshold, mult in EVIDENCE_MULTIPLIER_BUCKETS:
        if sample_count <= threshold:
            return mult
    return 1.0


# ---------------------------------------------------------------------------
# Global Maturity Cap (based on lifetime trades)
# ---------------------------------------------------------------------------

MATURITY_CAPS = [
    (20,  45),
    (50,  60),
    (100, 72),
    (200, 82),
    (400, 90),
]

def _maturity_cap(lifetime_trades: int) -> int:
    """Max skill score allowed based on total lifetime trades."""
    for threshold, cap in MATURITY_CAPS:
        if lifetime_trades < threshold:
            return cap
    return 100


# ---------------------------------------------------------------------------
# Mind Level Ladder (v7.3.1 — Seed → Oracle)
# ---------------------------------------------------------------------------

MIND_LEVELS = [
    (0,    "Seed"),
    (100,  "Novice"),
    (200,  "Apprentice"),
    (300,  "Monk"),
    (400,  "Ranger"),
    (500,  "Sniper"),
    (600,  "Operator"),
    (700,  "Strategist"),
    (800,  "Mastermind"),
    (900,  "Oracle"),
]

# Level gates — minimum requirements beyond just score
LEVEL_GATES = {
    "Seed":        {"confidence": 0,  "trades": 0,  "sessions": 0, "outcomes": 0},
    "Novice":      {"confidence": 0,  "trades": 5,  "sessions": 1, "outcomes": 0},
    "Apprentice":  {"confidence": 15, "trades": 15, "sessions": 1, "outcomes": 3},
    "Monk":        {"confidence": 25, "trades": 30, "sessions": 1, "outcomes": 8},
    "Ranger":      {"confidence": 35, "trades": 50, "sessions": 2, "outcomes": 15},
    "Sniper":      {"confidence": 45, "trades": 80, "sessions": 2, "outcomes": 25},
    "Operator":    {"confidence": 55, "trades": 120,"sessions": 3, "outcomes": 40},
    "Strategist":  {"confidence": 65, "trades": 180,"sessions": 3, "outcomes": 60},
    "Mastermind":  {"confidence": 75, "trades": 250,"sessions": 4, "outcomes": 80},
    "Oracle":      {"confidence": 85, "trades": 350,"sessions": 5, "outcomes": 100},
}


def _get_mind_level(score: int, confidence: int = 0, trades: int = 0,
                    sessions: int = 0, outcomes: int = 0) -> dict:
    """Map evolution score to named level, enforcing gate requirements."""
    level_name = "Seed"
    level_floor = 0
    next_name = "Novice"
    next_floor = 100

    for i, (threshold, name) in enumerate(MIND_LEVELS):
        if score >= threshold:
            # Check gate requirements
            gate = LEVEL_GATES.get(name, {})
            if (confidence >= gate.get("confidence", 0) and
                trades >= gate.get("trades", 0) and
                sessions >= gate.get("sessions", 0) and
                outcomes >= gate.get("outcomes", 0)):
                level_name = name
                level_floor = threshold
                if i + 1 < len(MIND_LEVELS):
                    next_floor = MIND_LEVELS[i + 1][0]
                    next_name = MIND_LEVELS[i + 1][1]
                else:
                    next_floor = 1000
                    next_name = "Oracle"

    points_to_next = max(0, next_floor - score)
    level_range = next_floor - level_floor
    progress_pct = round((score - level_floor) / level_range * 100, 1) if level_range > 0 else 100.0

    # What's blocking next level?
    blocked_by = []
    if level_name != "Oracle":
        next_gate = LEVEL_GATES.get(next_name, {})
        if score < next_floor:
            blocked_by.append(f"Need {next_floor - score} more evolution points")
        if confidence < next_gate.get("confidence", 0):
            blocked_by.append(f"Confidence must reach {next_gate['confidence']} (currently {confidence})")
        if trades < next_gate.get("trades", 0):
            blocked_by.append(f"Need {next_gate['trades'] - trades} more trades")
        if sessions < next_gate.get("sessions", 0):
            blocked_by.append(f"Need {next_gate['sessions'] - sessions} completed sessions")
        if outcomes < next_gate.get("outcomes", 0):
            blocked_by.append(f"Need {next_gate['outcomes'] - outcomes} more evaluated outcomes")

    return {
        "level": level_name,
        "score": score,
        "next_level": next_name if level_name != "Oracle" else None,
        "points_to_next": points_to_next if level_name != "Oracle" else 0,
        "progress_pct": progress_pct,
        "blocked_by": blocked_by,
    }


# ---------------------------------------------------------------------------
# Confidence Layer
# ---------------------------------------------------------------------------

CONFIDENCE_LABELS = [
    (25, "Very Low"),
    (45, "Low"),
    (65, "Medium"),
    (85, "High"),
    (101, "Elite"),
]

def _confidence_label(score: int) -> str:
    for threshold, label in CONFIDENCE_LABELS:
        if score < threshold:
            return label
    return "Elite"

CONFIDENCE_COLORS = {
    "Very Low": "#6b7280",  # gray
    "Low": "#d97706",       # muted amber
    "Medium": "#3b82f6",    # blue
    "High": "#22c55e",      # green
    "Elite": "#8b5cf6",     # purple
}


def compute_global_confidence() -> dict:
    """Compute mind confidence score (0-100) from evidence depth."""
    system = db.get_system_state()
    if not system:
        return {"score": 0, "label": "Very Low", "color": "#6b7280", "components": {}}

    sid = session_manager.get_session_id()

    # Components
    sessions = db.get_all_sessions()
    completed_sessions = len([s for s in sessions if not s.get("is_active")])
    total_trades = system.get("total_lifetime_trades", 0)
    outcome_summary = db.get_outcome_summary()
    total_outcomes = outcome_summary.get("total", 0)
    completed_outcomes = outcome_summary.get("completed", 0)
    memory_count = db.get_memory_count()
    regime_profiles = db.get_regime_profiles(session_id=sid) if sid else []
    regime_recs = len([p for p in regime_profiles if p.get("recommended_action") != "neutral"])
    adapt_journal = db.get_adaptation_journal(session_id=sid, limit=500) if sid else []

    # Session age in hours
    session_hours = 0
    if sid:
        age = session_manager.get_system_age()
        session_hours = age.get("system_age_hours", 0)

    # Weighted components (each 0-1, weighted to sum to ~100)
    c_sessions = min(1.0, completed_sessions / 5) * 12       # 5 sessions = full credit
    c_trades = min(1.0, total_trades / 200) * 20              # 200 trades = full
    c_outcomes = min(1.0, completed_outcomes / 50) * 18       # 50 completed = full
    c_coverage = (completed_outcomes / max(total_outcomes, 1)) * 10 if total_outcomes > 0 else 0
    c_adapt = min(1.0, len(adapt_journal) / 50) * 12         # 50 journal entries = full
    c_memory = min(1.0, memory_count / 30) * 10              # 30 memories = full
    c_regime = min(1.0, regime_recs / 8) * 10                # 8 recommendations = full
    c_hours = min(1.0, session_hours / 168) * 8              # 1 week = full

    total = round(c_sessions + c_trades + c_outcomes + c_coverage +
                  c_adapt + c_memory + c_regime + c_hours)
    total = max(0, min(100, total))

    label = _confidence_label(total)

    return {
        "score": total,
        "label": label,
        "color": CONFIDENCE_COLORS.get(label, "#6b7280"),
        "components": {
            "completed_sessions": completed_sessions,
            "total_trades": total_trades,
            "evaluated_outcomes": completed_outcomes,
            "outcome_coverage_pct": round(completed_outcomes / max(total_outcomes, 1) * 100, 1) if total_outcomes > 0 else 0,
            "adaptation_depth": len(adapt_journal),
            "memory_count": memory_count,
            "regime_recommendations": regime_recs,
            "session_age_hours": round(session_hours, 1),
        },
    }


def _compute_evidence_strength(confidence_score: int) -> dict:
    """Overall evidence strength as a percentage."""
    return {
        "pct": confidence_score,
        "label": f"Evidence Strength: {confidence_score}%",
    }


# ---------------------------------------------------------------------------
# Evolution Score Computation (0-1000)
# ---------------------------------------------------------------------------

# Weight allocation — totals to 1000
SCORE_WEIGHTS = {
    "system_age":           80,   # longevity / cycles survived
    "sessions_completed":   40,   # completed sessions
    "trades_executed":      60,   # total trades
    "outcome_coverage":     80,   # delayed outcome evaluations done
    "adaptation_quality":   100,  # adaptations allowed vs blocked ratio
    "discipline_quality":   130,  # blocked bad trades, cooldown respect
    "drawdown_control":     80,   # max drawdown behavior
    "regime_accuracy":      100,  # regime intelligence accuracy
    "missed_opp_learning":  60,   # missed opportunity review quality
    "session_consistency":  80,   # stability across sessions
    "recovery_ability":     60,   # recovery after poor periods
    "win_rate_quality":     50,   # win rate (capped contribution)
    "memory_depth":         80,   # experience memory richness
}


def compute_evolution_score() -> dict:
    """Compute the full evolution score from real system evidence.

    Returns dict with total score, breakdown, and mind level.
    """
    system = db.get_system_state()
    if not system:
        return _empty_score()

    sid = session_manager.get_session_id()
    breakdown = {}

    # 1. System Age
    total_cycles = system.get("total_lifetime_cycles", 0)
    age_pct = min(1.0, total_cycles / 2000)
    breakdown["system_age"] = {
        "raw": total_cycles,
        "pct": round(age_pct * 100, 1),
        "points": round(age_pct * SCORE_WEIGHTS["system_age"]),
        "label": "System Age",
        "detail": f"{total_cycles} lifetime cycles",
    }

    # 2. Sessions Completed
    sessions = db.get_all_sessions()
    closed_sessions = [s for s in sessions if not s.get("is_active")]
    sess_pct = min(1.0, len(closed_sessions) / 8)
    breakdown["sessions_completed"] = {
        "raw": len(closed_sessions),
        "pct": round(sess_pct * 100, 1),
        "points": round(sess_pct * SCORE_WEIGHTS["sessions_completed"]),
        "label": "Sessions Completed",
        "detail": f"{len(closed_sessions)} sessions completed, {len(sessions)} total",
    }

    # 3. Trades Executed
    total_trades = system.get("total_lifetime_trades", 0)
    trade_pct = min(1.0, total_trades / 200)
    breakdown["trades_executed"] = {
        "raw": total_trades,
        "pct": round(trade_pct * 100, 1),
        "points": round(trade_pct * SCORE_WEIGHTS["trades_executed"]),
        "label": "Trades Executed",
        "detail": f"{total_trades} lifetime trades",
    }

    # 4. Outcome Coverage
    outcome_summary = db.get_outcome_summary()
    total_outcomes = outcome_summary.get("total", 0)
    completed_outcomes = outcome_summary.get("completed", 0)
    coverage = completed_outcomes / max(total_outcomes, 1) if total_outcomes > 0 else 0
    volume_factor = min(1.0, total_outcomes / 30)
    outcome_pct = coverage * volume_factor
    breakdown["outcome_coverage"] = {
        "raw": completed_outcomes,
        "pct": round(outcome_pct * 100, 1),
        "points": round(outcome_pct * SCORE_WEIGHTS["outcome_coverage"]),
        "label": "Outcome Evaluation",
        "detail": f"{completed_outcomes}/{total_outcomes} outcomes evaluated",
    }

    # 5. Adaptation Quality
    adapt_quality = _compute_adaptation_quality(sid)
    breakdown["adaptation_quality"] = {
        "raw": adapt_quality["ratio"],
        "pct": round(adapt_quality["pct"] * 100, 1),
        "points": round(adapt_quality["pct"] * SCORE_WEIGHTS["adaptation_quality"]),
        "label": "Adaptation Quality",
        "detail": adapt_quality["detail"],
    }

    # 6. Discipline Quality
    discipline = _compute_discipline_score(sid)
    breakdown["discipline_quality"] = {
        "raw": discipline["score"],
        "pct": round(discipline["pct"] * 100, 1),
        "points": round(discipline["pct"] * SCORE_WEIGHTS["discipline_quality"]),
        "label": "Discipline",
        "detail": discipline["detail"],
    }

    # 7. Drawdown Control
    drawdown = _compute_drawdown_score(sid)
    breakdown["drawdown_control"] = {
        "raw": drawdown["max_dd"],
        "pct": round(drawdown["pct"] * 100, 1),
        "points": round(drawdown["pct"] * SCORE_WEIGHTS["drawdown_control"]),
        "label": "Drawdown Control",
        "detail": drawdown["detail"],
    }

    # 8. Regime Accuracy
    regime = _compute_regime_score(sid)
    breakdown["regime_accuracy"] = {
        "raw": regime["accuracy"],
        "pct": round(regime["pct"] * 100, 1),
        "points": round(regime["pct"] * SCORE_WEIGHTS["regime_accuracy"]),
        "label": "Regime Intelligence",
        "detail": regime["detail"],
    }

    # 9. Missed Opportunity Learning
    missed = _compute_missed_opp_score()
    breakdown["missed_opp_learning"] = {
        "raw": missed["reviewed"],
        "pct": round(missed["pct"] * 100, 1),
        "points": round(missed["pct"] * SCORE_WEIGHTS["missed_opp_learning"]),
        "label": "Opportunity Sensing",
        "detail": missed["detail"],
    }

    # 10. Session Consistency
    consistency = _compute_consistency_score(sessions)
    breakdown["session_consistency"] = {
        "raw": consistency["score"],
        "pct": round(consistency["pct"] * 100, 1),
        "points": round(consistency["pct"] * SCORE_WEIGHTS["session_consistency"]),
        "label": "Consistency",
        "detail": consistency["detail"],
    }

    # 11. Recovery Ability
    recovery = _compute_recovery_score(sid)
    breakdown["recovery_ability"] = {
        "raw": recovery["score"],
        "pct": round(recovery["pct"] * 100, 1),
        "points": round(recovery["pct"] * SCORE_WEIGHTS["recovery_ability"]),
        "label": "Recovery",
        "detail": recovery["detail"],
    }

    # 12. Win Rate Quality (capped)
    trade_summary = db.get_trade_summary()
    win_rate = trade_summary.get("win_rate", 0)
    wr_pct = min(1.0, max(0, (win_rate - 30) / 40))
    breakdown["win_rate_quality"] = {
        "raw": win_rate,
        "pct": round(wr_pct * 100, 1),
        "points": round(wr_pct * SCORE_WEIGHTS["win_rate_quality"]),
        "label": "Win Rate",
        "detail": f"{win_rate:.1f}% win rate (capped contribution)",
    }

    # 13. Memory Depth
    memory_count = db.get_memory_count()
    mem_pct = min(1.0, memory_count / 50)
    breakdown["memory_depth"] = {
        "raw": memory_count,
        "pct": round(mem_pct * 100, 1),
        "points": round(mem_pct * SCORE_WEIGHTS["memory_depth"]),
        "label": "Memory Depth",
        "detail": f"{memory_count} active memories",
    }

    # Total
    total_score = sum(v["points"] for v in breakdown.values())
    total_score = max(0, min(1000, total_score))

    # Confidence (needed for level gating)
    confidence = compute_global_confidence()

    mind_level = _get_mind_level(
        total_score,
        confidence=confidence["score"],
        trades=total_trades,
        sessions=len(closed_sessions),
        outcomes=completed_outcomes,
    )

    return {
        "evolution_score": total_score,
        "mind_level": mind_level,
        "breakdown": breakdown,
        "max_possible": 1000,
        "confidence": confidence,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


def _empty_score() -> dict:
    """Return empty score when system has no data."""
    return {
        "evolution_score": 0,
        "mind_level": _get_mind_level(0),
        "breakdown": {},
        "max_possible": 1000,
        "warming_up": True,
        "confidence": {"score": 0, "label": "Very Low", "color": "#6b7280", "components": {}},
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Score Component Helpers
# ---------------------------------------------------------------------------

def _compute_adaptation_quality(session_id: int | None) -> dict:
    journal = db.get_adaptation_journal(session_id=session_id, limit=200)
    if len(journal) < 5:
        return {"ratio": 0, "pct": 0.3, "detail": "Warming up (< 5 adaptation attempts)"}

    allowed = sum(1 for j in journal if j.get("allowed_or_blocked") == "allowed")
    blocked = sum(1 for j in journal if j.get("allowed_or_blocked") == "blocked")
    total = allowed + blocked
    if total == 0:
        return {"ratio": 0, "pct": 0.3, "detail": "No adaptation data"}

    ratio = allowed / total
    if 0.3 <= ratio <= 0.7:
        pct = 0.8 + (0.2 * min(1.0, total / 50))
    elif ratio > 0.7:
        pct = 0.5
    else:
        pct = 0.4

    return {
        "ratio": round(ratio, 3),
        "pct": min(1.0, pct),
        "detail": f"{allowed}/{total} adaptations allowed ({ratio:.0%})",
    }


def _compute_discipline_score(session_id: int | None) -> dict:
    missed_summary = db.get_missed_opportunity_summary()
    total_blocked = missed_summary.get("total", 0)
    confirmed_missed = missed_summary.get("confirmed_missed", 0)

    if total_blocked == 0:
        return {"score": 0, "pct": 0.3, "detail": "Warming up (no blocked trade data)"}

    false_positive_rate = confirmed_missed / total_blocked if total_blocked > 0 else 0
    discipline_pct = max(0, 1.0 - false_positive_rate)
    volume = min(1.0, total_blocked / 20)
    final_pct = discipline_pct * 0.7 + volume * 0.3

    return {
        "score": round(discipline_pct, 3),
        "pct": min(1.0, final_pct),
        "detail": f"{total_blocked} blocked, {confirmed_missed} were actual misses ({false_positive_rate:.0%} false positive)",
    }


def _compute_drawdown_score(session_id: int | None) -> dict:
    if not session_id:
        return {"max_dd": 0, "pct": 0.5, "detail": "No session data"}

    snapshots = db.get_recent_snapshots(session_id, limit=200)
    if len(snapshots) < 10:
        return {"max_dd": 0, "pct": 0.5, "detail": "Warming up (< 10 snapshots)"}

    equities = [s.get("equity", 100) for s in reversed(snapshots) if s.get("equity")]
    if not equities:
        return {"max_dd": 0, "pct": 0.5, "detail": "No equity data"}

    peak = equities[0]
    max_dd = 0
    for eq in equities:
        peak = max(peak, eq)
        dd = (peak - eq) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)

    if max_dd <= 0.05:
        pct = 1.0
    elif max_dd <= 0.10:
        pct = 0.8
    elif max_dd <= 0.20:
        pct = 0.5
    else:
        pct = max(0.1, 1.0 - max_dd)

    return {
        "max_dd": round(max_dd * 100, 2),
        "pct": pct,
        "detail": f"Max drawdown: {max_dd*100:.1f}%",
    }


def _compute_regime_score(session_id: int | None) -> dict:
    if not session_id:
        return {"accuracy": 0, "pct": 0.3, "detail": "No session data"}

    profiles = db.get_regime_profiles(session_id=session_id)
    if len(profiles) < 3:
        return {"accuracy": 0, "pct": 0.3, "detail": "Warming up (< 3 regime profiles)"}

    with_recs = [p for p in profiles if p.get("recommended_action") != "neutral"]
    total_trades_in_recs = sum(p.get("total_trades", 0) for p in with_recs)

    preferred = [p for p in with_recs if p.get("recommended_action") == "prefer"]
    avoided = [p for p in with_recs if p.get("recommended_action") == "avoid"]

    pref_wr = sum(p.get("win_rate", 0) for p in preferred) / len(preferred) if preferred else 0
    avoid_wr = sum(p.get("win_rate", 0) for p in avoided) / len(avoided) if avoided else 100

    if preferred and avoided:
        gap = pref_wr - avoid_wr
        accuracy = min(1.0, max(0, gap / 40))
    elif preferred:
        accuracy = min(1.0, pref_wr / 70)
    else:
        accuracy = 0.3

    volume = min(1.0, total_trades_in_recs / 20)
    pct = accuracy * 0.7 + volume * 0.3

    return {
        "accuracy": round(accuracy, 3),
        "pct": min(1.0, pct),
        "detail": f"{len(with_recs)} regime recommendations, {len(profiles)} profiles tracked",
    }


def _compute_missed_opp_score() -> dict:
    summary = db.get_missed_opportunity_summary()
    total = summary.get("total", 0)
    if total < 3:
        return {"reviewed": 0, "pct": 0.3, "detail": "Warming up (< 3 missed opps recorded)"}

    major = summary.get("major", 0) or 0
    moderate = summary.get("moderate", 0) or 0
    confirmed = summary.get("confirmed_missed", 0)
    minor = summary.get("minor", 0) or 0

    severity_score = 1.0
    if major > 3:
        severity_score -= 0.3
    if moderate > 5:
        severity_score -= 0.2

    volume = min(1.0, total / 15)
    pct = max(0.1, severity_score * 0.6 + volume * 0.4)

    return {
        "reviewed": total,
        "pct": min(1.0, pct),
        "detail": f"{total} tracked, {confirmed} confirmed ({minor}m/{moderate}M/{major}X severity)",
    }


def _compute_consistency_score(sessions: list[dict]) -> dict:
    completed = [s for s in sessions if not s.get("is_active") and s.get("total_trades", 0) > 0]
    if len(completed) < 2:
        return {"score": 0, "pct": 0.4, "detail": "Need 2+ completed sessions"}

    pnls = [s.get("realized_pnl", 0) for s in completed]
    positive = sum(1 for p in pnls if p > 0)
    consistency = positive / len(pnls) if pnls else 0.5

    cycles = [s.get("total_cycles", 0) for s in completed]
    avg_cycles = sum(cycles) / len(cycles) if cycles else 0
    cycle_credit = min(1.0, avg_cycles / 500)

    pct = consistency * 0.6 + cycle_credit * 0.4

    return {
        "score": round(consistency, 3),
        "pct": min(1.0, pct),
        "detail": f"{positive}/{len(completed)} sessions profitable, avg {avg_cycles:.0f} cycles/session",
    }


def _compute_recovery_score(session_id: int | None) -> dict:
    if not session_id:
        return {"score": 0, "pct": 0.5, "detail": "No session data"}

    trades, _ = db.get_trades(session_id=session_id, limit=100)
    sells = [t for t in trades if t.get("action") == "SELL"]
    if len(sells) < 5:
        return {"score": 0, "pct": 0.4, "detail": "Warming up (< 5 sells)"}

    recoveries = 0
    loss_streaks = 0
    in_loss = False

    for s in reversed(sells):
        pnl = s.get("pnl", 0)
        if pnl < 0:
            if not in_loss:
                loss_streaks += 1
            in_loss = True
        elif pnl > 0 and in_loss:
            recoveries += 1
            in_loss = False
        else:
            in_loss = False

    recovery_rate = recoveries / max(loss_streaks, 1) if loss_streaks > 0 else 1.0
    pct = min(1.0, recovery_rate)

    return {
        "score": round(recovery_rate, 3),
        "pct": pct,
        "detail": f"{recoveries} recoveries from {loss_streaks} losing streaks",
    }


# ---------------------------------------------------------------------------
# Skill Breakdown (9 skills, 0-100 each) — v7.3.1 calibrated
# ---------------------------------------------------------------------------

# Skill → evidence source mapping (used for evidence multiplier + confidence)
SKILL_EVIDENCE_SOURCES = {
    "Discipline":          "blocked_trades",
    "Risk Control":        "snapshots",
    "Timing":              "outcomes",
    "Adaptation":          "adaptation_journal",
    "Regime Reading":      "regime_profiles",
    "Opportunity Sensing": "missed_opportunities",
    "Consistency":         "sessions",
    "Self-Correction":     "sells",
    "Patience":            "composite",
}


def compute_skill_breakdown() -> list[dict]:
    """Compute 9 individual skill scores with evidence multiplier + maturity cap."""
    score_data = compute_evolution_score()
    breakdown = score_data.get("breakdown", {})
    confidence_data = score_data.get("confidence", {})
    components = confidence_data.get("components", {})

    # Global maturity cap
    total_trades = components.get("total_trades", 0)
    mat_cap = _maturity_cap(total_trades)

    # Evidence counts per source
    evidence_counts = _gather_evidence_counts()

    skills = []

    def _make_skill(name: str, raw_pct: float, description: str,
                    detail: str, evidence_source: str):
        """Build a calibrated skill entry."""
        ev_count = evidence_counts.get(evidence_source, 0)
        ev_mult = _evidence_multiplier(ev_count)
        raw_score = round(raw_pct * 100)

        # Apply evidence multiplier
        calibrated = round(raw_score * ev_mult)

        # Apply maturity cap
        capped = min(calibrated, mat_cap)

        # Warming up check
        is_warming = ev_count < 10
        if is_warming:
            capped = min(capped, 38)  # hard cap for warming up

        status = _skill_status(capped)
        if is_warming:
            status = "warming_up"

        # Per-skill confidence
        skill_conf = min(100, round(ev_mult * 100))
        skill_conf_label = _confidence_label(skill_conf)

        return {
            "name": name,
            "score": capped,
            "raw_score": raw_score,
            "description": description,
            "status": status,
            "detail": detail,
            "evidence_count": ev_count,
            "evidence_multiplier": ev_mult,
            "maturity_cap": mat_cap,
            "warming_up": is_warming,
            "confidence": skill_conf,
            "confidence_label": skill_conf_label,
            "confidence_color": CONFIDENCE_COLORS.get(skill_conf_label, "#6b7280"),
        }

    # 1. Discipline
    disc = breakdown.get("discipline_quality", {})
    skills.append(_make_skill(
        "Discipline", disc.get("pct", 30) / 100,
        "Blocked bad trades, low overtrading, cooldown respect",
        disc.get("detail", ""), "blocked_trades"))

    # 2. Risk Control
    dd = breakdown.get("drawdown_control", {})
    skills.append(_make_skill(
        "Risk Control", dd.get("pct", 50) / 100,
        "Drawdown behavior, exposure control, good exits",
        dd.get("detail", ""), "snapshots"))

    # 3. Timing
    outcome = breakdown.get("outcome_coverage", {})
    skills.append(_make_skill(
        "Timing", outcome.get("pct", 30) / 100,
        "Entry/exit quality from delayed outcome evaluations",
        outcome.get("detail", ""), "outcomes"))

    # 4. Adaptation
    adapt = breakdown.get("adaptation_quality", {})
    skills.append(_make_skill(
        "Adaptation", adapt.get("pct", 30) / 100,
        "Whether adaptations improved later outcomes",
        adapt.get("detail", ""), "adaptation_journal"))

    # 5. Regime Reading
    regime = breakdown.get("regime_accuracy", {})
    skills.append(_make_skill(
        "Regime Reading", regime.get("pct", 30) / 100,
        "Accuracy of regime + strategy fit predictions",
        regime.get("detail", ""), "regime_profiles"))

    # 6. Opportunity Sensing
    missed = breakdown.get("missed_opp_learning", {})
    skills.append(_make_skill(
        "Opportunity Sensing", missed.get("pct", 30) / 100,
        "Missed opportunity review and learning quality",
        missed.get("detail", ""), "missed_opportunities"))

    # 7. Consistency
    cons = breakdown.get("session_consistency", {})
    skills.append(_make_skill(
        "Consistency", cons.get("pct", 40) / 100,
        "Stability of performance across sessions",
        cons.get("detail", ""), "sessions"))

    # 8. Self-Correction
    recovery = breakdown.get("recovery_ability", {})
    skills.append(_make_skill(
        "Self-Correction", recovery.get("pct", 40) / 100,
        "How often mistakes get corrected in later trades",
        recovery.get("detail", ""), "sells"))

    # 9. Patience (composite)
    patience_pct = (disc.get("pct", 30) / 100 * 0.5 +
                    adapt.get("pct", 30) / 100 * 0.3 +
                    cons.get("pct", 40) / 100 * 0.2)
    # For patience, evidence = min of its component sources
    patience_ev = min(
        evidence_counts.get("blocked_trades", 0),
        evidence_counts.get("adaptation_journal", 0),
        evidence_counts.get("sessions", 0) * 20,  # scale sessions up
    )
    ev_mult_p = _evidence_multiplier(patience_ev)
    raw_patience = round(patience_pct * 100)
    calibrated_p = min(round(raw_patience * ev_mult_p), mat_cap)
    is_warming_p = patience_ev < 10
    if is_warming_p:
        calibrated_p = min(calibrated_p, 38)
    status_p = "warming_up" if is_warming_p else _skill_status(calibrated_p)
    pc = min(100, round(ev_mult_p * 100))
    pcl = _confidence_label(pc)

    skills.append({
        "name": "Patience",
        "score": calibrated_p,
        "raw_score": raw_patience,
        "description": "Not forcing trades in low-quality conditions",
        "status": status_p,
        "detail": "Composite of discipline, adaptation quality, and consistency",
        "evidence_count": patience_ev,
        "evidence_multiplier": ev_mult_p,
        "maturity_cap": mat_cap,
        "warming_up": is_warming_p,
        "confidence": pc,
        "confidence_label": pcl,
        "confidence_color": CONFIDENCE_COLORS.get(pcl, "#6b7280"),
    })

    return skills


def _gather_evidence_counts() -> dict:
    """Gather evidence counts for each skill source."""
    sid = session_manager.get_session_id()
    counts = {}

    # Blocked trades
    missed_summary = db.get_missed_opportunity_summary()
    counts["blocked_trades"] = missed_summary.get("total", 0)

    # Snapshots
    if sid:
        snaps = db.get_recent_snapshots(sid, limit=500)
        counts["snapshots"] = len(snaps)
    else:
        counts["snapshots"] = 0

    # Outcomes
    outcome_summary = db.get_outcome_summary()
    counts["outcomes"] = outcome_summary.get("total", 0)

    # Adaptation journal
    journal = db.get_adaptation_journal(session_id=sid, limit=500) if sid else []
    counts["adaptation_journal"] = len(journal)

    # Regime profiles
    profiles = db.get_regime_profiles(session_id=sid) if sid else []
    counts["regime_profiles"] = len(profiles)

    # Missed opportunities
    counts["missed_opportunities"] = missed_summary.get("total", 0)

    # Sessions
    sessions = db.get_all_sessions()
    counts["sessions"] = len([s for s in sessions if not s.get("is_active")])

    # Sells
    if sid:
        trades, _ = db.get_trades(session_id=sid, limit=500)
        counts["sells"] = len([t for t in trades if t.get("action") == "SELL"])
    else:
        counts["sells"] = 0

    return counts


def _skill_status(score: int) -> str:
    """Determine skill status label from calibrated score."""
    if score >= 75:
        return "strong"
    elif score >= 55:
        return "developing"
    elif score >= 35:
        return "learning"
    elif score >= 18:
        return "weak"
    else:
        return "warming_up"


# ---------------------------------------------------------------------------
# "Why This Level" + "What's Needed for Next Level"
# ---------------------------------------------------------------------------

def compute_why_this_level() -> dict:
    """Generate explanations for current level and what's needed next."""
    score_data = compute_evolution_score()
    mind_level = score_data.get("mind_level", {})
    confidence = score_data.get("confidence", {})
    skills = compute_skill_breakdown()

    # Why this level
    reasons = []
    strong_skills = [s for s in skills if s["status"] == "strong"]
    weak_skills = [s for s in skills if s["status"] in ("weak", "warming_up")]
    developing_skills = [s for s in skills if s["status"] == "developing"]

    if strong_skills:
        names = ", ".join(s["name"] for s in strong_skills[:3])
        reasons.append(f"Strong {names}")
    if developing_skills:
        names = ", ".join(s["name"] for s in developing_skills[:3])
        reasons.append(f"Developing {names}")
    if weak_skills:
        names = ", ".join(s["name"] for s in weak_skills[:3])
        reasons.append(f"Weak/warming: {names}")

    conf_label = confidence.get("label", "Very Low")
    reasons.append(f"Confidence: {conf_label}")

    warming_count = sum(1 for s in skills if s.get("warming_up"))
    if warming_count > 3:
        reasons.append(f"{warming_count} skills still warming up")

    components = confidence.get("components", {})
    if components.get("total_trades", 0) < 20:
        reasons.append("Limited trade evidence")
    if components.get("evaluated_outcomes", 0) < 10:
        reasons.append("Not enough evaluated outcomes yet")

    return {
        "current_level": mind_level.get("level", "Seed"),
        "evolution_score": score_data.get("evolution_score", 0),
        "why_this_level": reasons,
        "what_needed_for_next": mind_level.get("blocked_by", []),
        "next_level": mind_level.get("next_level"),
    }


# ---------------------------------------------------------------------------
# Recent Learning Feed
# ---------------------------------------------------------------------------

def get_recent_learning() -> list[dict]:
    """Generate a structured feed of recent improvements and regressions."""
    sid = session_manager.get_session_id()
    feed = []

    if not sid:
        return [{"type": "info", "message": "No active session", "area": "system"}]

    # 1. Check recent memories
    memories = db.get_active_memories(session_id=sid, limit=5)
    for mem in memories[:3]:
        lesson = mem.get("lesson_text", "")
        if lesson:
            feed.append({
                "type": "lesson_absorbed",
                "message": lesson,
                "area": mem.get("strategy", "general"),
                "confidence": round(mem.get("confidence_weight", 0.5), 2),
                "times_seen": mem.get("times_observed", 1),
                "timestamp": mem.get("timestamp", ""),
            })

    # 2. Check outcome evaluations
    outcome_summary = db.get_outcome_summary()
    correct = outcome_summary.get("correct", 0)
    wrong = outcome_summary.get("wrong", 0)
    total_eval = correct + wrong
    if total_eval > 0:
        accuracy = correct / total_eval
        if accuracy >= 0.6:
            feed.append({
                "type": "improvement",
                "message": f"Entry timing accuracy at {accuracy:.0%} ({correct}/{total_eval} correct entries)",
                "area": "timing",
            })
        elif accuracy < 0.4:
            feed.append({
                "type": "regression",
                "message": f"Entry timing accuracy low at {accuracy:.0%} — entries often mispriced",
                "area": "timing",
            })

    # 3. Check missed opportunities
    missed = db.get_missed_opportunity_summary()
    major_misses = missed.get("major", 0) or 0
    if major_misses > 0:
        feed.append({
            "type": "weakness",
            "message": f"{major_misses} major missed opportunities — system was too cautious at key moments",
            "area": "opportunity_sensing",
        })

    # 4. Check behavior state
    bstate = db.get_behavior_state(sid)
    if bstate:
        self_state = bstate.get("system_self_state", "learning")
        market_reward = bstate.get("market_reward_state", "neutral")
        if self_state == "in_sync":
            feed.append({
                "type": "strength",
                "message": "System is in sync — decisions align well with market outcomes",
                "area": "self_awareness",
            })
        elif self_state == "out_of_sync":
            feed.append({
                "type": "weakness",
                "message": "System is out of sync — readings don't match outcomes, adapting cautiously",
                "area": "self_awareness",
            })
        if market_reward == "punishing_aggression":
            feed.append({
                "type": "regression",
                "message": "Market is punishing aggressive entries — patience rewarded",
                "area": "market_reading",
            })
        elif market_reward == "rewarding_aggression":
            feed.append({
                "type": "improvement",
                "message": "Market is rewarding aggressive entries — confidence is paying off",
                "area": "market_reading",
            })

    # 5. Check regime intelligence
    profiles = db.get_regime_profiles(session_id=sid)
    strong_regimes = [p for p in profiles if p.get("win_rate", 0) >= 60 and p.get("total_trades", 0) >= 5]
    weak_regimes = [p for p in profiles if p.get("win_rate", 0) < 35 and p.get("total_trades", 0) >= 5]

    for sr in strong_regimes[:2]:
        feed.append({
            "type": "strength",
            "message": f"Strong in {sr['regime']} with {sr['strategy']} ({sr['win_rate']:.0f}% WR, {sr['total_trades']} trades)",
            "area": "regime_reading",
        })

    for wr in weak_regimes[:2]:
        feed.append({
            "type": "weakness",
            "message": f"Struggling in {wr['regime']} with {wr['strategy']} ({wr['win_rate']:.0f}% WR)",
            "area": "regime_reading",
        })

    # 6. Check daily reviews
    latest_review = db.get_latest_review()
    if latest_review:
        if latest_review.get("what_worked"):
            feed.append({
                "type": "improvement",
                "message": f"Recent review: {latest_review['what_worked'][:120]}",
                "area": "daily_review",
            })
        if latest_review.get("what_failed"):
            feed.append({
                "type": "regression",
                "message": f"Recent review: {latest_review['what_failed'][:120]}",
                "area": "daily_review",
            })

    if not feed:
        feed.append({
            "type": "info",
            "message": "System is warming up — collecting data to generate insights",
            "area": "system",
        })

    return feed


# ---------------------------------------------------------------------------
# Version/Session Timeline
# ---------------------------------------------------------------------------

VERSION_MILESTONES = {
    "pre-v7": "Legacy CSV-based trades (archived)",
    "6.0.0": "Trade intelligence UI + night-mode P&L",
    "7.0.0": "Memory born — SQLite persistence, sessions, experience memory",
    "7.1.0": "Self-review engine — delayed outcomes, regime intelligence, behavior states",
    "7.2.0": "Discipline guard — central adaptation safety, audit trail",
    "7.3.0": "Mind evolution layer — evolution score, skill tracking, growth history",
    "7.3.1": "Mind calibration — confidence layer, evidence gating, honest scoring",
}


def get_session_timeline() -> list[dict]:
    """Build version/session timeline with key metrics."""
    sessions = db.get_all_sessions()
    timeline = []

    for s in sessions:
        version = s.get("app_version", "?")
        entry = {
            "session_id": s.get("session_id"),
            "version": version,
            "started_at": s.get("started_at", ""),
            "closed_at": s.get("closed_at"),
            "is_active": bool(s.get("is_active")),
            "total_cycles": s.get("total_cycles", 0),
            "total_trades": s.get("total_trades", 0),
            "realized_pnl": round(s.get("realized_pnl", 0), 6),
            "version_description": VERSION_MILESTONES.get(version, ""),
            "buys": s.get("total_buys", 0),
            "sells": s.get("total_sells", 0),
        }
        timeline.append(entry)

    return timeline


# ---------------------------------------------------------------------------
# Snapshot — called periodically to persist evolution history
# ---------------------------------------------------------------------------

def take_evolution_snapshot(session_id: int, cycle_number: int) -> None:
    """Periodic snapshot for history tracking. Called every 100 cycles."""
    try:
        score_data = compute_evolution_score()
        skills = compute_skill_breakdown()

        db.insert_evolution_snapshot(
            session_id=session_id,
            cycle_number=cycle_number,
            evolution_score=score_data["evolution_score"],
            mind_level=score_data["mind_level"]["level"],
            discipline_score=_find_skill(skills, "Discipline"),
            risk_control_score=_find_skill(skills, "Risk Control"),
            timing_score=_find_skill(skills, "Timing"),
            adaptation_score=_find_skill(skills, "Adaptation"),
            regime_reading_score=_find_skill(skills, "Regime Reading"),
            opportunity_score=_find_skill(skills, "Opportunity Sensing"),
            consistency_score=_find_skill(skills, "Consistency"),
            self_correction_score=_find_skill(skills, "Self-Correction"),
            patience_score=_find_skill(skills, "Patience"),
        )
    except Exception as e:
        print(f"[mind_evolution] Snapshot error: {e}")


def _find_skill(skills: list[dict], name: str) -> int:
    for s in skills:
        if s["name"] == name:
            return s["score"]
    return 0


# ---------------------------------------------------------------------------
# Growth History
# ---------------------------------------------------------------------------

def get_evolution_history(limit: int = 100) -> list[dict]:
    sid = session_manager.get_session_id()
    return db.get_evolution_history(session_id=sid, limit=limit)


# ---------------------------------------------------------------------------
# Full Mind State for API
# ---------------------------------------------------------------------------

def get_full_mind_state() -> dict:
    """Complete mind state for the /v7/mind endpoint."""
    score_data = compute_evolution_score()
    skills = compute_skill_breakdown()
    system_age = session_manager.get_system_age()
    confidence = score_data.get("confidence", {})
    why = compute_why_this_level()
    evidence = _compute_evidence_strength(confidence.get("score", 0))

    return {
        "evolution_score": score_data["evolution_score"],
        "max_possible": 1000,
        "mind_level": score_data["mind_level"],
        "confidence": confidence,
        "evidence_strength": evidence,
        "skills": skills,
        "why_this_level": why.get("why_this_level", []),
        "what_needed_for_next": why.get("what_needed_for_next", []),
        "system_age": {
            "total_cycles": system_age.get("system_age_cycles", 0),
            "total_hours": system_age.get("system_age_hours", 0),
            "total_trades": system_age.get("total_lifetime_trades", 0),
            "current_session_hours": system_age.get("current_session_hours", 0),
            "version": system_age.get("current_session_version", "?"),
        },
        "warming_up": score_data.get("warming_up", False),
        "computed_at": score_data["computed_at"],
    }
