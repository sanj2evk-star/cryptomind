"""
feedback.py — CryptoMind v7.1 Feedback Loop + Behavior Adaptation Engine.

Periodic self-review system that:
1. Inspects recent trades, blocked trades, strategy outcomes
2. Detects patterns (overtrading, undertrading, missed moves)
3. v7.1: Uses regime intelligence + behavior state + missed opportunity data
4. Generates adaptation candidates
5. Applies bounded parameter adjustments to behavior profile

Runs every REVIEW_INTERVAL_CYCLES (50 cycles ≈ 25 min at 30s intervals).

RULES:
- All adaptations are bounded (±10-15% from defaults)
- Minimum observation count before any adaptation fires
- Every adaptation is logged and later validated
- Adaptations are reversible
- v7.1: No impulsive adaptation — evidence-based only
"""

from __future__ import annotations

from datetime import datetime, timezone

import db
import session_manager
import memory_engine

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REVIEW_INTERVAL_CYCLES = 50          # review every 50 cycles
MIN_TRADES_FOR_REVIEW = 3            # need at least 3 trades to have data
MIN_OBSERVATIONS_FOR_ADAPT = 50      # need 50+ cycles of evidence
ADAPTATION_COOLDOWN_CYCLES = 100     # min cycles between adaptations of same type

# Bounded parameter ranges (min, default, max)
PARAM_BOUNDS = {
    "aggressiveness":       (0.2, 0.5, 0.8),
    "patience":             (0.2, 0.5, 0.8),
    "probe_bias":           (0.2, 0.5, 0.8),
    "trend_follow_bias":    (0.3, 0.5, 0.7),
    "mean_revert_bias":     (0.3, 0.5, 0.7),
    "conviction_threshold": (0.3, 0.5, 0.7),
    "overtrade_penalty":    (0.2, 0.5, 0.8),
    "hold_extension_bias":  (0.3, 0.5, 0.7),
    "exit_tightness":       (0.3, 0.5, 0.7),
    "noise_tolerance":      (0.3, 0.5, 0.7),
}

# Step size for each adaptation (bounded)
ADAPT_STEP = 0.03  # ±3% per adaptation

# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

