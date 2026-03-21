"""
outcome_engine.py — CryptoMind v7.1 Delayed Outcome Evaluation Engine.

Every BUY decision is evaluated at 3 future checkpoints:
  +5 cycles   (short-term — ~2.5 min at 30s intervals)
  +20 cycles  (mid-term   — ~10 min)
  +100 cycles (long-term  — ~50 min)

Each checkpoint captures:
  - price movement %
  - max favorable excursion (MFE)
  - max adverse excursion (MAE)
  - directional correctness verdict

Final verdict = majority of 3 checkpoints.
Lessons are generated ONLY after all 3 are evaluated.

NO instant learning. Learning is based on delayed truth.
"""

from __future__ import annotations

from datetime import datetime, timezone

import db
import session_manager

# ---------------------------------------------------------------------------
# Price tracking for MFE/MAE calculation
# ---------------------------------------------------------------------------

# {outcome_id: {"entry_price": float, "high": float, "low": float}}
_price_extremes: dict[int, dict] = {}
_MAX_TRACKED = 200  # max active outcomes to track


# ---------------------------------------------------------------------------
# Registration — called on every BUY
# ---------------------------------------------------------------------------

def register_outcome(trade_id: int, price: float, cycle: int,
                     strategy: str = "", regime: str = "",
                     entry_type: str = "full", score: float = 0.0,
                     confidence: float = 0.0,
                     pattern_signature: str = "") -> int | None:
    """Register a new BUY for delayed outcome evaluation.

    Returns outcome_id, or None if no session.
    """
    sid = session_manager.get_session_id()
    if not sid:
        return None

    outcome_id = db.insert_experience_outcome(
        session_id=sid,
        trade_id=trade_id,
        action="BUY",
        entry_price=price,
        entry_cycle=cycle,
        strategy=strategy,
        regime=regime,
        entry_type=entry_type,
        entry_score=score,
        entry_confidence=confidence,
        pattern_signature=pattern_signature,
    )

    # Start tracking price extremes for MFE/MAE
    _price_extremes[outcome_id] = {
        "entry_price": price,
        "high": price,
        "low": price,
    }

    # Trim tracked outcomes if too many
    if len(_price_extremes) > _MAX_TRACKED:
        oldest = sorted(_price_extremes.keys())[:50]
        for k in oldest:
            _price_extremes.pop(k, None)

    return outcome_id


# ---------------------------------------------------------------------------
# Checkpoint evaluation — called every cycle
# ---------------------------------------------------------------------------

CHECKPOINTS = [5, 20, 100]

# Verdict thresholds
GOOD_THRESHOLD = 0.3    # +0.3% = good entry
BAD_THRESHOLD = -0.3    # -0.3% = bad entry


def evaluate_checkpoints(current_price: float, current_cycle: int) -> dict:
    """Evaluate all pending outcome checkpoints.

    Called every cycle. Returns summary of evaluations performed.
    """
    # Update price extremes for all tracked outcomes
    for oid, extremes in _price_extremes.items():
        if current_price > extremes["high"]:
            extremes["high"] = current_price
        if current_price < extremes["low"]:
            extremes["low"] = current_price

    results = {"evaluated": 0, "verdicts_set": 0, "lessons_generated": 0}

    for cp in CHECKPOINTS:
        pending = db.get_pending_outcomes_at(cp, current_cycle)
        for outcome in pending:
            oid = outcome["outcome_id"]
            entry_price = outcome["entry_price"]

            # Calculate PnL %
            pnl_pct = (current_price - entry_price) / entry_price * 100

            # Calculate MFE/MAE from tracked extremes
            extremes = _price_extremes.get(oid, {
                "entry_price": entry_price,
                "high": max(current_price, entry_price),
                "low": min(current_price, entry_price),
            })
            mfe = (extremes["high"] - entry_price) / entry_price * 100
            mae = (extremes["low"] - entry_price) / entry_price * 100

            # Determine verdict
            if pnl_pct >= GOOD_THRESHOLD:
                verdict = "correct"
            elif pnl_pct <= BAD_THRESHOLD:
                verdict = "wrong"
            else:
                verdict = "neutral"

            db.update_outcome_checkpoint(
                outcome_id=oid,
                checkpoint=cp,
                price=round(current_price, 2),
                pnl_pct=round(pnl_pct, 4),
                mfe=round(mfe, 4),
                mae=round(mae, 4),
                verdict=verdict,
            )
            results["evaluated"] += 1

            # If this was the last checkpoint (+100), clean up tracking
            if cp == 100:
                _price_extremes.pop(oid, None)

    # Process final verdicts
    needs_verdict = db.get_outcomes_needing_final_verdict()
    for outcome in needs_verdict:
        final = _compute_final_verdict(outcome)
        db.set_outcome_final_verdict(outcome["outcome_id"], final)
        results["verdicts_set"] += 1

    # Generate lessons from completed evaluations
    needs_lessons = db.get_outcomes_needing_lessons()
    for outcome in needs_lessons:
        _generate_lesson(outcome)
        results["lessons_generated"] += 1

    return results


