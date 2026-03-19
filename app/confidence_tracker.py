"""
confidence_tracker.py — Track AI decision accuracy over time.

Stores every BUY/SELL/HOLD decision with confidence score,
then evaluates outcome after a delay to measure accuracy.

Detects overconfidence: high confidence but wrong prediction.
"""

from __future__ import annotations
import time
from datetime import datetime, timezone

# Config
EVAL_DELAY_SECONDS = 600   # 10 minutes
MAX_HISTORY = 500          # keep last 500 decisions

# State
_decisions: list[dict] = []
_evaluated: list[dict] = []
_metrics = {
    "total_evaluated": 0,
    "correct": 0,
    "incorrect": 0,
    "accuracy_pct": 0.0,
    "high_conf_total": 0,
    "high_conf_correct": 0,
    "high_conf_accuracy_pct": 0.0,
    "low_conf_total": 0,
    "low_conf_correct": 0,
    "low_conf_accuracy_pct": 0.0,
    "overconfidence_count": 0,
    "overconfidence_pct": 0.0,
}


def record_decision(action: str, confidence: float, score: float, price: float):
    """Record a new AI decision for later evaluation."""
    if not action or price <= 0:
        return

    _decisions.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "unix_ts": time.time(),
        "action": action.upper(),
        "confidence": round(confidence, 4),
        "score": round(score, 2),
        "price_at_decision": round(price, 2),
        "evaluated": False,
        "result": None,
        "price_at_eval": None,
        "price_change_pct": None,
    })

    # Trim old decisions
    if len(_decisions) > MAX_HISTORY:
        _decisions[:] = _decisions[-MAX_HISTORY:]


def evaluate_pending(current_price: float):
    """Check pending decisions that are old enough to evaluate."""
    if current_price <= 0:
        return

    now = time.time()

    for d in _decisions:
        if d["evaluated"]:
            continue
        if now - d["unix_ts"] < EVAL_DELAY_SECONDS:
            continue  # too soon

        # Evaluate
        d["evaluated"] = True
        d["price_at_eval"] = round(current_price, 2)
        entry_price = d["price_at_decision"]
        change_pct = ((current_price - entry_price) / entry_price) * 100
        d["price_change_pct"] = round(change_pct, 4)

        action = d["action"]
        if action == "BUY":
            d["result"] = "correct" if change_pct > 0 else "incorrect"
        elif action == "SELL":
            d["result"] = "correct" if change_pct < 0 else "incorrect"
        elif action == "HOLD":
            # HOLD is correct if price didn't move much (<0.3%)
            d["result"] = "correct" if abs(change_pct) < 0.3 else "neutral"
        else:
            d["result"] = "neutral"

        _evaluated.append(d)

    # Trim evaluated list
    if len(_evaluated) > MAX_HISTORY:
        _evaluated[:] = _evaluated[-MAX_HISTORY:]

    # Recalculate metrics
    _recalculate_metrics()


def _recalculate_metrics():
    """Recalculate accuracy metrics from evaluated decisions."""
    global _metrics

    scored = [d for d in _evaluated if d["result"] in ("correct", "incorrect")]
    total = len(scored)

    if total == 0:
        _metrics = {k: 0 if isinstance(v, int) else 0.0 for k, v in _metrics.items()}
        return

    correct = sum(1 for d in scored if d["result"] == "correct")
    incorrect = total - correct

    # High confidence (>60%)
    high_conf = [d for d in scored if d["confidence"] > 0.6]
    high_correct = sum(1 for d in high_conf if d["result"] == "correct")

    # Low confidence (<40%)
    low_conf = [d for d in scored if d["confidence"] < 0.4]
    low_correct = sum(1 for d in low_conf if d["result"] == "correct")

    # Overconfidence: high confidence but wrong
    overconfident = sum(1 for d in high_conf if d["result"] == "incorrect")

    _metrics = {
        "total_evaluated": total,
        "correct": correct,
        "incorrect": incorrect,
        "accuracy_pct": round((correct / total) * 100, 1) if total > 0 else 0.0,
        "high_conf_total": len(high_conf),
        "high_conf_correct": high_correct,
        "high_conf_accuracy_pct": round((high_correct / len(high_conf)) * 100, 1) if high_conf else 0.0,
        "low_conf_total": len(low_conf),
        "low_conf_correct": low_correct,
        "low_conf_accuracy_pct": round((low_correct / len(low_conf)) * 100, 1) if low_conf else 0.0,
        "overconfidence_count": overconfident,
        "overconfidence_pct": round((overconfident / len(high_conf)) * 100, 1) if high_conf else 0.0,
    }


def get_metrics() -> dict:
    """Return current accuracy metrics."""
    return {
        **_metrics,
        "pending_evaluations": sum(1 for d in _decisions if not d["evaluated"]),
        "recent_decisions": len(_decisions),
    }


def get_recent_evaluated(limit: int = 20) -> list[dict]:
    """Return recently evaluated decisions (newest first)."""
    return _evaluated[-limit:][::-1]