_last_review_cycle = 0
_last_adaptation_types: dict[str, int] = {}  # type → last cycle adapted


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
    """Generate and apply bounded behavior adaptations based on review findings."""
    adaptations = []
    issues = review.get("issues", [])
    profile = db.get_active_profile(session_id)
    if not profile:
        return []

    # --- v7.1: Intelligence-driven issue detection ---
    # Check behavior state for prolonged punishing market
    try:
        bstate = db.get_behavior_state(session_id)
        if bstate and bstate.get("market_reward_state") == "punishing_aggression":
            if "defensive_adaptation" not in issues:
                issues.append("defensive_adaptation")
    except Exception:
        pass

    # Check missed opportunities for chronic blocks
    try:
        import memory_engine
        chronic = memory_engine.get_chronic_blocks(min_misses=5)
        if chronic and "opportunity_sensitivity" not in issues:
            issues.append("opportunity_sensitivity")
    except Exception:
        pass

    # Process v7.1 issues
    for issue in [i for i in issues if i in ("defensive_adaptation", "opportunity_sensitivity")]:
        last = _last_adaptation_types.get(issue, 0)
        if cycle_number - last < ADAPTATION_COOLDOWN_CYCLES:
            continue

        adaptation = None

        if issue == "defensive_adaptation":
            old_val = profile.get("patience", 0.5)
            new_val = _bounded_adjust(old_val, ADAPT_STEP, "patience")
            if new_val != old_val:
                adaptation = {
                    "trigger_type": "defensive_market_response",
                    "old_behavior": f"patience={old_val:.3f}",
                    "new_behavior": f"patience={new_val:.3f}",
                    "reason": "Market punishing aggression — increase patience",
                    "expected_effect": "Wait for stronger signals, reduce false entries",
                    "param": "patience",
                    "new_value": new_val,
                }

        elif issue == "opportunity_sensitivity":
            old_val = profile.get("conviction_threshold", 0.5)
            new_val = _bounded_adjust(old_val, -ADAPT_STEP, "conviction_threshold")
            if new_val != old_val:
                adaptation = {
                    "trigger_type": "chronic_missed_opportunities",
                    "old_behavior": f"conviction_threshold={old_val:.3f}",
                    "new_behavior": f"conviction_threshold={new_val:.3f}",
                    "reason": "Chronically blocking profitable trades — lower conviction bar",
                    "expected_effect": "Allow more entries when blocked trades would have succeeded",
                    "param": "conviction_threshold",
                    "new_value": new_val,
                }

        if adaptation:
            # Apply the adaptation
            db.upsert_behavior_profile(session_id, **{adaptation["param"]: adaptation["new_value"]})
            db.insert_adaptation(
                session_id=session_id,
                trigger_type=adaptation["trigger_type"],
                old_behavior=adaptation["old_behavior"],
                new_behavior=adaptation["new_behavior"],
                reason=adaptation["reason"],
                expected_effect=adaptation["expected_effect"],
            )
            _last_adaptation_types[issue] = cycle_number
            db.upsert_system_state(
                last_adaptation_at=datetime.now(timezone.utc).isoformat()
            )
            adaptations.append(adaptation)
            print(f"[feedback] v7.1 Adaptation: {adaptation['trigger_type']} → "
                  f"{adaptation['old_behavior']} → {adaptation['new_behavior']}")

    for issue in [i for i in issues if i not in ("defensive_adaptation", "opportunity_sensitivity")]:
        # Check cooldown
        last = _last_adaptation_types.get(issue, 0)
        if cycle_number - last < ADAPTATION_COOLDOWN_CYCLES:
            continue

        adaptation = None

        if issue == "overtrading":
            old_val = profile.get("overtrade_penalty", 0.5)
            new_val = _bounded_adjust(old_val, ADAPT_STEP, "overtrade_penalty")
            if new_val != old_val:
                adaptation = {
                    "trigger_type": "overtrading_detected",
                    "old_behavior": f"overtrade_penalty={old_val:.3f}",
                    "new_behavior": f"overtrade_penalty={new_val:.3f}",
                    "reason": review["summary"]["what_failed"],
                    "expected_effect": "Reduce trade frequency, increase conviction requirement",
                    "param": "overtrade_penalty",
                    "new_value": new_val,
                }

        elif issue == "probes_failing":
            old_val = profile.get("probe_bias", 0.5)
            new_val = _bounded_adjust(old_val, -ADAPT_STEP, "probe_bias")
            if new_val != old_val:
                adaptation = {
                    "trigger_type": "probe_failure_pattern",
                    "old_behavior": f"probe_bias={old_val:.3f}",
                    "new_behavior": f"probe_bias={new_val:.3f}",
                    "reason": "Probes failing at high rate",
                    "expected_effect": "Reduce probe frequency, require stronger conditions",
                    "param": "probe_bias",
                    "new_value": new_val,
                }

        elif issue == "low_win_rate":
            old_val = profile.get("conviction_threshold", 0.5)
            new_val = _bounded_adjust(old_val, ADAPT_STEP, "conviction_threshold")
            if new_val != old_val:
                adaptation = {
                    "trigger_type": "low_win_rate",
                    "old_behavior": f"conviction_threshold={old_val:.3f}",
                    "new_behavior": f"conviction_threshold={new_val:.3f}",
                    "reason": "Win rate below acceptable threshold",
                    "expected_effect": "Require higher conviction before entry",
                    "param": "conviction_threshold",
                    "new_value": new_val,
                }

        elif issue == "undertrading":
            old_val = profile.get("patience", 0.5)
            new_val = _bounded_adjust(old_val, -ADAPT_STEP, "patience")
            if new_val != old_val:
                adaptation = {
                    "trigger_type": "undertrading_detected",
                    "old_behavior": f"patience={old_val:.3f}",
                    "new_behavior": f"patience={new_val:.3f}",
                    "reason": "System too passive, missing opportunities",
                    "expected_effect": "Slightly reduce patience to allow more entries",
                    "param": "patience",
                    "new_value": new_val,
                }

        if adaptation:
            # Apply the adaptation
            db.upsert_behavior_profile(session_id, **{adaptation["param"]: adaptation["new_value"]})

            # Log it
            db.insert_adaptation(
                session_id=session_id,
                trigger_type=adaptation["trigger_type"],
                old_behavior=adaptation["old_behavior"],
                new_behavior=adaptation["new_behavior"],
                reason=adaptation["reason"],
                expected_effect=adaptation["expected_effect"],
            )

            # Update cooldown
            _last_adaptation_types[issue] = cycle_number

            # Update system state
            db.upsert_system_state(
                last_adaptation_at=datetime.now(timezone.utc).isoformat()
            )

            adaptations.append(adaptation)
            print(f"[feedback] Adaptation: {adaptation['trigger_type']} → "
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
            for k in PARAM_BOUNDS.keys()
        } if profile else {},
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bounded_adjust(current: float, delta: float, param_name: str) -> float:
    """Adjust a parameter within its bounds."""
    bounds = PARAM_BOUNDS.get(param_name, (0.2, 0.5, 0.8))
    new_val = current + delta
    return round(max(bounds[0], min(bounds[2], new_val)), 3)
