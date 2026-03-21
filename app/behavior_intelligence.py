"""
behavior_intelligence.py — CryptoMind v7.1 Behavior Intelligence Layer.

Introduces two dynamic internal states:

A. market_reward_state — How is the market rewarding us?
   - rewarding_aggression: wins come from aggressive entries
   - punishing_aggression: losses from aggressive entries
   - rewarding_patience: wins from patient entries, misses from impatience
   - noisy_unpredictable: no clear pattern

B. system_self_state — How well is the system performing?
   - in_sync: reading market well, decisions align with outcomes
   - out_of_sync: low accuracy, confusion, signals wrong
   - learning: not enough data yet
   - recovering: was out_of_sync, starting to improve

These states produce bounded, reversible modifiers:
   - aggression_modifier    [-0.2, +0.2]
   - patience_modifier      [-0.2, +0.2]
   - threshold_modifier     [-5.0, +5.0]  (applied to buy/sell thresholds)
   - exposure_modifier      [-0.1, +0.1]  (applied to exposure caps)

All changes are evidence-based. No impulsive adaptation.
"""

from __future__ import annotations

from datetime import datetime, timezone

import db
import session_manager
import discipline_guard

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MIN_TRADES_FOR_STATE = 5            # need 5+ recent trades to compute state
LOOKBACK_TRADES = 20                # analyze last 20 trades
MIN_OUTCOMES_FOR_CALIBRATION = 10   # need 10+ delayed outcomes for calibration

# State transition thresholds
HIGH_WIN_RATE = 0.55
LOW_WIN_RATE = 0.40
POSITIVE_PNL_THRESHOLD = 0.0
NEGATIVE_PNL_THRESHOLD = -0.001

# Modifier bounds
MODIFIER_BOUNDS = {
    "aggression_modifier":  (-0.2, 0.2),
    "patience_modifier":    (-0.2, 0.2),
    "threshold_modifier":   (-5.0, 5.0),
    "exposure_modifier":    (-0.1, 0.1),
}

# State → modifier mapping
STATE_MODIFIERS = {
    # (market_reward, system_self) → modifiers
    ("rewarding_aggression", "in_sync"): {
        "aggression_modifier": 0.1,
        "patience_modifier": -0.05,
        "threshold_modifier": -2.0,
        "exposure_modifier": 0.05,
    },
    ("rewarding_aggression", "learning"): {
        "aggression_modifier": 0.05,
        "patience_modifier": 0.0,
        "threshold_modifier": -1.0,
        "exposure_modifier": 0.02,
    },
    ("rewarding_patience", "in_sync"): {
        "aggression_modifier": -0.05,
        "patience_modifier": 0.1,
        "threshold_modifier": 1.0,
        "exposure_modifier": 0.0,
    },
    ("rewarding_patience", "learning"): {
        "aggression_modifier": 0.0,
        "patience_modifier": 0.05,
        "threshold_modifier": 0.5,
        "exposure_modifier": 0.0,
    },
    ("punishing_aggression", "out_of_sync"): {
        "aggression_modifier": -0.15,
        "patience_modifier": 0.1,
        "threshold_modifier": 3.0,
        "exposure_modifier": -0.05,
    },
    ("punishing_aggression", "recovering"): {
        "aggression_modifier": -0.1,
        "patience_modifier": 0.05,
        "threshold_modifier": 2.0,
        "exposure_modifier": -0.03,
    },
    ("noisy_unpredictable", "out_of_sync"): {
        "aggression_modifier": -0.1,
        "patience_modifier": 0.1,
        "threshold_modifier": 3.0,
        "exposure_modifier": -0.05,
    },
    ("noisy_unpredictable", "learning"): {
        "aggression_modifier": 0.0,
        "patience_modifier": 0.0,
        "threshold_modifier": 0.0,
        "exposure_modifier": 0.0,
    },
}

# Default neutral modifiers
_NEUTRAL_MODIFIERS = {
    "aggression_modifier": 0.0,
    "patience_modifier": 0.0,
    "threshold_modifier": 0.0,
    "exposure_modifier": 0.0,
}


# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

_cached_modifiers: dict = dict(_NEUTRAL_MODIFIERS)
_last_update_cycle: int = 0


# ---------------------------------------------------------------------------
# Update behavior state — called every 10 cycles
# ---------------------------------------------------------------------------

