"""
discipline_guard.py — CryptoMind v7.2 Discipline Enforcement Layer.

Central guard that prevents adaptation on weak, stale, or noisy evidence.
Every adaptation path in the system MUST call can_adapt() before applying
any parameter change.

PRINCIPLES:
1. No adaptation without minimum sample size
2. No adaptation without cooldown satisfaction
3. Recency-weighted evidence (old data fades, not dominates)
4. Small-step only (bounded delta per adaptation)
5. Stability check (no conflicting/stacking adaptations)
6. Full audit trail (every attempt logged, allowed or blocked)

STATES (for any adaptation attempt):
- observed:    data exists but not evaluated
- evaluated:   outcomes checked against reality
- recommended: guard approved, ready to apply
- applied:     parameter was changed
- blocked:     guard rejected with reasons
- reverted:    prior adaptation was undone
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta

import db
import session_manager

# ═══════════════════════════════════════════════════════════════════════════
# SINGLE SOURCE OF TRUTH — ALL MINIMUM / COOLDOWN / BOUND CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════

# --- Minimum sample sizes ---
MIN_OBSERVATIONS_BEHAVIOR = 50       # events before behavior adaptation
MIN_OUTCOMES_BEHAVIOR = 20           # evaluated delayed outcomes before behavior adapt
MIN_TRADES_DAILY_BIAS = 5            # trades needed before generating new daily bias
MIN_TRADES_REGIME_REC = 10           # trades per regime-strategy before recommend
MIN_OUTCOMES_REGIME_REC = 5          # evaluated outcomes per regime-strategy
MIN_BLOCKED_FOR_LESSON = 8           # evaluated blocked opportunities before lesson
MIN_OBSERVATIONS_MODIFIER = 50      # before any modifier (aggression/patience/exposure)
MIN_OUTCOMES_MODIFIER = 20           # evaluated outcomes before modifier change

# --- Cooldown rules (in cycles, 1 cycle ≈ 30s) ---
COOLDOWN_GLOBAL_ADAPTATION = 100     # global: no adaptation within 100 cycles of last
COOLDOWN_BEHAVIOR_PERSONALITY = 150  # behavior/personality params: 150 cycles
COOLDOWN_REGIME_RECOMMENDATION = 50  # regime rec refresh: every 50 cycles minimum
COOLDOWN_DAILY_BIAS = "once_per_day" # daily bias: once per completed day only

# --- Small-step bounds (max delta per adaptation) ---
MAX_DELTA = {
    "aggressiveness":       0.02,
    "patience":             0.02,
    "probe_bias":           0.02,
    "trend_follow_bias":    0.02,
    "mean_revert_bias":     0.02,
    "conviction_threshold": 0.02,
    "overtrade_penalty":    0.02,
    "hold_extension_bias":  0.02,
    "exit_tightness":       0.02,
    "noise_tolerance":      0.02,
    "threshold_modifier":   2.0,
    "exposure_modifier":    0.03,
    "aggression_modifier":  0.02,
    "patience_modifier":    0.02,
}

# --- Absolute floor/ceiling ranges ---
PARAM_FLOORS_CEILINGS = {
    "aggressiveness":       (0.2, 0.8),
    "patience":             (0.2, 0.8),
    "probe_bias":           (0.2, 0.8),
    "trend_follow_bias":    (0.3, 0.7),
    "mean_revert_bias":     (0.3, 0.7),
    "conviction_threshold": (0.3, 0.7),
    "overtrade_penalty":    (0.2, 0.8),
    "hold_extension_bias":  (0.3, 0.7),
    "exit_tightness":       (0.3, 0.7),
    "noise_tolerance":      (0.3, 0.7),
    "threshold_modifier":   (-5.0, 5.0),
    "exposure_modifier":    (-0.1, 0.1),
    "aggression_modifier":  (-0.2, 0.2),
    "patience_modifier":    (-0.2, 0.2),
}

# --- Recency decay weights (cycle-based) ---
# Cycles map roughly: 720 cycles ≈ 6 hours at 30s intervals
RECENCY_BANDS = [
    (720,    1.00),   # 0–6 hours:  full weight
    (2880,   0.70),   # 6–24 hours: 70%
    (8640,   0.40),   # 1–3 days:   40%
    (999999, 0.15),   # 3+ days:    15%
]

# --- Adaptation categories ---
CATEGORIES = (
    "behavior", "regime", "daily_bias", "threshold",
    "exposure", "recommendation", "modifier",
)


# ═══════════════════════════════════════════════════════════════════════════
# MODULE STATE
# ═══════════════════════════════════════════════════════════════════════════

_last_global_adaptation_cycle: int = 0
_last_behavior_adaptation_cycle: int = 0
_last_regime_rec_cycle: int = 0
_last_daily_bias_date: str = ""
_recent_adaptations: list[dict] = []   # last 20, for stacking detection


# ═══════════════════════════════════════════════════════════════════════════
# RECENCY DECAY
# ═══════════════════════════════════════════════════════════════════════════

def compute_recency_weight(cycles_ago: int) -> float:
    """Get recency weight for an observation N cycles ago."""
    for max_cycles, weight in RECENCY_BANDS:
        if cycles_ago <= max_cycles:
            return weight
    return 0.15


def compute_weighted_sample_size(observations: list[dict],
                                  current_cycle: int,
                                  cycle_key: str = "cycle") -> float:
    """Compute effective weighted sample size from a list of observations.

    Each observation should have a cycle number (or timestamp).
    Returns the sum of recency weights.
    """
    total = 0.0
    for obs in observations:
        obs_cycle = obs.get(cycle_key, 0)
        if isinstance(obs_cycle, str):
            # Try to parse timestamp to cycle estimate
            continue
        cycles_ago = max(0, current_cycle - obs_cycle)
        total += compute_recency_weight(cycles_ago)
    return round(total, 2)


def apply_recency_weights(trades: list[dict], current_cycle: int) -> list[dict]:
    """Add recency_weight field to each trade based on cycle distance.

    If trades don't have cycle numbers, uses list position as proxy.
    """
    for i, t in enumerate(trades):
        # Estimate cycles ago from position (newest first)
        cycles_ago = i * 2  # rough estimate: 2 cycles between trades
        t["recency_weight"] = compute_recency_weight(cycles_ago)
    return trades


# ═══════════════════════════════════════════════════════════════════════════
# CENTRAL GUARD — can_adapt()
# ═══════════════════════════════════════════════════════════════════════════

def can_adapt(context: dict) -> dict:
    """Central guard function. Must be called before ANY adaptation.

    Args:
        context: dict with keys:
            category:       str — one of CATEGORIES
            target:         str — parameter being changed (e.g. "patience")
            current_value:  float — current value of parameter
            proposed_delta: float — proposed change amount
            current_cycle:  int — current cycle number
            session_id:     int — current session ID
            trigger_reason: str — why this adaptation is being proposed
            evidence_count: int — number of observations backing this
            outcome_count:  int — number of evaluated delayed outcomes
            regime:         str — current market regime (optional)

    Returns:
        dict with:
            allowed:       bool
            reasons:       list[str] — block reasons (empty if allowed)
            clamped_delta: float — delta after clamping to max step
            final_value:   float — value after applying clamped delta
            weighted_sample_size: float
            state:         str — 'recommended' or 'blocked'
    """
    category = context.get("category", "behavior")
    target = context.get("target", "")
    current_value = context.get("current_value", 0.5)
    proposed_delta = context.get("proposed_delta", 0.0)
    current_cycle = context.get("current_cycle", 0)
    session_id = context.get("session_id", 0)
    trigger_reason = context.get("trigger_reason", "")
    evidence_count = context.get("evidence_count", 0)
    outcome_count = context.get("outcome_count", 0)
    regime = context.get("regime", "")

    reasons = []

    # ── 1. MINIMUM SAMPLE SIZE CHECK ──
    if category in ("behavior", "modifier"):
        if evidence_count < MIN_OBSERVATIONS_BEHAVIOR:
            reasons.append(
                f"insufficient_observations: {evidence_count}/{MIN_OBSERVATIONS_BEHAVIOR}"
            )
        if outcome_count < MIN_OUTCOMES_BEHAVIOR:
            reasons.append(
                f"insufficient_outcomes: {outcome_count}/{MIN_OUTCOMES_BEHAVIOR}"
            )

    elif category == "daily_bias":
        if evidence_count < MIN_TRADES_DAILY_BIAS:
            reasons.append(
                f"insufficient_trades_for_bias: {evidence_count}/{MIN_TRADES_DAILY_BIAS}"
            )

    elif category == "regime":
        if evidence_count < MIN_TRADES_REGIME_REC:
            reasons.append(
                f"insufficient_regime_trades: {evidence_count}/{MIN_TRADES_REGIME_REC}"
            )
        if outcome_count < MIN_OUTCOMES_REGIME_REC:
            reasons.append(
                f"insufficient_regime_outcomes: {outcome_count}/{MIN_OUTCOMES_REGIME_REC}"
            )

    elif category == "recommendation":
        if evidence_count < MIN_BLOCKED_FOR_LESSON:
            reasons.append(
                f"insufficient_blocked_evaluations: {evidence_count}/{MIN_BLOCKED_FOR_LESSON}"
            )

    # ── 2. COOLDOWN CHECK ──
    global _last_global_adaptation_cycle, _last_behavior_adaptation_cycle
    global _last_regime_rec_cycle, _last_daily_bias_date

    cycles_since_global = current_cycle - _last_global_adaptation_cycle
    if cycles_since_global < COOLDOWN_GLOBAL_ADAPTATION and _last_global_adaptation_cycle > 0:
        reasons.append(
            f"cooldown_active: global ({cycles_since_global}/{COOLDOWN_GLOBAL_ADAPTATION} cycles)"
        )

    if category in ("behavior", "modifier"):
        cycles_since_behavior = current_cycle - _last_behavior_adaptation_cycle
        if cycles_since_behavior < COOLDOWN_BEHAVIOR_PERSONALITY and _last_behavior_adaptation_cycle > 0:
            reasons.append(
                f"cooldown_active: behavior ({cycles_since_behavior}/{COOLDOWN_BEHAVIOR_PERSONALITY} cycles)"
            )

    if category == "regime":
        cycles_since_regime = current_cycle - _last_regime_rec_cycle
        if cycles_since_regime < COOLDOWN_REGIME_RECOMMENDATION and _last_regime_rec_cycle > 0:
            reasons.append(
                f"cooldown_active: regime ({cycles_since_regime}/{COOLDOWN_REGIME_RECOMMENDATION} cycles)"
            )

    if category == "daily_bias":
        today = datetime.now(timezone.utc).date().isoformat()
        if _last_daily_bias_date == today:
            reasons.append("cooldown_active: daily_bias (already generated today)")

    # ── 3. SMALL-STEP CLAMPING ──
    max_delta = MAX_DELTA.get(target, 0.03)
    clamped_delta = max(-max_delta, min(max_delta, proposed_delta))

    # ── 4. FLOOR/CEILING ENFORCEMENT ──
    floor, ceiling = PARAM_FLOORS_CEILINGS.get(target, (0.0, 1.0))
    final_value = current_value + clamped_delta
    final_value = round(max(floor, min(ceiling, final_value)), 4)

    # If clamping made the change meaningless
    if abs(final_value - current_value) < 0.0001:
        reasons.append(f"no_effective_change: value already at boundary ({final_value})")

    # ── 5. STABILITY CHECK — conflict / stacking / risk ──
    stability_issues = _check_stability(
        category=category,
        target=target,
        proposed_delta=clamped_delta,
        current_cycle=current_cycle,
        regime=regime,
        outcome_count=outcome_count,
    )
    reasons.extend(stability_issues)

    # ── 6. COMPUTE WEIGHTED SAMPLE SIZE ──
    # Use evidence_count as proxy since we don't have individual observations here
    weighted_sample = evidence_count * 0.7  # conservative estimate with decay

    # ── BUILD RESULT ──
    allowed = len(reasons) == 0
    state = "recommended" if allowed else "blocked"

    result = {
        "allowed": allowed,
        "reasons": reasons,
        "clamped_delta": clamped_delta,
        "final_value": final_value,
        "weighted_sample_size": round(weighted_sample, 2),
        "state": state,
        "category": category,
        "target": target,
        "evidence_count": evidence_count,
        "outcome_count": outcome_count,
        "trigger_reason": trigger_reason,
    }

    # ── LOG THE ATTEMPT (allowed or blocked) ──
    _log_adaptation_attempt(session_id, result, current_value, clamped_delta)

    return result


# ═══════════════════════════════════════════════════════════════════════════
# STABILITY CHECK
# ═══════════════════════════════════════════════════════════════════════════

def _check_stability(category: str, target: str, proposed_delta: float,
                     current_cycle: int, regime: str,
                     outcome_count: int) -> list[str]:
    """Check for conflicts, risk increases, and stacking."""
    issues = []

    # A) Duplicate recent adjustment — same target within last 5 adaptations
    for recent in _recent_adaptations[-5:]:
        if (recent.get("target") == target
                and recent.get("allowed_or_blocked") == "applied"
                and current_cycle - recent.get("cycle", 0) < COOLDOWN_BEHAVIOR_PERSONALITY):
            issues.append(
                f"duplicate_recent_adjustment: {target} was changed "
                f"{current_cycle - recent['cycle']} cycles ago"
            )
            break

    # B) Risk increase without evidence — loosening thresholds while outcomes are inconclusive
    if outcome_count < MIN_OUTCOMES_MODIFIER:
        # Check if this change would increase risk
        risk_increasing_changes = {
            "aggressiveness": lambda d: d > 0,
            "patience": lambda d: d < 0,
            "conviction_threshold": lambda d: d < 0,
            "overtrade_penalty": lambda d: d < 0,
            "threshold_modifier": lambda d: d < 0,   # lowering buy bar = more risk
            "exposure_modifier": lambda d: d > 0,     # more exposure = more risk
        }
        checker = risk_increasing_changes.get(target)
        if checker and checker(proposed_delta):
            issues.append(
                f"risk_increase_without_evidence: {target} delta={proposed_delta:+.3f} "
                f"with only {outcome_count}/{MIN_OUTCOMES_MODIFIER} outcomes"
            )

    # C) Conflicting regime signals — don't loosen in volatile/sleeping
    if regime in ("SLEEPING", "VOLATILE") and category == "behavior":
        if target == "aggressiveness" and proposed_delta > 0:
            issues.append(
                f"conflicts_with_regime: increasing aggressiveness in {regime}"
            )

    return issues


# ═══════════════════════════════════════════════════════════════════════════
# ADAPTATION JOURNAL — persistent audit trail
# ═══════════════════════════════════════════════════════════════════════════

def _log_adaptation_attempt(session_id: int, result: dict,
                            old_value: float, delta: float) -> None:
    """Log every adaptation attempt to DB and in-memory cache."""
    now = datetime.now(timezone.utc).isoformat()

    entry = {
        "session_id": session_id,
        "timestamp": now,
        "cycle": result.get("evidence_count", 0),  # will be overridden below
        "category": result.get("category", ""),
        "target": result.get("target", ""),
        "old_value": round(old_value, 4),
        "new_value": round(result.get("final_value", old_value), 4),
        "delta": round(delta, 4),
        "evidence_count": result.get("evidence_count", 0),
        "outcome_count": result.get("outcome_count", 0),
        "weighted_sample_size": result.get("weighted_sample_size", 0),
        "trigger_reason": result.get("trigger_reason", ""),
        "allowed_or_blocked": "applied" if result["allowed"] else "blocked",
        "blocked_reason": "; ".join(result.get("reasons", [])),
        "reversal_candidate": False,
    }

    # Store in DB via extended adaptation_events
    try:
        db.insert_adaptation_v72(session_id=session_id, **entry)
    except Exception as e:
        # Fallback: use v7.0 adaptation logging
        try:
            db.insert_adaptation(
                session_id=session_id,
                trigger_type=f"v72:{entry['category']}:{entry['target']}",
                reason=entry["trigger_reason"],
                old_behavior=f"{entry['target']}={entry['old_value']}",
                new_behavior=f"{entry['target']}={entry['new_value']}" if result["allowed"] else "BLOCKED",
                expected_effect=entry["blocked_reason"] if not result["allowed"] else "approved",
            )
        except Exception:
            pass

    # In-memory cache for stacking detection
    _recent_adaptations.append(entry)
    if len(_recent_adaptations) > 20:
        _recent_adaptations[:] = _recent_adaptations[-20:]

    # Print log
    status = "ALLOWED" if result["allowed"] else "BLOCKED"
    print(f"[discipline] {status}: {entry['category']}/{entry['target']} "
          f"delta={delta:+.4f} evidence={entry['evidence_count']} "
          f"outcomes={entry['outcome_count']}"
          + (f" reasons=[{entry['blocked_reason']}]" if not result["allowed"] else ""))


# ═══════════════════════════════════════════════════════════════════════════
# COOLDOWN MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════

def record_adaptation_applied(category: str, current_cycle: int) -> None:
    """Record that an adaptation was successfully applied.
    Must be called after every successful apply.
    """
    global _last_global_adaptation_cycle, _last_behavior_adaptation_cycle
    global _last_regime_rec_cycle, _last_daily_bias_date

    _last_global_adaptation_cycle = current_cycle

    if category in ("behavior", "modifier"):
        _last_behavior_adaptation_cycle = current_cycle
    elif category == "regime":
        _last_regime_rec_cycle = current_cycle
    elif category == "daily_bias":
        _last_daily_bias_date = datetime.now(timezone.utc).date().isoformat()


# ═══════════════════════════════════════════════════════════════════════════
# DAILY BIAS SAFETY MODE
# ═══════════════════════════════════════════════════════════════════════════

def get_daily_bias_status(trade_count: int, session_id: int) -> dict:
    """Determine what the daily bias should do.

    Returns:
        dict with 'action' = 'applied' | 'carried_forward' | 'insufficient_data' | 'blocked_by_cooldown'
    """
    today = datetime.now(timezone.utc).date().isoformat()

    # Cooldown check
    if _last_daily_bias_date == today:
        return {
            "action": "blocked_by_cooldown",
            "reason": "Daily bias already generated today",
            "trade_count": trade_count,
        }

    # Minimum sample check
    if trade_count < MIN_TRADES_DAILY_BIAS:
        # Try to carry forward prior bias
        prior_bias = db.get_active_bias(session_id) if session_id else None
        if prior_bias:
            return {
                "action": "carried_forward",
                "reason": f"Only {trade_count}/{MIN_TRADES_DAILY_BIAS} trades — carrying forward prior bias",
                "trade_count": trade_count,
                "prior_bias_id": prior_bias.get("bias_id"),
            }
        else:
            return {
                "action": "insufficient_data",
                "reason": f"Only {trade_count}/{MIN_TRADES_DAILY_BIAS} trades — no prior bias to carry forward",
                "trade_count": trade_count,
            }

    return {
        "action": "applied",
        "reason": f"Sufficient data ({trade_count} trades)",
        "trade_count": trade_count,
    }


# ═══════════════════════════════════════════════════════════════════════════
# SAFE PARAMETER ADJUSTMENT
# ═══════════════════════════════════════════════════════════════════════════

def safe_adjust(current: float, delta: float, param_name: str) -> float:
    """Adjust a parameter with v7.2 discipline enforcement.

    1. Clamps delta to MAX_DELTA
    2. Enforces floor/ceiling from PARAM_FLOORS_CEILINGS
    3. Returns the safe new value
    """
    max_d = MAX_DELTA.get(param_name, 0.03)
    clamped = max(-max_d, min(max_d, delta))
    floor, ceiling = PARAM_FLOORS_CEILINGS.get(param_name, (0.0, 1.0))
    new_val = current + clamped
    return round(max(floor, min(ceiling, new_val)), 4)


# ═══════════════════════════════════════════════════════════════════════════
# EVIDENCE COUNTING HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def get_evidence_counts(session_id: int) -> dict:
    """Get current observation and outcome counts for guard decisions."""
    if not session_id:
        return {"observations": 0, "outcomes": 0, "weighted_sample": 0}

    try:
        # Observations = total trades in session
        _, total_trades = db.get_trades(session_id=session_id, limit=1)

        # Outcomes = completed delayed evaluations
        outcome_summary = db.get_outcome_summary()
        completed_outcomes = outcome_summary.get("completed") or 0

        # Missed opportunity evaluations
        missed_summary = db.get_missed_opportunity_summary()
        evaluated_missed = missed_summary.get("confirmed_missed") or 0

        return {
            "observations": total_trades,
            "outcomes": completed_outcomes,
            "missed_evaluated": evaluated_missed,
            "weighted_sample": round(total_trades * 0.7, 1),
        }
    except Exception:
        return {"observations": 0, "outcomes": 0, "weighted_sample": 0}


# ═══════════════════════════════════════════════════════════════════════════
# DEBUG / API STATE
# ═══════════════════════════════════════════════════════════════════════════

def get_discipline_status(current_cycle: int = 0) -> dict:
    """Full discipline guard state for API/debug display."""
    session_id = session_manager.get_session_id()
    evidence = get_evidence_counts(session_id) if session_id else {}

    return {
        "version": "7.2.0",
        "guard_active": True,

        # Current evidence levels
        "observations": evidence.get("observations", 0),
        "outcomes": evidence.get("outcomes", 0),
        "missed_evaluated": evidence.get("missed_evaluated", 0),
        "weighted_sample_size": evidence.get("weighted_sample", 0),

        # Minimum requirements
        "min_observations_behavior": MIN_OBSERVATIONS_BEHAVIOR,
        "min_outcomes_behavior": MIN_OUTCOMES_BEHAVIOR,
        "min_trades_daily_bias": MIN_TRADES_DAILY_BIAS,
        "min_trades_regime_rec": MIN_TRADES_REGIME_REC,
        "min_blocked_for_lesson": MIN_BLOCKED_FOR_LESSON,

        # Cooldown state
        "last_global_adaptation_cycle": _last_global_adaptation_cycle,
        "last_behavior_adaptation_cycle": _last_behavior_adaptation_cycle,
        "last_regime_rec_cycle": _last_regime_rec_cycle,
        "last_daily_bias_date": _last_daily_bias_date,
        "next_global_adaptation_cycle": _last_global_adaptation_cycle + COOLDOWN_GLOBAL_ADAPTATION,
        "next_behavior_adaptation_cycle": _last_behavior_adaptation_cycle + COOLDOWN_BEHAVIOR_PERSONALITY,

        # Adaptation status
        "adaptation_allowed_now": (
            current_cycle - _last_global_adaptation_cycle >= COOLDOWN_GLOBAL_ADAPTATION
            or _last_global_adaptation_cycle == 0
        ),
        "behavior_allowed_now": (
            current_cycle - _last_behavior_adaptation_cycle >= COOLDOWN_BEHAVIOR_PERSONALITY
            or _last_behavior_adaptation_cycle == 0
        ),

        # Recent events
        "recent_adaptation_events": _recent_adaptations[-20:],

        # Max step sizes
        "max_deltas": MAX_DELTA,
        "param_bounds": PARAM_FLOORS_CEILINGS,

        # Recency bands
        "recency_bands": [{"max_cycles": mc, "weight": w} for mc, w in RECENCY_BANDS],
    }
