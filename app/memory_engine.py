"""
memory_engine.py — CryptoMind v7 Experience Memory Engine.

Rule-based system that creates condensed lessons from trading outcomes.
NO fake AI. NO black-box learning. Simple, auditable, real.

Memory types:
- signal_success / signal_failure
- good_exit / bad_exit
- overtrading_penalty
- sleeping_probe_success / sleeping_probe_failure
- trend_follow_success / trend_follow_failure
- mean_revert_success / mean_revert_failure
- missed_move (deferred evaluation)
- churn_detected
- patience_rewarded

Each memory has a pattern_signature (regime + indicators + strategy context)
that allows the system to recognize recurring situations.
"""

from __future__ import annotations

import db
import session_manager

# ---------------------------------------------------------------------------
# Pattern signature builder
# ---------------------------------------------------------------------------

def _build_pattern(regime: str, rsi: float = 0, accel: float = 0,
                   trend: str = "", strategy: str = "",
                   entry_type: str = "", extra: str = "") -> str:
    """Build a human-readable pattern signature.

    Examples:
      - SLEEPING + RSI_oversold + accel_improving
      - WAKING_UP + trend_bullish + EMA_expanding
      - ACTIVE + HUNTER + trend_probe + accel_strong
    """
    parts = [regime]

    if rsi < 35:
        parts.append("RSI_oversold")
    elif rsi > 65:
        parts.append("RSI_overbought")
    elif 45 <= rsi <= 55:
        parts.append("RSI_neutral")

    if accel > 5:
        parts.append("accel_strong")
    elif accel > 0:
        parts.append("accel_improving")
    elif accel < -5:
        parts.append("accel_declining")

    if trend:
        parts.append(f"trend_{trend}")

    if strategy:
        parts.append(strategy)

    if entry_type and entry_type != "full":
        parts.append(entry_type)

    if extra:
        parts.append(extra)

    return " + ".join(parts)


# ---------------------------------------------------------------------------
# Trade evaluation — called after each SELL
# ---------------------------------------------------------------------------

def evaluate_completed_trade(buy_context: dict, sell_context: dict) -> dict | None:
    """Evaluate a completed BUY→SELL pair and generate memory.

    Args:
        buy_context: dict with keys: price, score, confidence, regime, strategy,
                     entry_type, rsi, accel, trend, timestamp
        sell_context: dict with keys: price, pnl, score, regime, rsi, accel, trend

    Returns:
        Memory dict if created, None otherwise.
    """
    session_id = session_manager.get_session_id()
    if not session_id:
        return None

    pnl = sell_context.get("pnl", 0)
    strategy = buy_context.get("strategy", "")
    entry_type = buy_context.get("entry_type", "full")
    regime = buy_context.get("regime", "SLEEPING")
    buy_rsi = buy_context.get("rsi", 50)
    buy_accel = buy_context.get("accel", 0)
    buy_trend = buy_context.get("trend", "sideways")
    buy_score = buy_context.get("score", 50)

    pattern = _build_pattern(
        regime=regime, rsi=buy_rsi, accel=buy_accel,
        trend=buy_trend, strategy=strategy, entry_type=entry_type
    )

    # Determine memory type and lesson
    if pnl > 0:
        # WINNER
        if "probe" in entry_type:
            if "sleeping" in entry_type:
                mem_type = "sleeping_probe_success"
                lesson = (f"Sleeping probe succeeded: {strategy} bought at "
                          f"RSI {buy_rsi:.0f}, accel {buy_accel:.1f}, "
                          f"PnL ${pnl:.6f}")
            elif "trend" in entry_type:
                mem_type = "trend_follow_success"
                lesson = (f"Trend probe worked: {strategy} in {regime}, "
                          f"RSI {buy_rsi:.0f}, accel {buy_accel:.1f}, "
                          f"PnL ${pnl:.6f}")
            else:
                mem_type = "signal_success"
                lesson = (f"Probe entry succeeded: {strategy} in {regime}, "
                          f"score {buy_score:.0f}, PnL ${pnl:.6f}")
        else:
            mem_type = "signal_success"
            lesson = (f"Full entry succeeded: {strategy} in {regime}, "
                      f"score {buy_score:.0f}, RSI {buy_rsi:.0f}, "
                      f"PnL ${pnl:.6f}")

        # Check for good exit quality
        sell_rsi = sell_context.get("rsi", 50)
        if sell_rsi > 60 and pnl > 0:
            # Sold near strength — good exit
            _insert_if_meaningful(session_id, "good_exit", regime, strategy, pattern,
                                 f"Exited near strength (RSI {sell_rsi:.0f}), captured PnL ${pnl:.6f}",
                                 confidence_weight=0.6, outcome=pnl)
    else:
        # LOSER
        if "probe" in entry_type:
            if "sleeping" in entry_type:
                mem_type = "sleeping_probe_failure"
                lesson = (f"Sleeping probe failed: {strategy} bought at "
                          f"RSI {buy_rsi:.0f}, accel {buy_accel:.1f}, "
                          f"loss ${pnl:.6f}")
            elif "trend" in entry_type:
                mem_type = "trend_follow_failure"
                lesson = (f"Trend probe failed: {strategy} in {regime}, "
                          f"RSI {buy_rsi:.0f}, accel {buy_accel:.1f}, "
                          f"loss ${pnl:.6f}")
            else:
                mem_type = "signal_failure"
                lesson = (f"Probe entry failed: {strategy} in {regime}, "
                          f"score {buy_score:.0f}, loss ${pnl:.6f}")
        else:
            mem_type = "signal_failure"
            lesson = (f"Full entry failed: {strategy} in {regime}, "
                      f"score {buy_score:.0f}, RSI {buy_rsi:.0f}, "
                      f"loss ${pnl:.6f}")

        # Check for bad exit
        sell_rsi = sell_context.get("rsi", 50)
        if sell_rsi < 40 and pnl < 0:
            _insert_if_meaningful(session_id, "bad_exit", regime, strategy, pattern,
                                 f"Sold in weakness (RSI {sell_rsi:.0f}), loss ${pnl:.6f}",
                                 confidence_weight=0.4, outcome=pnl)

    # Store the main memory
    _insert_if_meaningful(session_id, mem_type, regime, strategy, pattern,
                          lesson, confidence_weight=0.5, outcome=pnl)

    return {"memory_type": mem_type, "pattern": pattern, "lesson": lesson, "pnl": pnl}