def update_behavior_state(session_id: int, current_cycle: int) -> dict:
    """Recompute market_reward_state and system_self_state.

    Analyzes recent trades and delayed outcomes to determine states,
    then computes bounded modifiers.

    Returns the updated state dict.
    """
    global _cached_modifiers, _last_update_cycle

    if not session_id:
        return {}

    _last_update_cycle = current_cycle

    # --- Gather recent trade data ---
    trades, _ = db.get_trades(session_id=session_id, limit=LOOKBACK_TRADES)
    sells = [t for t in trades if t.get("action") == "SELL"]

    # v7.2: Apply recency weights to trades
    sells = discipline_guard.apply_recency_weights(sells, current_cycle)

    if len(sells) < MIN_TRADES_FOR_STATE:
        # Not enough data — stay in learning mode
        state = {
            "market_reward_state": "noisy_unpredictable",
            "reward_score": 0.0,
            "reward_trend": "flat",
            "recent_win_rate": 0.5,
            "recent_avg_pnl": 0.0,
            "system_self_state": "learning",
            "self_score": 0.0,
            "calibration_quality": 0.5,
            "cycle_number": current_cycle,
            **_NEUTRAL_MODIFIERS,
            "notes": f"Insufficient data ({len(sells)} sells < {MIN_TRADES_FOR_STATE})",
        }
        try:
            db.upsert_behavior_state(session_id, **state)
        except Exception as e:
            print(f"[behavior_intel] DB error: {e}")
        return state

    # --- Compute market reward state (v7.2: recency-weighted) ---
    weighted_wins = sum(t.get("recency_weight", 1.0) for t in sells if (t.get("pnl") or 0) > 0)
    weighted_total = sum(t.get("recency_weight", 1.0) for t in sells)
    total = len(sells)
    win_rate = weighted_wins / weighted_total if weighted_total > 0 else 0.5
    weighted_pnl = sum(t.get("pnl", 0) * t.get("recency_weight", 1.0) for t in sells)
    avg_pnl = weighted_pnl / weighted_total if weighted_total > 0 else 0

    # Check if aggressive entries are being rewarded
    probe_sells = [t for t in sells if "probe" in t.get("entry_type", "")]
    full_sells = [t for t in sells if t.get("entry_type", "full") == "full"]
    probe_pnl = sum(t.get("pnl", 0) for t in probe_sells) if probe_sells else 0
    full_pnl = sum(t.get("pnl", 0) for t in full_sells) if full_sells else 0

    # Reward score: -1.0 (punishing) to +1.0 (rewarding)
    reward_score = min(1.0, max(-1.0, (win_rate - 0.5) * 4))

    # Determine market reward state
    if win_rate >= HIGH_WIN_RATE and avg_pnl > POSITIVE_PNL_THRESHOLD:
        if full_pnl > probe_pnl:
            market_reward = "rewarding_aggression"
        else:
            market_reward = "rewarding_patience"
    elif win_rate <= LOW_WIN_RATE or avg_pnl < NEGATIVE_PNL_THRESHOLD:
        market_reward = "punishing_aggression"
    else:
        market_reward = "noisy_unpredictable"

    # Reward trend: compare first half vs second half
    mid = len(sells) // 2
    if mid > 0:
        first_half_wr = sum(1 for t in sells[:mid] if (t.get("pnl") or 0) > 0) / mid
        second_half_wr = sum(1 for t in sells[mid:] if (t.get("pnl") or 0) > 0) / (len(sells) - mid)
        if second_half_wr > first_half_wr + 0.1:
            reward_trend = "improving"
        elif second_half_wr < first_half_wr - 0.1:
            reward_trend = "declining"
        else:
            reward_trend = "flat"
    else:
        reward_trend = "flat"

    # --- Compute system self state ---
    # Check calibration from delayed outcomes
    calibration = _compute_calibration(session_id)
    self_score = (win_rate - 0.5) * 2  # -1.0 to +1.0

    # Determine self state
    prev_state = db.get_behavior_state(session_id)
    prev_self = prev_state.get("system_self_state", "learning") if prev_state else "learning"

    if calibration >= 0.6 and win_rate >= HIGH_WIN_RATE:
        system_self = "in_sync"
    elif calibration < 0.4 or win_rate < LOW_WIN_RATE:
        if prev_self == "out_of_sync" and win_rate > LOW_WIN_RATE:
            system_self = "recovering"
        else:
            system_self = "out_of_sync"
    elif prev_self == "out_of_sync":
        system_self = "recovering"
    else:
        system_self = "learning"

    # --- Compute modifiers from state pair ---
    key = (market_reward, system_self)
    raw_modifiers = STATE_MODIFIERS.get(key, _NEUTRAL_MODIFIERS).copy()

    # v7.2: Run each modifier through discipline guard
    evidence = discipline_guard.get_evidence_counts(session_id)
    obs_count = evidence.get("observations", 0)
    out_count = evidence.get("outcomes", 0)

    modifiers = {}
    for param, proposed in raw_modifiers.items():
        current = 0.0  # modifiers always start from 0
        guard_result = discipline_guard.can_adapt({
            "category": "modifier",
            "target": param,
            "current_value": current,
            "proposed_delta": proposed,
            "current_cycle": current_cycle,
            "session_id": session_id,
            "trigger_reason": f"behavior_state:{market_reward}/{system_self}",
            "evidence_count": obs_count,
            "outcome_count": out_count,
            "regime": "",
        })

        if guard_result["allowed"]:
            modifiers[param] = guard_result["final_value"]
            discipline_guard.record_adaptation_applied("modifier", current_cycle)
        else:
            modifiers[param] = 0.0  # blocked → stay neutral

    _cached_modifiers = modifiers

    # --- Build notes ---
    notes = (
        f"mkt={market_reward}, self={system_self}, "
        f"wr={win_rate:.0%}, avg_pnl={avg_pnl:.6f}, "
        f"calib={calibration:.2f}, trend={reward_trend}"
    )

    # --- Persist ---
    state = {
        "market_reward_state": market_reward,
        "reward_score": round(reward_score, 3),
        "reward_trend": reward_trend,
        "recent_win_rate": round(win_rate, 3),
        "recent_avg_pnl": round(avg_pnl, 6),
        "system_self_state": system_self,
        "self_score": round(self_score, 3),
        "calibration_quality": round(calibration, 3),
        "cycle_number": current_cycle,
        **modifiers,
        "notes": notes,
    }

    try:
        db.upsert_behavior_state(session_id, **state)
    except Exception as e:
        print(f"[behavior_intel] DB error: {e}")

    print(f"[behavior_intel] State: {market_reward}/{system_self} "
          f"(wr={win_rate:.0%}, thr_mod={modifiers['threshold_modifier']:+.1f})")

    return state


