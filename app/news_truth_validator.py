"""
news_truth_validator.py — CryptoMind v7.4 Chunk 3: Truth Validation.

Compares expected bias from classified news against actual market movement
at delayed windows (+5, +20, +100 cycles). Classifies each prediction as:
    correct  — market moved in the expected direction
    wrong    — market moved opposite to expected
    mixed    — partial/ambiguous match
    faded    — initial move was correct but reversed

Observer module — reads from news_event_analysis + cycle_snapshots,
writes ONLY to news_truth_reviews (observer-owned table).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REVIEW_WINDOWS = [5, 20, 100]  # cycle offsets

# Movement thresholds (% price change to count as "moved")
_MOVE_THRESHOLD = 0.15   # 0.15% minimum to count as directional
_STRONG_MOVE    = 0.50   # 0.50% is a strong confirmation
_FADE_THRESHOLD = 0.25   # if reversed by this much, it's a "fade"

# Cache control
_last_check = None
_CHECK_INTERVAL = 120  # seconds between truth validation runs


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Core truth validation
# ---------------------------------------------------------------------------

def _classify_move(expected_bias: str, move_pct: float) -> tuple[str, str, str]:
    """Classify whether the actual move matches the expected bias.

    Returns (verdict, explanation, confidence).
    confidence: 'low', 'medium', 'high'
    verdict:    'correct', 'wrong', 'mixed', 'unclear'
    """
    abs_move = abs(move_pct)

    # Too small to judge — unclear, not mixed
    if abs_move < _MOVE_THRESHOLD:
        return ("unclear",
                f"Market barely moved ({move_pct:+.2f}%) — too small to judge.",
                "low")

    if expected_bias == "neutral":
        if abs_move < _STRONG_MOVE:
            return ("correct",
                    f"Expected neutral, market moved only {move_pct:+.2f}%.",
                    "medium")
        return ("unclear",
                f"Expected neutral but market moved {move_pct:+.2f}% — hard to call.",
                "low")

    # Bullish expectation
    if expected_bias == "bullish":
        if move_pct > 0:
            if move_pct >= _STRONG_MOVE:
                return ("correct",
                        f"Strong bullish confirmation: {move_pct:+.2f}%.",
                        "high")
            return ("correct",
                    f"Bullish call validated: {move_pct:+.2f}%.",
                    "medium")
        else:
            if abs_move >= _STRONG_MOVE:
                return ("wrong",
                        f"Expected bullish but market dropped {move_pct:+.2f}%.",
                        "high")
            # Small counter-move — genuinely unclear
            return ("unclear",
                    f"Expected bullish, slight dip {move_pct:+.2f}% — inconclusive.",
                    "low")

    # Bearish expectation
    if expected_bias == "bearish":
        if move_pct < 0:
            if abs_move >= _STRONG_MOVE:
                return ("correct",
                        f"Strong bearish confirmation: {move_pct:+.2f}%.",
                        "high")
            return ("correct",
                    f"Bearish call validated: {move_pct:+.2f}%.",
                    "medium")
        else:
            if move_pct >= _STRONG_MOVE:
                return ("wrong",
                        f"Expected bearish but market rallied {move_pct:+.2f}%.",
                        "high")
            return ("unclear",
                    f"Expected bearish, slight bounce {move_pct:+.2f}% — inconclusive.",
                    "low")

    return ("unclear",
            f"Unrecognized bias '{expected_bias}', move was {move_pct:+.2f}%.",
            "low")


def _detect_fade(expected_bias: str, early_move_pct: float,
                 late_move_pct: float) -> bool:
    """Detect if the initial move was correct but faded/reversed."""
    if expected_bias == "bullish":
        return early_move_pct > _MOVE_THRESHOLD and late_move_pct < -_FADE_THRESHOLD
    if expected_bias == "bearish":
        return early_move_pct < -_MOVE_THRESHOLD and late_move_pct > _FADE_THRESHOLD
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_reviews_for_news(session_id: int, classified_news: list[dict],
                             current_price: float) -> list[int]:
    """Create pending truth reviews for newly classified interesting/watch news.

    Only creates the +5 window initially. The +20 and +100 windows are
    created later when the shorter window completes (staggered approach).
    Returns list of review_ids created.
    """
    import db

    created = []
    for item in classified_news:
        verdict = item.get("verdict", "noise")
        if verdict not in ("interesting", "watch"):
            continue

        sentiment = item.get("sentiment", "neutral")
        if sentiment == "neutral":
            continue  # no directional expectation to validate

        headline = item.get("headline", "")
        if not headline:
            continue

        analysis_id = item.get("analysis_id")

        # Only create the +5 window now — +20 and +100 are staggered
        try:
            rid = db.insert_truth_review(
                session_id=session_id,
                headline=headline,
                expected_bias=sentiment,
                review_window=5,
                analysis_id=analysis_id,
                price_at_news=current_price,
            )
            created.append(rid)
        except Exception:
            pass

    return created


def _create_next_window(review: dict) -> None:
    """After completing a window, create the next staggered window.

    +5 completed → create +20
    +20 completed → create +100
    """
    import db

    window = review.get("review_window", 0)
    next_window = {5: 20, 20: 100}.get(window)
    if not next_window:
        return

    try:
        db.insert_truth_review(
            session_id=review.get("session_id"),
            headline=review.get("headline", ""),
            expected_bias=review.get("expected_bias", "neutral"),
            review_window=next_window,
            analysis_id=review.get("analysis_id"),
            price_at_news=review.get("price_at_news"),
        )
    except Exception:
        pass


def evaluate_pending_reviews(session_id: int, current_cycle: int,
                              current_price: float) -> list[dict]:
    """Evaluate pending truth reviews that are ready (enough cycles elapsed).

    Returns list of completed reviews.
    """
    global _last_check
    import time
    now = time.time()
    if _last_check and (now - _last_check) < _CHECK_INTERVAL:
        return []
    _last_check = now

    import db

    completed = []

    for window in REVIEW_WINDOWS:
        pending = db.get_pending_truth_reviews(review_window=window)
        if not pending:
            continue

        for review in pending:
            price_at_news = review.get("price_at_news")
            if not price_at_news or price_at_news <= 0:
                continue

            created_at = review.get("created_at", "")
            if not created_at:
                continue

            # Price movement since news
            move_pct = ((current_price - price_at_news) / price_at_news) * 100

            expected_bias = review.get("expected_bias", "neutral")
            verdict, explanation, confidence = _classify_move(expected_bias, move_pct)

            # For longer windows, check for fade pattern
            if window >= 20 and len(completed) > 0:
                earlier = [c for c in completed
                          if c.get("headline") == review.get("headline")
                          and c.get("review_window", 0) < window]
                if earlier:
                    early_move = earlier[0].get("actual_move_pct", 0)
                    if _detect_fade(expected_bias, early_move, move_pct):
                        verdict = "faded"
                        confidence = "medium"
                        explanation = (
                            f"Initial {expected_bias} signal was right ({early_move:+.2f}%) "
                            f"but faded to {move_pct:+.2f}%."
                        )

            try:
                db.complete_truth_review(
                    review_id=review["review_id"],
                    price_at_review=current_price,
                    actual_move_pct=round(move_pct, 4),
                    verdict=verdict,
                    explanation=f"{explanation} [confidence: {confidence}]",
                )
                result = {
                    **review,
                    "price_at_review": current_price,
                    "actual_move_pct": round(move_pct, 4),
                    "verdict": verdict,
                    "explanation": explanation,
                    "confidence": confidence,
                }
                completed.append(result)

                # Stagger: create next window after this one completes
                _create_next_window(review)
            except Exception:
                pass

    return completed


def get_truth_stats() -> dict:
    """Get truth validation statistics for the API."""
    import db
    summary = db.get_truth_review_summary()
    total = summary.get("total", 0) or 0
    pending = summary.get("pending", 0) or 0
    completed = total - pending

    correct = summary.get("correct", 0) or 0
    wrong = summary.get("wrong", 0) or 0

    accuracy = round(correct / max(completed, 1) * 100, 1)

    return {
        "total_reviews": total,
        "pending": pending,
        "completed": completed,
        "correct": correct,
        "wrong": wrong,
        "mixed": summary.get("mixed", 0) or 0,
        "unclear": summary.get("unclear", 0) or 0,
        "faded": summary.get("faded", 0) or 0,
        "accuracy_pct": accuracy,
        "avg_move_pct": round(summary.get("avg_move", 0) or 0, 3),
    }


def get_recent_reviews(session_id: int = None, limit: int = 20) -> list[dict]:
    """Get recent truth reviews for display."""
    import db
    return db.get_truth_reviews(session_id=session_id, limit=limit)