# ---------------------------------------------------------------------------
# Missed move evaluation — deferred check
# ---------------------------------------------------------------------------

# Pending evaluations: {cycle_number: {price_at_block, regime, strategy, reason, score}}
_pending_missed: list[dict] = []


def record_blocked_trade(cycle: int, price: float, score: float,
                         regime: str, strategy: str, reason: str) -> None:
    """Record a blocked trade for later missed-move evaluation."""
    _pending_missed.append({
        "cycle": cycle,
        "price": price,
        "score": score,
        "regime": regime,
        "strategy": strategy,
        "reason": reason,
    })
    # Keep only last 50
    if len(_pending_missed) > 50:
        _pending_missed[:] = _pending_missed[-50:]


def evaluate_missed_moves(current_price: float, current_cycle: int) -> list[dict]:
    """Check if any blocked trades would have been profitable.

    Called periodically (e.g., every 10 cycles). Checks trades blocked
    5+ cycles ago and evaluates if price moved favorably.
    """
    session_id = session_manager.get_session_id()
    if not session_id:
        return []

    results = []
    remaining = []

    for pending in _pending_missed:
        cycles_ago = current_cycle - pending["cycle"]
        if cycles_ago < 5:
            remaining.append(pending)
            continue

        # Evaluate: would a BUY have been profitable?
        price_change_pct = (current_price - pending["price"]) / pending["price"] * 100
        if price_change_pct > 0.3:
            # Missed a move — market went up >0.3%
            pattern = _build_pattern(
                regime=pending["regime"], strategy=pending["strategy"],
                extra=f"blocked_{pending['reason'][:20]}"
            )
            lesson = (f"Missed move: blocked {pending['strategy']} BUY at "
                      f"${pending['price']:,.0f} (score {pending['score']:.0f}), "
                      f"price rose {price_change_pct:.1f}% to ${current_price:,.0f}")
            _insert_if_meaningful(
                session_id, "missed_move", pending["regime"],
                pending["strategy"], pattern, lesson,
                confidence_weight=0.4, outcome=price_change_pct
            )
            results.append({"type": "missed_move", "pattern": pattern,
                            "price_change_pct": price_change_pct})
        # Either evaluated or too old — don't keep
        if cycles_ago > 30:
            continue
        remaining.append(pending)

    _pending_missed[:] = remaining
    return results


# ---------------------------------------------------------------------------
# Pattern analysis — detect repeated failures/successes
# ---------------------------------------------------------------------------