def _compute_final_verdict(outcome: dict) -> str:
    """Compute final verdict from 3 checkpoint verdicts.

    Majority vote: if 2 of 3 say correct → correct.
    If mixed → neutral. If 2 of 3 say wrong → wrong.
    """
    verdicts = [
        outcome.get("verdict_at_5", "neutral"),
        outcome.get("verdict_at_20", "neutral"),
        outcome.get("verdict_at_100", "neutral"),
    ]
    correct_count = verdicts.count("correct")
    wrong_count = verdicts.count("wrong")

    if correct_count >= 2:
        return "correct"
    elif wrong_count >= 2:
        return "wrong"
    else:
        return "neutral"


def _generate_lesson(outcome: dict) -> None:
    """Generate an experience memory lesson from a completed outcome evaluation."""
    sid = session_manager.get_session_id()
    if not sid:
        return

    verdict = outcome.get("final_verdict", "neutral")
    strategy = outcome.get("strategy", "unknown")
    regime = outcome.get("regime", "SLEEPING")
    pattern = outcome.get("pattern_signature", "")
    entry_price = outcome.get("entry_price", 0)

    # Build lesson text from delayed evaluation
    pnl_5 = outcome.get("pnl_pct_at_5", 0) or 0
    pnl_20 = outcome.get("pnl_pct_at_20", 0) or 0
    pnl_100 = outcome.get("pnl_pct_at_100", 0) or 0
    mfe_100 = outcome.get("mfe_at_100", 0) or 0
    mae_100 = outcome.get("mae_at_100", 0) or 0

    if verdict == "correct":
        mem_type = "delayed_correct"
        lesson = (
            f"Delayed evaluation CORRECT: {strategy} BUY at ${entry_price:,.0f} in {regime}. "
            f"+5c: {pnl_5:+.2f}%, +20c: {pnl_20:+.2f}%, +100c: {pnl_100:+.2f}%. "
            f"MFE: {mfe_100:+.2f}%, MAE: {mae_100:.2f}%."
        )
        confidence = 0.7
    elif verdict == "wrong":
        mem_type = "delayed_wrong"
        lesson = (
            f"Delayed evaluation WRONG: {strategy} BUY at ${entry_price:,.0f} in {regime}. "
            f"+5c: {pnl_5:+.2f}%, +20c: {pnl_20:+.2f}%, +100c: {pnl_100:+.2f}%. "
            f"MFE: {mfe_100:+.2f}%, MAE: {mae_100:.2f}%. Entry was not validated by time."
        )
        confidence = 0.6
    else:
        mem_type = "delayed_neutral"
        lesson = (
            f"Delayed evaluation NEUTRAL: {strategy} BUY at ${entry_price:,.0f} in {regime}. "
            f"+5c: {pnl_5:+.2f}%, +20c: {pnl_20:+.2f}%, +100c: {pnl_100:+.2f}%. "
            f"Inconclusive — entry neither clearly good nor bad."
        )
        confidence = 0.4

    try:
        db.insert_memory(
            session_id=sid,
            memory_type=mem_type,
            lesson_text=lesson,
            regime=regime,
            strategy=strategy,
            pattern_signature=pattern,
            confidence_weight=confidence,
            average_outcome=pnl_100,
        )
        db.mark_outcome_lesson_generated(outcome["outcome_id"])
    except Exception as e:
        print(f"[outcome_engine] Lesson generation error: {e}")


# ---------------------------------------------------------------------------
# API / Summary
# ---------------------------------------------------------------------------

def get_outcome_summary() -> dict:
    """Get outcome evaluation summary for API."""
    return db.get_outcome_summary()
