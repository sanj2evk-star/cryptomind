"""
action_reflection_engine.py — CryptoMind v7.4 Chunk 3: Trade Reflection.

Interprets and grades each trade:
    - Entry timing (was the signal strong? was the regime right?)
    - Size appropriateness (probe vs full entry)
    - Patience impact (did holding/exiting early help or hurt?)
    - Overall grade (A-F based on composite factors)

Observer module — reads from trade_ledger + cycle_snapshots + behavior data,
writes ONLY to action_reflections (observer-owned table).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

# Cache control
_cache = {}
_cache_ts = 0
_CACHE_TTL = 120  # seconds


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Grading logic
# ---------------------------------------------------------------------------

def _grade_entry_timing(trade: dict, snapshot_at_entry: dict | None) -> tuple[str, str]:
    """Grade entry timing based on signal strength and market conditions.

    Returns (grade, reasoning).
    """
    score = trade.get("score", 0) or 0
    confidence = trade.get("confidence", 0) or 0
    regime = trade.get("regime", "SLEEPING")

    # High score + high confidence in active market = good timing
    timing_score = 0

    if score >= 0.7:
        timing_score += 3
    elif score >= 0.5:
        timing_score += 2
    elif score >= 0.3:
        timing_score += 1

    if confidence >= 0.7:
        timing_score += 2
    elif confidence >= 0.5:
        timing_score += 1

    if regime in ("ACTIVE", "BREAKOUT"):
        timing_score += 1  # trading in an active regime is good
    elif regime == "SLEEPING":
        timing_score -= 1  # trading in sleeping regime is risky

    # Check market quality from snapshot
    if snapshot_at_entry:
        mq = snapshot_at_entry.get("market_quality_score", 0) or 0
        if mq >= 60:
            timing_score += 1
        elif mq < 30:
            timing_score -= 1

    if timing_score >= 5:
        return "A", f"Strong signal ({score:.0%}) + high confidence ({confidence:.0%}) in {regime}."
    elif timing_score >= 3:
        return "B", f"Decent timing: score {score:.0%}, confidence {confidence:.0%}."
    elif timing_score >= 1:
        return "C", f"Average timing: score {score:.0%}, some conditions suboptimal."
    elif timing_score >= 0:
        return "D", f"Weak signal ({score:.0%}) or poor conditions for entry."
    else:
        return "F", f"Bad timing: low signal ({score:.0%}) in {regime} regime."


def _grade_size(trade: dict) -> tuple[str, str]:
    """Grade position size appropriateness.

    Returns (grade, reasoning).
    """
    entry_type = trade.get("entry_type", "full")
    confidence = trade.get("confidence", 0) or 0
    score = trade.get("score", 0) or 0

    # Probe entry with low confidence = smart
    if entry_type == "probe" and confidence < 0.6:
        return "A", "Smart probe: small size matched the uncertain signal."

    if entry_type == "probe" and confidence >= 0.7:
        return "C", "Probed despite high confidence — could have been bolder."

    if entry_type == "full" and confidence >= 0.7 and score >= 0.6:
        return "A", "Full entry backed by strong conviction — appropriate size."

    if entry_type == "full" and confidence < 0.5:
        return "D", "Full entry with low confidence — should have probed."

    return "B", f"Reasonable size ({entry_type}) given the conditions."


def _grade_patience(trade: dict, next_snapshots: list[dict]) -> tuple[str, str, str]:
    """Assess whether patience helped or hurt.

    Returns (impact, grade, reasoning).
    impact: 'helped', 'hurt', 'neutral'
    """
    action = trade.get("action", "")
    pnl = trade.get("pnl", 0) or 0

    if action == "BUY":
        # For buys, check if the price moved favorably after entry
        if not next_snapshots:
            return "neutral", "C", "Not enough data after entry to assess patience."

        entry_price = trade.get("price", 0)
        if entry_price <= 0:
            return "neutral", "C", "Missing price data."

        # Check price movement in next few snapshots
        later_prices = [s.get("price", 0) for s in next_snapshots[:5] if s.get("price")]
        if not later_prices:
            return "neutral", "C", "No follow-up price data."

        best_after = max(later_prices)
        worst_after = min(later_prices)
        best_move = ((best_after - entry_price) / max(entry_price, 1)) * 100
        worst_move = ((worst_after - entry_price) / max(entry_price, 1)) * 100

        if best_move > 0.3:
            return "helped", "A", f"Good patience — price rose {best_move:.2f}% after entry."
        elif worst_move < -0.3:
            return "hurt", "D", f"Price dropped {worst_move:.2f}% after entry — bad timing or early buy."
        return "neutral", "B", "Price was relatively stable after entry."

    elif action == "SELL":
        if pnl > 0:
            # Profitable exit — but could we have held longer?
            if not next_snapshots:
                return "neutral", "B", f"Profitable exit (+{pnl:.4f}), no data to assess if early."
            later_prices = [s.get("price", 0) for s in next_snapshots[:10] if s.get("price")]
            sell_price = trade.get("price", 0)
            if later_prices and sell_price > 0:
                best_after = max(later_prices)
                missed = ((best_after - sell_price) / max(sell_price, 1)) * 100
                if missed > 0.5:
                    return "hurt", "C", f"Sold too early — price rose {missed:.2f}% more."
                return "helped", "A", f"Good timing on exit — captured the move."
            return "neutral", "B", f"Profitable exit (+{pnl:.4f})."
        else:
            return "helped", "B", f"Cut losses at {pnl:.4f} — discipline intact."

    return "neutral", "C", "Unrecognized action."


def _overall_grade(timing: str, size: str, patience: str) -> str:
    """Compute overall grade from sub-grades."""
    grade_values = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}
    scores = [
        grade_values.get(timing, 2) * 2,  # timing weighted 2x
        grade_values.get(size, 2),
        grade_values.get(patience, 2),
    ]
    avg = sum(scores) / 4  # total weight = 4

    if avg >= 3.5:
        return "A"
    elif avg >= 2.5:
        return "B"
    elif avg >= 1.5:
        return "C"
    elif avg >= 0.5:
        return "D"
    return "F"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def reflect_on_trade(trade: dict, session_id: int) -> dict:
    """Generate a reflection for a single trade.

    Returns the reflection dict (also persists to DB).
    """
    import db

    trade_id = trade.get("trade_id")
    if not trade_id:
        return {"error": "No trade_id"}

    # Check if already reflected
    existing = db.get_reflection_for_trade(trade_id)
    if existing:
        return existing

    action = trade.get("action", "HOLD")

    # Get snapshot near the trade
    # Use cycle_snapshots near the trade timestamp
    snapshots = db.get_recent_snapshots(session_id, limit=100)
    trade_price = trade.get("price", 0)

    # Find snapshot closest to trade price/time
    snapshot_at_entry = None
    next_snapshots = []
    for i, s in enumerate(reversed(snapshots)):
        if s.get("price") and abs(s["price"] - trade_price) < trade_price * 0.002:
            snapshot_at_entry = s
            next_snapshots = list(reversed(snapshots))[(i+1):(i+11)]
            break

    # Grade components
    timing_grade, timing_reason = _grade_entry_timing(trade, snapshot_at_entry)
    size_grade, size_reason = _grade_size(trade)
    patience_impact, patience_grade, patience_reason = _grade_patience(
        trade, next_snapshots
    )
    overall = _overall_grade(timing_grade, size_grade, patience_grade)

    # Confidence assessment — honest about data gaps
    confidence = "high"
    confidence_notes = []
    if not snapshot_at_entry:
        confidence = "low"
        confidence_notes.append("No matching snapshot found — timing grade is approximate.")
    if not next_snapshots or len(next_snapshots) < 3:
        if confidence == "high":
            confidence = "low"
        confidence_notes.append("Insufficient post-trade data — patience grade is approximate.")
    elif len(next_snapshots) < 5:
        if confidence != "low":
            confidence = "medium"
        confidence_notes.append("Limited post-trade data — patience grade may be incomplete.")

    # Downgrade overall if confidence is low
    if confidence == "low" and overall in ("A", "F"):
        overall = "C"  # refuse to give extreme grades on bad data

    # What went well / could improve
    well_parts = []
    improve_parts = []

    if timing_grade in ("A", "B"):
        well_parts.append(timing_reason)
    else:
        improve_parts.append(timing_reason)

    if size_grade in ("A", "B"):
        well_parts.append(size_reason)
    else:
        improve_parts.append(size_reason)

    if patience_grade in ("A", "B"):
        well_parts.append(patience_reason)
    else:
        improve_parts.append(patience_reason)

    what_went_well = " ".join(well_parts) if well_parts else "No clear strengths in this trade."
    what_could_improve = " ".join(improve_parts) if improve_parts else "No obvious improvements needed."

    reasoning = f"Timing: {timing_grade} — {timing_reason} | Size: {size_grade} — {size_reason} | Patience: {patience_grade} — {patience_reason}"
    if confidence_notes:
        reasoning += f" | ⚠ {' '.join(confidence_notes)}"

    reflection = {
        "trade_id": trade_id,
        "session_id": session_id,
        "action": action,
        "entry_timing_grade": timing_grade,
        "size_grade": size_grade,
        "patience_impact": patience_impact,
        "overall_grade": overall,
        "confidence": confidence,
        "reasoning": reasoning,
        "what_went_well": what_went_well,
        "what_could_improve": what_could_improve,
    }

    # Persist
    try:
        data_json = json.dumps({
            "trade_price": trade_price,
            "trade_score": trade.get("score", 0),
            "trade_confidence": trade.get("confidence", 0),
            "regime": trade.get("regime", ""),
            "strategy": trade.get("strategy", ""),
            "pnl": trade.get("pnl", 0),
        })
        db.insert_action_reflection(
            trade_id=trade_id,
            session_id=session_id,
            action=action,
            entry_timing_grade=timing_grade,
            size_grade=size_grade,
            patience_impact=patience_impact,
            overall_grade=overall,
            reasoning=reasoning,
            what_went_well=what_went_well,
            what_could_improve=what_could_improve,
            data_json=data_json,
        )
    except Exception:
        pass

    return reflection


def reflect_on_recent_trades(session_id: int = None, limit: int = 10) -> list[dict]:
    """Generate reflections for recent un-reflected trades.

    Returns list of reflections.
    """
    global _cache, _cache_ts
    import time
    now = time.time()
    if _cache and (now - _cache_ts) < _CACHE_TTL:
        return list(_cache.values())[:limit]

    import db
    import session_manager

    sid = session_id or session_manager.get_session_id()
    if not sid:
        return []

    trades, _ = db.get_trades(session_id=sid, limit=limit)
    reflections = []

    for trade in trades:
        ref = reflect_on_trade(trade, sid)
        if ref and not ref.get("error"):
            reflections.append(ref)
            _cache[trade.get("trade_id")] = ref

    _cache_ts = now
    return reflections


def get_reflection_stats(session_id: int = None) -> dict:
    """Get reflection grade distribution."""
    import db
    return db.get_reflection_summary(session_id=session_id)