def analyze_strategy_patterns(strategy: str, session_id: int = None) -> dict:
    """Analyze success/failure patterns for a strategy.

    Returns dict with strongest and weakest patterns.
    """
    if not session_id:
        session_id = session_manager.get_session_id()
    if not session_id:
        return {}

    memories = db.get_active_memories(strategy=strategy, limit=100)
    if not memories:
        return {"strategy": strategy, "patterns": [], "strongest": None, "weakest": None}

    # Group by pattern
    pattern_stats: dict[str, dict] = {}
    for m in memories:
        pat = m.get("pattern_signature", "unknown")
        if pat not in pattern_stats:
            pattern_stats[pat] = {"successes": 0, "failures": 0, "total_outcome": 0, "count": 0}
        stats = pattern_stats[pat]
        stats["count"] += m.get("times_observed", 1)
        stats["total_outcome"] += m.get("average_outcome", 0) * m.get("times_observed", 1)
        if "success" in m.get("memory_type", ""):
            stats["successes"] += m.get("times_observed", 1)
        elif "failure" in m.get("memory_type", ""):
            stats["failures"] += m.get("times_observed", 1)

    # Rank patterns
    patterns = []
    for pat, stats in pattern_stats.items():
        total = stats["successes"] + stats["failures"]
        win_rate = stats["successes"] / total * 100 if total > 0 else 50
        avg = stats["total_outcome"] / stats["count"] if stats["count"] > 0 else 0
        patterns.append({
            "pattern": pat, "win_rate": round(win_rate, 1),
            "avg_outcome": round(avg, 6), "observations": stats["count"],
        })

    patterns.sort(key=lambda x: x["avg_outcome"], reverse=True)

    return {
        "strategy": strategy,
        "patterns": patterns[:10],
        "strongest": patterns[0] if patterns else None,
        "weakest": patterns[-1] if patterns else None,
    }


# ---------------------------------------------------------------------------
# Churn detection
# ---------------------------------------------------------------------------

def detect_churn(strategy: str, recent_trades: list[dict], session_id: int = None) -> bool:
    """Detect if a strategy is churning (many trades, no net gain).

    Returns True if churn detected and memory was created.
    """
    if not session_id:
        session_id = session_manager.get_session_id()
    if not session_id or len(recent_trades) < 4:
        return False

    # Look at last 10 trades
    trades = recent_trades[-10:]
    total_pnl = sum(t.get("pnl", 0) for t in trades if isinstance(t.get("pnl"), (int, float)))
    trade_count = len(trades)

    if trade_count >= 4 and abs(total_pnl) < 0.001:
        pattern = _build_pattern(
            regime=trades[-1].get("regime", "SLEEPING") if isinstance(trades[-1], dict) else "SLEEPING",
            strategy=strategy, extra="churn"
        )
        lesson = (f"Churn detected: {strategy} made {trade_count} trades "
                  f"with net PnL ${total_pnl:.6f} — consider reducing activity")
        _insert_if_meaningful(session_id, "churn_detected", "", strategy, pattern,
                              lesson, confidence_weight=0.6, outcome=total_pnl)
        return True
    return False


# ---------------------------------------------------------------------------
# Memory summary for UI
# ---------------------------------------------------------------------------

def get_memory_summary() -> dict:
    """Get a summary of the experience memory system for UI display."""
    session_id = session_manager.get_session_id()
    total = db.get_memory_count()
    recent = db.get_active_memories(limit=5)
    latest = recent[0] if recent else None

    # Count by type
    all_memories = db.get_active_memories(limit=500)
    type_counts: dict[str, int] = {}
    for m in all_memories:
        mt = m.get("memory_type", "unknown")
        type_counts[mt] = type_counts.get(mt, 0) + 1

    successes = sum(v for k, v in type_counts.items() if "success" in k)
    failures = sum(v for k, v in type_counts.items() if "failure" in k)

    return {
        "total_memories": total,
        "latest_memory": {
            "type": latest.get("memory_type", ""),
            "lesson": latest.get("lesson_text", ""),
            "pattern": latest.get("pattern_signature", ""),
            "times_observed": latest.get("times_observed", 0),
            "timestamp": latest.get("timestamp", ""),
        } if latest else None,
        "type_breakdown": type_counts,
        "total_successes": successes,
        "total_failures": failures,
        "recent_memories": [
            {
                "type": m.get("memory_type", ""),
                "lesson": m.get("lesson_text", ""),
                "strategy": m.get("strategy", ""),
                "times_observed": m.get("times_observed", 0),
                "confidence": m.get("confidence_weight", 0),
            }
            for m in recent
        ],
    }


def get_strategy_lesson(strategy: str) -> str | None:
    """Get the most relevant active lesson for a strategy. For leaderboard display."""
    memories = db.get_active_memories(strategy=strategy, limit=3)
    if not memories:
        return None
    # Pick the most observed memory
    best = max(memories, key=lambda m: m.get("times_observed", 0))
    return best.get("lesson_text", "")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _insert_if_meaningful(session_id: int, mem_type: str, regime: str,
                          strategy: str, pattern: str, lesson: str,
                          confidence_weight: float = 0.5, outcome: float = 0.0) -> None:
    """Insert memory only if session is active."""
    try:
        db.insert_memory(
            session_id=session_id,
            memory_type=mem_type,
            lesson_text=lesson,
            regime=regime,
            strategy=strategy,
            pattern_signature=pattern,
            confidence_weight=confidence_weight,
            average_outcome=outcome,
        )
    except Exception as e:
        print(f"[memory] Failed to insert memory: {e}")
