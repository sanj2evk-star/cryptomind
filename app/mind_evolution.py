"""
mind_evolution.py — CryptoMind v7.3 Mind Evolution Layer.

READ-ONLY intelligence module. Does NOT alter trading behavior.
Measures, scores, stores, and exposes how the system's mind is evolving.

Core components:
    1. Evolution Score (0-1000) — weighted composite from real evidence
    2. Mind Level — named progression from Rookie to Godmode
    3. Skill Breakdown — 9 sub-scores (0-100) from real system behavior
    4. Growth History — persistent snapshots over time
    5. Recent Learning Feed — what improved/regressed recently
    6. Version/Session Timeline — brain evolution by version
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import db
import session_manager

# ---------------------------------------------------------------------------
# Mind Level Ladder
# ---------------------------------------------------------------------------

MIND_LEVELS = [
    (0,    "Rookie"),
    (50,   "Beginner"),
    (120,  "Apprentice"),
    (220,  "Operator"),
    (350,  "Pro"),
    (500,  "Elite"),
    (650,  "World Class"),
    (780,  "Assassin"),
    (880,  "Sage"),
    (950,  "Godmode"),
]

def _get_mind_level(score: int) -> dict:
    """Map evolution score to named level + progress info."""
    level_name = "Rookie"
    level_floor = 0
    next_name = "Beginner"
    next_floor = 50

    for i, (threshold, name) in enumerate(MIND_LEVELS):
        if score >= threshold:
            level_name = name
            level_floor = threshold
            if i + 1 < len(MIND_LEVELS):
                next_floor = MIND_LEVELS[i + 1][0]
                next_name = MIND_LEVELS[i + 1][1]
            else:
                next_floor = 1000
                next_name = "Godmode"

    points_to_next = max(0, next_floor - score)
    level_range = next_floor - level_floor
    progress_pct = round((score - level_floor) / level_range * 100, 1) if level_range > 0 else 100.0

    return {
        "level": level_name,
        "score": score,
        "next_level": next_name if level_name != "Godmode" else None,
        "points_to_next": points_to_next if level_name != "Godmode" else 0,
        "progress_pct": progress_pct,
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

    # 1. System Age (0-100% of weight based on cycles)
    total_cycles = system.get("total_lifetime_cycles", 0)
    # 500 cycles = 50%, 2000 = 100%
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
    sess_pct = min(1.0, len(closed_sessions) / 8)  # 8 sessions = full
    breakdown["sessions_completed"] = {
        "raw": len(closed_sessions),
        "pct": round(sess_pct * 100, 1),
        "points": round(sess_pct * SCORE_WEIGHTS["sessions_completed"]),
        "label": "Sessions Completed",
        "detail": f"{len(closed_sessions)} sessions completed, {len(sessions)} total",
    }

    # 3. Trades Executed
    total_trades = system.get("total_lifetime_trades", 0)
    trade_pct = min(1.0, total_trades / 200)  # 200 trades = full
    breakdown["trades_executed"] = {
        "raw": total_trades,
        "pct": round(trade_pct * 100, 1),
        "points": round(trade_pct * SCORE_WEIGHTS["trades_executed"]),
        "label": "Trades Executed",
        "detail": f"{total_trades} lifetime trades",
    }

    # 4. Outcome Coverage — how many outcomes have been fully evaluated
    outcome_summary = db.get_outcome_summary()
    total_outcomes = outcome_summary.get("total", 0)
    completed_outcomes = outcome_summary.get("completed", 0)
    coverage = completed_outcomes / max(total_outcomes, 1) if total_outcomes > 0 else 0
    # Also need minimum volume
    volume_factor = min(1.0, total_outcomes / 30)  # 30 outcomes = full volume credit
    outcome_pct = coverage * volume_factor
    breakdown["outcome_coverage"] = {
        "raw": completed_outcomes,
        "pct": round(outcome_pct * 100, 1),
        "points": round(outcome_pct * SCORE_WEIGHTS["outcome_coverage"]),
        "label": "Outcome Evaluation",
        "detail": f"{completed_outcomes}/{total_outcomes} outcomes evaluated",
    }

    # 5. Adaptation Quality — ratio of allowed vs blocked adaptations
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
    # Cap contribution: 40-60% = some credit, above 60% = full
    wr_pct = min(1.0, max(0, (win_rate - 30) / 40))  # 30% = 0, 70% = 1
    breakdown["win_rate_quality"] = {
        "raw": win_rate,
        "pct": round(wr_pct * 100, 1),
        "points": round(wr_pct * SCORE_WEIGHTS["win_rate_quality"]),
        "label": "Win Rate",
        "detail": f"{win_rate:.1f}% win rate (capped contribution)",
    }

    # 13. Memory Depth
    memory_count = db.get_memory_count()
    mem_pct = min(1.0, memory_count / 50)  # 50 memories = full
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

    mind_level = _get_mind_level(total_score)

    return {
        "evolution_score": total_score,
        "mind_level": mind_level,
        "breakdown": breakdown,
        "max_possible": 1000,
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
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Score Component Helpers
# ---------------------------------------------------------------------------

def _compute_adaptation_quality(session_id: int | None) -> dict:
    """Score adaptation quality from the journal."""
    journal = db.get_adaptation_journal(session_id=session_id, limit=200)
    if len(journal) < 5:
        return {"ratio": 0, "pct": 0.3, "detail": "Warming up (< 5 adaptation attempts)"}

    allowed = sum(1 for j in journal if j.get("allowed_or_blocked") == "allowed")
    blocked = sum(1 for j in journal if j.get("allowed_or_blocked") == "blocked")
    total = allowed + blocked
    if total == 0:
        return {"ratio": 0, "pct": 0.3, "detail": "No adaptation data"}

    # Good ratio: 30-70% allowed is ideal (means guard is working but not blocking everything)
    ratio = allowed / total
    if 0.3 <= ratio <= 0.7:
        pct = 0.8 + (0.2 * min(1.0, total / 50))  # volume bonus
    elif ratio > 0.7:
        pct = 0.5  # too permissive — guard may be too loose
    else:
        pct = 0.4  # too strict — guard may be blocking valid adaptations

    return {
        "ratio": round(ratio, 3),
        "pct": min(1.0, pct),
        "detail": f"{allowed}/{total} adaptations allowed ({ratio:.0%})",
    }


def _compute_discipline_score(session_id: int | None) -> dict:
    """Score discipline from blocked trades and cooldown behavior."""
    # Check how many trades were blocked for good reasons
    missed_summary = db.get_missed_opportunity_summary()
    total_blocked = missed_summary.get("total", 0)
    confirmed_missed = missed_summary.get("confirmed_missed", 0)

    # Good discipline = blocking trades, and most blocked trades turned out NOT to be missed
    if total_blocked == 0:
        return {"score": 0, "pct": 0.3, "detail": "Warming up (no blocked trade data)"}

    false_positive_rate = confirmed_missed / total_blocked if total_blocked > 0 else 0
    # Low false positive = good discipline (blocked and it was RIGHT to block)
    discipline_pct = max(0, 1.0 - false_positive_rate)

    # Volume factor
    volume = min(1.0, total_blocked / 20)
    final_pct = discipline_pct * 0.7 + volume * 0.3

    return {
        "score": round(discipline_pct, 3),
        "pct": min(1.0, final_pct),
        "detail": f"{total_blocked} blocked, {confirmed_missed} were actual misses ({false_positive_rate:.0%} false positive)",
    }


def _compute_drawdown_score(session_id: int | None) -> dict:
    """Score drawdown control from equity curve."""
    if not session_id:
        return {"max_dd": 0, "pct": 0.5, "detail": "No session data"}

    snapshots = db.get_recent_snapshots(session_id, limit=200)
    if len(snapshots) < 10:
        return {"max_dd": 0, "pct": 0.5, "detail": "Warming up (< 10 snapshots)"}

    equities = [s.get("equity", 100) for s in reversed(snapshots) if s.get("equity")]
    if not equities:
        return {"max_dd": 0, "pct": 0.5, "detail": "No equity data"}

    # Compute max drawdown
    peak = equities[0]
    max_dd = 0
    for eq in equities:
        peak = max(peak, eq)
        dd = (peak - eq) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)

    # Score: <5% dd = excellent, <10% = good, <20% = ok, >20% = poor
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
    """Score regime intelligence accuracy."""
    if not session_id:
        return {"accuracy": 0, "pct": 0.3, "detail": "No session data"}

    profiles = db.get_regime_profiles(session_id=session_id)
    if len(profiles) < 3:
        return {"accuracy": 0, "pct": 0.3, "detail": "Warming up (< 3 regime profiles)"}

    # Score based on: profiles with recommendations + their accuracy
    with_recs = [p for p in profiles if p.get("recommended_action") != "neutral"]
    total_trades_in_recs = sum(p.get("total_trades", 0) for p in with_recs)

    # Preferred strategies should have higher win rates
    preferred = [p for p in with_recs if p.get("recommended_action") == "prefer"]
    avoided = [p for p in with_recs if p.get("recommended_action") == "avoid"]

    pref_wr = sum(p.get("win_rate", 0) for p in preferred) / len(preferred) if preferred else 0
    avoid_wr = sum(p.get("win_rate", 0) for p in avoided) / len(avoided) if avoided else 100

    # Good regime intelligence: preferred have high WR, avoided have low WR
    if preferred and avoided:
        gap = pref_wr - avoid_wr  # should be positive
        accuracy = min(1.0, max(0, gap / 40))  # 40% gap = perfect
    elif preferred:
        accuracy = min(1.0, pref_wr / 70)  # 70% WR for preferred = perfect
    else:
        accuracy = 0.3  # neutral

    volume = min(1.0, total_trades_in_recs / 20)
    pct = accuracy * 0.7 + volume * 0.3

    return {
        "accuracy": round(accuracy, 3),
        "pct": min(1.0, pct),
        "detail": f"{len(with_recs)} regime recommendations, {len(profiles)} profiles tracked",
    }


def _compute_missed_opp_score() -> dict:
    """Score missed opportunity review quality."""
    summary = db.get_missed_opportunity_summary()
    total = summary.get("total", 0)
    if total < 3:
        return {"reviewed": 0, "pct": 0.3, "detail": "Warming up (< 3 missed opps recorded)"}

    confirmed = summary.get("confirmed_missed", 0)
    minor = summary.get("minor", 0) or 0
    moderate = summary.get("moderate", 0) or 0
    major = summary.get("major", 0) or 0

    # Good sensing = catching major misses, few major misses overall
    severity_score = 1.0
    if major > 3:
        severity_score -= 0.3
    if moderate > 5:
        severity_score -= 0.2

    # Volume credit for reviewing opportunities
    volume = min(1.0, total / 15)
    pct = max(0.1, severity_score * 0.6 + volume * 0.4)

    return {
        "reviewed": total,
        "pct": min(1.0, pct),
        "detail": f"{total} tracked, {confirmed} confirmed ({minor}m/{moderate}M/{major}X severity)",
    }


def _compute_consistency_score(sessions: list[dict]) -> dict:
    """Score stability across sessions."""
    completed = [s for s in sessions if not s.get("is_active") and s.get("total_trades", 0) > 0]
    if len(completed) < 2:
        return {"score": 0, "pct": 0.4, "detail": "Need 2+ completed sessions"}

    # Check if PnL direction is consistent across sessions
    pnls = [s.get("realized_pnl", 0) for s in completed]
    positive = sum(1 for p in pnls if p > 0)
    consistency = positive / len(pnls) if pnls else 0.5

    # Also check cycle counts (longer sessions = more consistent)
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
    """Score recovery after poor periods (losing trades followed by wins)."""
    if not session_id:
        return {"score": 0, "pct": 0.5, "detail": "No session data"}

    trades, _ = db.get_trades(session_id=session_id, limit=100)
    sells = [t for t in trades if t.get("action") == "SELL"]
    if len(sells) < 5:
        return {"score": 0, "pct": 0.4, "detail": "Warming up (< 5 sells)"}

    # Look for loss → win transitions
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
# Skill Breakdown (9 skills, 0-100 each)
# ---------------------------------------------------------------------------

def compute_skill_breakdown() -> list[dict]:
    """Compute 9 individual skill scores from real system behavior."""
    score_data = compute_evolution_score()
    breakdown = score_data.get("breakdown", {})

    skills = []

    # 1. Discipline
    disc = breakdown.get("discipline_quality", {})
    skills.append({
        "name": "Discipline",
        "score": _scale_to_100(disc.get("pct", 0.3)),
        "description": "Blocked bad trades, low overtrading, cooldown respect",
        "status": _skill_status(disc.get("pct", 0.3)),
        "detail": disc.get("detail", ""),
    })

    # 2. Risk Control
    dd = breakdown.get("drawdown_control", {})
    skills.append({
        "name": "Risk Control",
        "score": _scale_to_100(dd.get("pct", 0.5)),
        "description": "Drawdown behavior, exposure control, good exits",
        "status": _skill_status(dd.get("pct", 0.5)),
        "detail": dd.get("detail", ""),
    })

    # 3. Timing
    outcome = breakdown.get("outcome_coverage", {})
    skills.append({
        "name": "Timing",
        "score": _scale_to_100(outcome.get("pct", 0.3)),
        "description": "Entry/exit quality from delayed outcome evaluations",
        "status": _skill_status(outcome.get("pct", 0.3)),
        "detail": outcome.get("detail", ""),
    })

    # 4. Adaptation
    adapt = breakdown.get("adaptation_quality", {})
    skills.append({
        "name": "Adaptation",
        "score": _scale_to_100(adapt.get("pct", 0.3)),
        "description": "Whether adaptations improved later outcomes",
        "status": _skill_status(adapt.get("pct", 0.3)),
        "detail": adapt.get("detail", ""),
    })

    # 5. Regime Reading
    regime = breakdown.get("regime_accuracy", {})
    skills.append({
        "name": "Regime Reading",
        "score": _scale_to_100(regime.get("pct", 0.3)),
        "description": "Accuracy of regime + strategy fit predictions",
        "status": _skill_status(regime.get("pct", 0.3)),
        "detail": regime.get("detail", ""),
    })

    # 6. Opportunity Sensing
    missed = breakdown.get("missed_opp_learning", {})
    skills.append({
        "name": "Opportunity Sensing",
        "score": _scale_to_100(missed.get("pct", 0.3)),
        "description": "Missed opportunity review and learning quality",
        "status": _skill_status(missed.get("pct", 0.3)),
        "detail": missed.get("detail", ""),
    })

    # 7. Consistency
    cons = breakdown.get("session_consistency", {})
    skills.append({
        "name": "Consistency",
        "score": _scale_to_100(cons.get("pct", 0.4)),
        "description": "Stability of performance across sessions",
        "status": _skill_status(cons.get("pct", 0.4)),
        "detail": cons.get("detail", ""),
    })

    # 8. Self-Correction
    recovery = breakdown.get("recovery_ability", {})
    skills.append({
        "name": "Self-Correction",
        "score": _scale_to_100(recovery.get("pct", 0.4)),
        "description": "How often mistakes get corrected in later trades",
        "status": _skill_status(recovery.get("pct", 0.4)),
        "detail": recovery.get("detail", ""),
    })

    # 9. Patience
    # Patience = combination of discipline (not forcing) + adaptation quality (not jittering)
    patience_pct = (disc.get("pct", 0.3) * 0.5 + adapt.get("pct", 0.3) * 0.3 +
                    cons.get("pct", 0.4) * 0.2)
    skills.append({
        "name": "Patience",
        "score": _scale_to_100(patience_pct),
        "description": "Not forcing trades in low-quality conditions",
        "status": _skill_status(patience_pct),
        "detail": "Composite of discipline, adaptation quality, and consistency",
    })

    return skills


def _scale_to_100(pct: float) -> int:
    """Scale a 0-1 percentage to 0-100 integer."""
    return max(0, min(100, round(pct * 100)))


def _skill_status(pct: float) -> str:
    """Determine skill status label."""
    if pct >= 0.8:
        return "strong"
    elif pct >= 0.6:
        return "developing"
    elif pct >= 0.4:
        return "learning"
    elif pct >= 0.2:
        return "weak"
    else:
        return "warming_up"


# ---------------------------------------------------------------------------
# Recent Learning Feed
# ---------------------------------------------------------------------------

def get_recent_learning() -> list[dict]:
    """Generate a structured feed of recent improvements and regressions."""
    sid = session_manager.get_session_id()
    feed = []

    if not sid:
        return [{"type": "info", "message": "No active session", "area": "system"}]

    # 1. Check recent memories for insights
    memories = db.get_active_memories(session_id=sid, limit=5)
    for mem in memories[:3]:
        mtype = mem.get("memory_type", "")
        lesson = mem.get("lesson_text", "")
        observed = mem.get("times_observed", 1)
        if lesson:
            feed.append({
                "type": "lesson_absorbed",
                "message": lesson,
                "area": mem.get("strategy", "general"),
                "confidence": round(mem.get("confidence_weight", 0.5), 2),
                "times_seen": observed,
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
        market_reward = bstate.get("market_reward_state", "neutral")
        self_state = bstate.get("system_self_state", "learning")
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

    # 6. Check daily reviews for latest observations
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
        }

        # Add trade breakdown
        entry["buys"] = s.get("total_buys", 0)
        entry["sells"] = s.get("total_sells", 0)

        timeline.append(entry)

    return timeline


# ---------------------------------------------------------------------------
# Snapshot — called periodically to persist evolution history
# ---------------------------------------------------------------------------

def take_evolution_snapshot(session_id: int, cycle_number: int) -> None:
    """Take a periodic snapshot of evolution state for history tracking.

    Called every 100 cycles from session_manager.on_cycle_complete.
    """
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
    """Find a skill score by name."""
    for s in skills:
        if s["name"] == name:
            return s["score"]
    return 0


# ---------------------------------------------------------------------------
# Growth History
# ---------------------------------------------------------------------------

def get_evolution_history(limit: int = 100) -> list[dict]:
    """Get evolution score history for charting."""
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

    return {
        "evolution_score": score_data["evolution_score"],
        "max_possible": 1000,
        "mind_level": score_data["mind_level"],
        "skills": skills,
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