def _compute_calibration(session_id: int) -> float:
    """Compute calibration quality from delayed outcome evaluations.

    Calibration = how often the system's entries are validated by time.
    Returns 0.0 (terrible) to 1.0 (perfect).
    """
    summary = db.get_outcome_summary()
    completed = summary.get("completed") or 0
    if completed < MIN_OUTCOMES_FOR_CALIBRATION:
        return 0.5  # neutral — not enough data

    correct = summary.get("correct") or 0
    return min(1.0, correct / completed) if completed > 0 else 0.5


# ---------------------------------------------------------------------------
# Query modifiers — used by multi_strategy
# ---------------------------------------------------------------------------

def get_behavior_modifiers(session_id: int = None) -> dict:
    """Get current behavior modifiers for trading logic.

    Returns dict with threshold_modifier, aggression_modifier, etc.
    Falls back to cached values if DB unavailable.
    """
    if session_id:
        try:
            state = db.get_behavior_state(session_id)
            if state:
                return {
                    "aggression_modifier": state.get("aggression_modifier", 0),
                    "patience_modifier": state.get("patience_modifier", 0),
                    "threshold_modifier": state.get("threshold_modifier", 0),
                    "exposure_modifier": state.get("exposure_modifier", 0),
                    "market_reward_state": state.get("market_reward_state", "neutral"),
                    "system_self_state": state.get("system_self_state", "learning"),
                }
        except Exception:
            pass

    return dict(_cached_modifiers)


# ---------------------------------------------------------------------------
# API summary
# ---------------------------------------------------------------------------

def get_behavior_state_summary() -> dict:
    """Full behavior state for API/UI display."""
    sid = session_manager.get_session_id()
    if not sid:
        return {"state": "no_session"}

    state = db.get_behavior_state(sid)
    if not state:
        return {"state": "not_initialized"}

    return {
        "market_reward_state": state.get("market_reward_state", "neutral"),
        "reward_score": round(state.get("reward_score", 0), 3),
        "reward_trend": state.get("reward_trend", "flat"),
        "recent_win_rate": round(state.get("recent_win_rate", 0.5) * 100, 1),
        "recent_avg_pnl": round(state.get("recent_avg_pnl", 0), 6),
        "system_self_state": state.get("system_self_state", "learning"),
        "self_score": round(state.get("self_score", 0), 3),
        "calibration_quality": round(state.get("calibration_quality", 0.5) * 100, 1),
        "modifiers": {
            "aggression": state.get("aggression_modifier", 0),
            "patience": state.get("patience_modifier", 0),
            "threshold": state.get("threshold_modifier", 0),
            "exposure": state.get("exposure_modifier", 0),
        },
        "cycle_number": state.get("cycle_number", 0),
        "notes": state.get("notes", ""),
    }
