"""
feedback.py — CryptoMind v7.2 Feedback Loop + Behavior Adaptation Engine.

Periodic self-review system that:
1. Inspects recent trades, blocked trades, strategy outcomes
2. Detects patterns (overtrading, undertrading, missed moves)
3. v7.1: Uses regime intelligence + behavior state + missed opportunity data
4. v7.2: ALL adaptations go through discipline_guard.can_adapt()
5. Generates adaptation candidates
6. Applies bounded parameter adjustments to behavior profile

Runs every REVIEW_INTERVAL_CYCLES (50 cycles ≈ 25 min at 30s intervals).

v7.2 RULES:
- All adaptations go through central discipline guard
- Minimum 50 observations + 20 evaluated outcomes before ANY adaptation
- 150 cycle cooldown between behavior adaptations
- Small step only: ±0.02 max per adaptation
- Stability check prevents conflicting/stacking changes
- Full audit trail of every attempt (allowed or blocked)
"""

from __future__ import annotations

from datetime import datetime, timezone

import db
import session_manager
import memory_engine
import discipline_guard

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REVIEW_INTERVAL_CYCLES = 50          # review every 50 cycles
MIN_TRADES_FOR_REVIEW = 3            # need at least 3 trades to have data

# v7.2: All bounds/steps/cooldowns are now in discipline_guard.py (single source of truth)
# These remain for backward compatibility but are NOT used for enforcement.
PARAM_BOUNDS = discipline_guard.PARAM_FLOORS_CEILINGS
ADAPT_STEP = 0.02  # v7.2: reduced from 0.03 → 0.02 (enforced by discipline_guard.MAX_DELTA)

# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

_last_review_cycle = 0


# ---------------------------------------------------------------------------
# Main feedback loop — called every cycle from auto_trader
# ---------------------------------------------------------------------------

def run_feedback_check(cycle_number: int, recent_trades: list[dict],
                       strategy_states: dict, regime: str,
                       market_quality: int) -> dict | None:
    """Check if it's time for a feedback review.

    Returns review dict if review was generated, None otherwise.
    """
    global _last_review_cycle

    if cycle_number - _last_review_cycle < REVIEW_INTERVAL_CYCLES:
        return None

    session_id = session_manager.get_session_id()
    if not session_id:
        return None

    _last_review_cycle = cycle_number

    # Get data for review
    trades, _ = db.get_trades(session_id=session_id, limit=100)
    if len(trades) < MIN_TRADES_FOR_REVIEW:
        return None

    # Run review
    review = _generate_review(trades, strategy_states, regime, market_quality, cycle_number)

    # Run adaptation candidates
    adaptations = _generate_adaptations(review, cycle_number, session_id)
    review["adaptations"] = adaptations

    print(f"[feedback] Review at cycle {cycle_number}: "
          f"{review['summary']['what_worked'][:60]}...")

    return review


# ---------------------------------------------------------------------------
# Review generation
# ---------------------------------------------------------------------------

