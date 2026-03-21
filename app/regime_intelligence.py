"""
regime_intelligence.py — CryptoMind v7.1 Regime Intelligence Memory.

Aggregates strategy performance per market regime to learn:
  "In THIS regime → THIS behavior works."

Tracks wins/losses/PnL per regime-strategy pair.
Periodically computes recommendations: prefer / avoid / neutral.
Feeds into multi_strategy score modifiers.

All updates are incremental. No data is ever deleted.
"""

from __future__ import annotations

import db
import session_manager
import discipline_guard

# ---------------------------------------------------------------------------
# Configuration — v7.2: minimums sourced from discipline_guard
# ---------------------------------------------------------------------------

MIN_TRADES_FOR_RECOMMENDATION = discipline_guard.MIN_TRADES_REGIME_REC  # 10 trades
PREFER_WIN_RATE = 60.0                  # >60% win rate + positive PnL → prefer
AVOID_WIN_RATE = 35.0                   # <35% win rate OR negative avg PnL → avoid
STRONG_CONFIDENCE_TRADES = 15           # 15+ trades → high confidence

# Score modifiers applied to multi_strategy buy thresholds
PREFER_THRESHOLD_BONUS = -3             # lower buy bar for preferred
AVOID_THRESHOLD_PENALTY = 3             # raise buy bar for underperformer


# ---------------------------------------------------------------------------
# Record a completed trade into regime profile
# ---------------------------------------------------------------------------

def record_trade_for_regime(session_id: int, regime: str, strategy: str,
                             pnl: float, entry_type: str = "full",
                             hold_cycles: float = 0) -> None:
    """Called after each SELL. Updates the regime-strategy profile."""
    if not session_id or not regime or not strategy:
        return

    is_win = pnl > 0
    try:
        db.upsert_regime_profile(
            session_id=session_id,
            regime=regime,
            strategy=strategy,
            pnl=pnl,
            is_win=is_win,
            hold_cycles=hold_cycles,
            entry_type=entry_type,
        )
    except Exception as e:
        print(f"[regime_intel] Record error: {e}")


# ---------------------------------------------------------------------------
# Compute recommendations — called periodically (every 50 cycles)
# ---------------------------------------------------------------------------

def compute_regime_recommendations(session_id: int) -> dict:
    """Recompute recommendations for all regime-strategy pairs.

    Returns summary of recommendations applied.
    """
    if not session_id:
        return {"computed": 0}

    profiles = db.get_regime_profiles(session_id=session_id)
    computed = 0

    # v7.2: Get outcome counts for guard
    evidence = discipline_guard.get_evidence_counts(session_id)
    out_count = evidence.get("outcomes", 0)

    for p in profiles:
        trades = p.get("total_trades", 0)
        if trades < MIN_TRADES_FOR_RECOMMENDATION:
            continue

        win_rate = p.get("win_rate", 50)
        avg_pnl = p.get("avg_pnl", 0)

        # Determine recommendation
        if win_rate >= PREFER_WIN_RATE and avg_pnl > 0:
            action = "prefer"
        elif win_rate <= AVOID_WIN_RATE or (avg_pnl < 0 and trades >= 5):
            action = "avoid"
        else:
            action = "neutral"

        # v7.2: Ask discipline guard before applying non-neutral recommendations
        if action != "neutral":
            guard_result = discipline_guard.can_adapt({
                "category": "regime",
                "target": f"regime_rec:{p['regime']}:{p['strategy']}",
                "current_value": 0.5,
                "proposed_delta": 0.3 if action == "prefer" else -0.3,
                "current_cycle": 0,  # regime recs don't use cycle cooldown
                "session_id": session_id,
                "trigger_reason": f"regime_performance:{action}",
                "evidence_count": trades,
                "outcome_count": out_count,
                "regime": p["regime"],
            })
            if not guard_result["allowed"]:
                action = "neutral"  # blocked → stay neutral

        # Confidence based on observation count
        if trades >= STRONG_CONFIDENCE_TRADES:
            confidence = 0.8
        elif trades >= 10:
            confidence = 0.6
        else:
            confidence = 0.4

        try:
            db.update_regime_recommendation(
                session_id=session_id,
                regime=p["regime"],
                strategy=p["strategy"],
                confidence=confidence,
                action=action,
            )
            computed += 1
        except Exception as e:
            print(f"[regime_intel] Recommendation update error: {e}")

    if computed:
        print(f"[regime_intel] Updated {computed} regime-strategy recommendations")

    return {"computed": computed}


# ---------------------------------------------------------------------------
# Query recommendations — used by multi_strategy
# ---------------------------------------------------------------------------

def get_strategy_recommendation(regime: str, strategy: str) -> str:
    """Get recommendation for a strategy in the current regime.

    Returns 'prefer', 'avoid', or 'neutral'.
    """
    sid = session_manager.get_session_id()
    if not sid:
        return "neutral"
    try:
        return db.get_strategy_recommendation(sid, regime, strategy)
    except Exception:
        return "neutral"


def get_best_strategies_for_regime(regime: str) -> list[dict]:
    """Get strategies ordered by performance in a regime."""
    sid = session_manager.get_session_id()
    if not sid:
        return []
    try:
        profiles = db.get_regime_profiles(session_id=sid, regime=regime)
        # Sort by win_rate then avg_pnl
        profiles.sort(key=lambda p: (p.get("win_rate", 0), p.get("avg_pnl", 0)), reverse=True)
        return profiles
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Intelligence summary for API
# ---------------------------------------------------------------------------

def get_regime_intelligence_summary() -> dict:
    """Full regime intelligence matrix for API/UI."""
    sid = session_manager.get_session_id()
    if not sid:
        return {"profiles": [], "recommendations": {}}

    profiles = db.get_regime_profiles(session_id=sid)

    # Build regime → strategy matrix
    matrix: dict[str, list[dict]] = {}
    recommendations: dict[str, dict] = {}

    for p in profiles:
        regime = p.get("regime", "SLEEPING")
        if regime not in matrix:
            matrix[regime] = []

        strategy_data = {
            "strategy": p.get("strategy", ""),
            "total_trades": p.get("total_trades", 0),
            "win_rate": round(p.get("win_rate", 0), 1),
            "avg_pnl": round(p.get("avg_pnl", 0), 6),
            "total_pnl": round(p.get("total_pnl", 0), 6),
            "confidence": round(p.get("confidence_score", 0.5), 2),
            "recommendation": p.get("recommended_action", "neutral"),
        }
        matrix[regime].append(strategy_data)

        # Track best per regime
        key = regime
        if key not in recommendations or strategy_data["win_rate"] > recommendations[key].get("win_rate", 0):
            recommendations[key] = strategy_data

    return {
        "matrix": matrix,
        "best_per_regime": recommendations,
        "total_profiles": len(profiles),
    }
