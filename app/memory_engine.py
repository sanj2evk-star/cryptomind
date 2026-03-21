"""
memory_engine.py — CryptoMind v7.1 Experience Memory Engine.

Rule-based system that creates condensed lessons from trading outcomes.
NO fake AI. NO black-box learning. Simple, auditable, real.

Memory types:
- signal_success / signal_failure
- good_exit / bad_exit
- overtrading_penalty
- sleeping_probe_success / sleeping_probe_failure
- trend_follow_success / trend_follow_failure
- mean_revert_success / mean_revert_failure
- missed_move (deferred evaluation — now DB-backed with multi-checkpoint)
- churn_detected
- patience_rewarded
- delayed_correct / delayed_wrong / delayed_neutral (v7.1 outcome engine)
- chronic_block (v7.1 — strategy/regime chronically missing opportunities)

v7.1: Missed opportunity tracking is now persistent (SQLite-backed).
      Multi-checkpoint evaluation at +5 and +20 cycles.
      Severity classification: minor (<0.3%), moderate (0.3-1%), major (>1%).

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
# Missed move evaluation — v7.1: DB-backed with multi-checkpoint
# ---------------------------------------------------------------------------

# Severity thresholds
MISSED_MINOR_PCT = 0.3      # >0.3% move = minor miss
MISSED_MODERATE_PCT = 0.5   # >0.5% = moderate
MISSED_MAJOR_PCT = 1.0      # >1.0% = major


def record_blocked_trade(cycle: int, price: float, score: float,
                         regime: str, strategy: str, reason: str) -> int | None:
    """Record a blocked trade for later missed-move evaluation.

    v7.1: Now persisted to SQLite instead of in-memory list.
    Returns missed_id.
    """
    session_id = session_manager.get_session_id()
    if not session_id:
        return None

    try:
        return db.insert_missed_opportunity(
            session_id=session_id,
            cycle_recorded=cycle,
            price_at_record=price,
            score_at_record=score,
            regime=regime,
            strategy=strategy,
            block_reason=reason,
        )
    except Exception as e:
        print(f"[memory] Failed to record blocked trade: {e}")
        return None


def evaluate_missed_moves(current_price: float, current_cycle: int) -> list[dict]:
    """Evaluate blocked trades at +5 and +20 cycle checkpoints.

    v7.1: Multi-checkpoint evaluation with severity classification.
    Called every 10 cycles.
    """
    session_id = session_manager.get_session_id()
    if not session_id:
        return []

    results = []

    # Evaluate at +5 cycles
    pending_5 = db.get_pending_missed(checkpoint=5, current_cycle=current_cycle)
    for missed in pending_5:
        price_at_record = missed["price_at_record"]
        move_pct = (current_price - price_at_record) / price_at_record * 100

        # Classify severity
        was_missed = move_pct > MISSED_MINOR_PCT
        if move_pct > MISSED_MAJOR_PCT:
            severity = "major"
        elif move_pct > MISSED_MODERATE_PCT:
            severity = "moderate"
        elif move_pct > MISSED_MINOR_PCT:
            severity = "minor"
        else:
            severity = None

        db.update_missed_evaluation(
            missed_id=missed["missed_id"],
            checkpoint=5,
            price=current_price,
            move_pct=round(move_pct, 4),
            was_missed=was_missed,
            severity=severity,
        )

        if was_missed and severity in ("moderate", "major"):
            pattern = _build_pattern(
                regime=missed["regime"], strategy=missed["strategy"],
                extra=f"blocked_{missed['block_reason'][:20]}"
            )
            lesson = (f"Missed move ({severity}): blocked {missed['strategy']} BUY at "
                      f"${price_at_record:,.0f} (score {missed['score_at_record']:.0f}), "
                      f"price rose {move_pct:.1f}% to ${current_price:,.0f} in 5 cycles")
            _insert_if_meaningful(
                session_id, "missed_move", missed["regime"],
                missed["strategy"], pattern, lesson,
                confidence_weight=0.4, outcome=move_pct
            )
            results.append({"type": "missed_move", "severity": severity,
                            "pattern": pattern, "move_pct": round(move_pct, 2)})

    # Evaluate at +20 cycles
    pending_20 = db.get_pending_missed(checkpoint=20, current_cycle=current_cycle)
    for missed in pending_20:
        price_at_record = missed["price_at_record"]
        move_pct = (current_price - price_at_record) / price_at_record * 100

        was_missed = move_pct > MISSED_MODERATE_PCT
        if move_pct > MISSED_MAJOR_PCT:
            severity = "major"
        elif move_pct > MISSED_MODERATE_PCT:
            severity = "moderate"
        else:
            severity = None

        db.update_missed_evaluation(
            missed_id=missed["missed_id"],
            checkpoint=20,
            price=current_price,
            move_pct=round(move_pct, 4),
            was_missed=was_missed,
            severity=severity,
        )

        # Only generate memory for major misses at +20 (moderate already logged at +5)
        if was_missed and severity == "major" and not missed.get("was_missed"):
            pattern = _build_pattern(
                regime=missed["regime"], strategy=missed["strategy"],
                extra=f"blocked_{missed['block_reason'][:20]}"
            )
            lesson = (f"Major missed move: blocked {missed['strategy']} BUY at "
                      f"${price_at_record:,.0f}, price rose {move_pct:.1f}% "
                      f"over 20 cycles. Filters may be too strict.")
            _insert_if_meaningful(
                session_id, "missed_move", missed["regime"],
                missed["strategy"], pattern, lesson,
                confidence_weight=0.6, outcome=move_pct
            )
            results.append({"type": "missed_move_20c", "severity": "major",
                            "move_pct": round(move_pct, 2)})

    return results


def get_chronic_blocks(min_misses: int = 3) -> list[dict]:
    """Detect strategies/regimes that chronically miss opportunities.

    Returns patterns like "HUNTER blocked in WAKING_UP missed 5 moves avg 0.7%".
    """
    summary = db.get_missed_opportunity_summary()
    chronic = []

    for strat_info in summary.get("by_strategy", []):
        missed_count = strat_info.get("missed", 0)
        if missed_count >= min_misses:
            chronic.append({
                "strategy": strat_info.get("strategy", ""),
                "total_blocks": strat_info.get("cnt", 0),
                "confirmed_misses": missed_count,
                "issue": f"{strat_info['strategy']} chronically blocked — "
                         f"{missed_count} confirmed missed opportunities",
            })

    return chronic


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