def _generate_review(trades: list[dict], strategy_states: dict,
                     regime: str, market_quality: int,
                     cycle_number: int) -> dict:
    """Generate a feedback review from recent data."""

    # --- Trade analysis ---
    sells = [t for t in trades if t.get("action") == "SELL"]
    buys = [t for t in trades if t.get("action") == "BUY"]
    wins = [t for t in sells if (t.get("pnl") or 0) > 0]
    losses = [t for t in sells if (t.get("pnl") or 0) < 0]
    net_pnl = sum(t.get("pnl", 0) for t in sells)

    # --- Strategy analysis ---
    strat_pnl: dict[str, float] = {}
    strat_trades: dict[str, int] = {}
    for t in trades:
        s = t.get("strategy", "unknown")
        strat_pnl[s] = strat_pnl.get(s, 0) + (t.get("pnl", 0) if t.get("action") == "SELL" else 0)
        strat_trades[s] = strat_trades.get(s, 0) + 1

    best_strat = max(strat_pnl, key=strat_pnl.get) if strat_pnl else "none"
    worst_strat = min(strat_pnl, key=strat_pnl.get) if strat_pnl else "none"

    # --- Pattern analysis ---
    probe_trades = [t for t in trades if "probe" in t.get("entry_type", "")]
    probe_sells = [t for t in sells if "probe" in t.get("entry_type", "")]
    probe_wins = sum(1 for t in probe_sells if (t.get("pnl") or 0) > 0)
    probe_total = len(probe_sells) if probe_sells else 0

    # --- Regime distribution ---
    regime_counts: dict[str, int] = {}
    for t in trades:
        r = t.get("regime", "SLEEPING")
        regime_counts[r] = regime_counts.get(r, 0) + 1

    # --- Detect issues ---
    issues = []
    what_worked = []
    what_failed = []

    # Overtrading detection
    if len(trades) > 20 and net_pnl < 0:
        issues.append("overtrading")
        what_failed.append("High trade frequency with negative PnL — possible overtrading")

    # Probe effectiveness
    if probe_total >= 3:
        probe_win_rate = probe_wins / probe_total * 100
        if probe_win_rate > 60:
            what_worked.append(f"Probe entries performing well ({probe_win_rate:.0f}% win rate)")
        elif probe_win_rate < 30:
            what_failed.append(f"Probe entries underperforming ({probe_win_rate:.0f}% win rate)")
            issues.append("probes_failing")

    # Strategy winners/losers
    if strat_pnl.get(best_strat, 0) > 0:
        what_worked.append(f"{best_strat} producing positive PnL (${strat_pnl[best_strat]:.6f})")
    if strat_pnl.get(worst_strat, 0) < 0:
        what_failed.append(f"{worst_strat} losing money (${strat_pnl[worst_strat]:.6f})")

    # Win rate
    total_decided = len(wins) + len(losses)
    if total_decided >= 5:
        win_rate = len(wins) / total_decided * 100
        if win_rate > 60:
            what_worked.append(f"Overall win rate strong at {win_rate:.0f}%")
        elif win_rate < 35:
            what_failed.append(f"Overall win rate weak at {win_rate:.0f}%")
            issues.append("low_win_rate")

    # Undertrading detection
    if len(trades) < 3 and cycle_number > 100:
        issues.append("undertrading")
        what_failed.append("Very few trades — system may be too passive")

    if not what_worked:
        what_worked.append("No clear positives detected in this review window")
    if not what_failed:
        what_failed.append("No critical issues detected")

    return {
        "cycle": cycle_number,
        "trades_reviewed": len(trades),
        "summary": {
            "total_trades": len(trades),
            "buys": len(buys),
            "sells": len(sells),
            "wins": len(wins),
            "losses": len(losses),
            "net_pnl": round(net_pnl, 6),
            "best_strategy": best_strat,
            "worst_strategy": worst_strat,
            "probe_win_rate": round(probe_wins / probe_total * 100, 1) if probe_total > 0 else 0,
            "dominant_regime": max(regime_counts, key=regime_counts.get) if regime_counts else regime,
            "what_worked": ". ".join(what_worked),
            "what_failed": ". ".join(what_failed),
        },
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# Adaptation generation
# ---------------------------------------------------------------------------

def _generate_adaptations(review: dict, cycle_number: int,
                          session_id: int) -> list[dict]:
    """Generate and apply bounded behavior adaptations.

    v7.2: ALL adaptations go through discipline_guard.can_adapt().
    Nothing is applied without passing the central guard.
    """
    adaptations = []
    issues = review.get("issues", [])
    profile = db.get_active_profile(session_id)
    if not profile:
        return []

    # Get evidence counts for guard
    evidence = discipline_guard.get_evidence_counts(session_id)
    obs_count = evidence.get("observations", 0)
    out_count = evidence.get("outcomes", 0)

    # Get current regime for stability check
    system = db.get_system_state()
    current_regime = system.get("current_regime", "SLEEPING") if system else "SLEEPING"

    # --- v7.1: Intelligence-driven issue detection ---
    try:
        bstate = db.get_behavior_state(session_id)
        if bstate and bstate.get("market_reward_state") == "punishing_aggression":
            if "defensive_adaptation" not in issues:
                issues.append("defensive_adaptation")
    except Exception:
        pass

    try:
        chronic = memory_engine.get_chronic_blocks(min_misses=5)
        if chronic and "opportunity_sensitivity" not in issues:
            issues.append("opportunity_sensitivity")
    except Exception:
        pass

    # --- Map issues to proposed adaptations ---
    ISSUE_MAP = {
        "overtrading": {
            "param": "overtrade_penalty", "delta": ADAPT_STEP,
            "trigger": "overtrading_detected",
            "reason": review.get("summary", {}).get("what_failed", "High trade frequency"),
            "effect": "Reduce trade frequency, increase conviction requirement",
        },
        "probes_failing": {
            "param": "probe_bias", "delta": -ADAPT_STEP,
            "trigger": "probe_failure_pattern",
            "reason": "Probes failing at high rate",
            "effect": "Reduce probe frequency, require stronger conditions",
        },
        "low_win_rate": {
            "param": "conviction_threshold", "delta": ADAPT_STEP,
            "trigger": "low_win_rate",
            "reason": "Win rate below acceptable threshold",
            "effect": "Require higher conviction before entry",
        },
        "undertrading": {
            "param": "patience", "delta": -ADAPT_STEP,
            "trigger": "undertrading_detected",
            "reason": "System too passive, missing opportunities",
            "effect": "Slightly reduce patience to allow more entries",
        },
        "defensive_adaptation": {
            "param": "patience", "delta": ADAPT_STEP,
            "trigger": "defensive_market_response",
            "reason": "Market punishing aggression — increase patience",
            "effect": "Wait for stronger signals, reduce false entries",
        },
        "opportunity_sensitivity": {
            "param": "conviction_threshold", "delta": -ADAPT_STEP,
            "trigger": "chronic_missed_opportunities",
            "reason": "Chronically blocking profitable trades",
            "effect": "Allow more entries when blocked trades would have succeeded",
        },
    }

    for issue in issues:
        mapping = ISSUE_MAP.get(issue)
        if not mapping:
            continue

        param = mapping["param"]
        old_val = profile.get(param, 0.5)

        # ── v7.2: ASK THE DISCIPLINE GUARD ──
        guard_result = discipline_guard.can_adapt({
            "category": "behavior",
            "target": param,
            "current_value": old_val,
            "proposed_delta": mapping["delta"],
            "current_cycle": cycle_number,
            "session_id": session_id,
            "trigger_reason": mapping["trigger"],
            "evidence_count": obs_count,
            "outcome_count": out_count,
            "regime": current_regime,
        })

        if not guard_result["allowed"]:
            # Blocked — already logged by discipline_guard
            continue

        # ── GUARD APPROVED — apply with clamped delta ──
        new_val = guard_result["final_value"]

        adaptation = {
            "trigger_type": mapping["trigger"],
            "old_behavior": f"{param}={old_val:.4f}",
            "new_behavior": f"{param}={new_val:.4f}",
            "reason": mapping["reason"],
            "expected_effect": mapping["effect"],
            "param": param,
            "new_value": new_val,
        }

        # Apply
        db.upsert_behavior_profile(session_id, **{param: new_val})

        # Log to v7.0 adaptation_events (backward compat)
        db.insert_adaptation(
            session_id=session_id,
            trigger_type=adaptation["trigger_type"],
            old_behavior=adaptation["old_behavior"],
            new_behavior=adaptation["new_behavior"],
            reason=adaptation["reason"],
            expected_effect=adaptation["expected_effect"],
        )

        # Record cooldown in discipline guard
        discipline_guard.record_adaptation_applied("behavior", cycle_number)

        # Update system state
        db.upsert_system_state(
            last_adaptation_at=datetime.now(timezone.utc).isoformat()
        )

        adaptations.append(adaptation)
        print(f"[feedback] APPLIED: {adaptation['trigger_type']} → "
              f"{adaptation['old_behavior']} → {adaptation['new_behavior']}")

    return adaptations


# ---------------------------------------------------------------------------
# Feedback summary for API/UI
# ---------------------------------------------------------------------------

def get_feedback_status() -> dict:
    """Get current feedback loop status for debug/UI."""
    session_id = session_manager.get_session_id()
    recent_adaptations = db.get_recent_adaptations(session_id=session_id, limit=5) if session_id else []
    profile = db.get_active_profile(session_id) if session_id else None

    return {
        "last_review_cycle": _last_review_cycle,
        "review_interval": REVIEW_INTERVAL_CYCLES,
        "next_review_in": max(0, REVIEW_INTERVAL_CYCLES - (session_manager._boot_cycle + _last_review_cycle)),
        "total_adaptations": len(recent_adaptations),
        "recent_adaptations": [
            {
                "trigger": a.get("trigger_type", ""),
                "old": a.get("old_behavior", ""),
                "new": a.get("new_behavior", ""),
                "reason": a.get("reason", ""),
                "status": a.get("validation_status", "pending"),
                "timestamp": a.get("timestamp", ""),
            }
            for a in recent_adaptations
        ],
        "behavior_profile": {
            k: round(profile.get(k, 0.5), 3)
            for k in discipline_guard.PARAM_FLOORS_CEILINGS.keys()
            if k in (profile or {})
        } if profile else {},
        "discipline_guard": discipline_guard.get_discipline_status(
            current_cycle=_last_review_cycle
        ),
    }
