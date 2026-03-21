"""
crowd_sentiment_engine.py — CryptoMind v7.5 Observer: Crowd Sentiment Layer.

Observes what the crowd believes vs what the market is actually doing.
Detects agreement, divergence, and narrative strength.

Inputs (currently synthetic/mock — designed for future Polymarket/prediction
market integration):
    - crowd_probability: how confident the crowd is in a direction
    - crowd_bias: bullish / bearish / neutral
    - price_trend: up / down / flat (from actual BTC price)

Outputs:
    - alignment: aligned / diverging / unclear
    - divergence_score: 0–100
    - one-liner insight for the feed

Observer-only module — NEVER triggers trades.
"""

from __future__ import annotations

import time
import random
import threading
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_CACHE_TTL = 45  # seconds
_lock = threading.Lock()
_cache: dict | None = None
_cache_ts: float = 0

# ---------------------------------------------------------------------------
# Synthetic crowd data generator (placeholder for real APIs)
#
# Designed so a real integration just replaces _fetch_crowd_data()
# with actual Polymarket / prediction market calls.
# ---------------------------------------------------------------------------

def _fetch_crowd_data() -> dict:
    """Fetch current crowd sentiment.

    TODO: Replace with real Polymarket / prediction market API.
    Currently generates synthetic data based on recent news sentiment
    from the bullshit_radar, providing a realistic approximation.
    """
    try:
        import bullshit_radar
        radar = bullshit_radar.get_radar()
        heat = radar.get("crowd_heat", "balanced")
        distortion = radar.get("narrative_distortion", 0)
        bullish_count = radar.get("bullish_count", 0)
        bearish_count = radar.get("bearish_count", 0)
        total = max(bullish_count + bearish_count, 1)

        # Derive crowd probability from news sentiment balance
        bull_ratio = bullish_count / total
        if heat in ("heavily_bullish", "leaning_bullish"):
            bias = "bullish"
            probability = 0.5 + (bull_ratio * 0.35) + (distortion * 0.15)
        elif heat in ("heavily_bearish", "leaning_bearish"):
            bias = "bearish"
            probability = 0.5 + ((1 - bull_ratio) * 0.35) + (distortion * 0.15)
        else:
            bias = "neutral"
            probability = 0.45 + (distortion * 0.1)

        # Clamp
        probability = max(0.15, min(0.95, probability))

        # Confidence strength: how sure the crowd is (0–1)
        confidence = abs(probability - 0.5) * 2  # 0 at 50%, 1 at 0% or 100%

        return {
            "source": "internal_sentiment",
            "question": "Will BTC go up in the next 24h?",
            "crowd_probability": round(probability, 3),
            "bias": bias,
            "confidence_strength": round(confidence, 3),
            "bullish_count": bullish_count,
            "bearish_count": bearish_count,
            "distortion": round(distortion, 3),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        return {
            "source": "internal_sentiment",
            "question": "Will BTC go up in the next 24h?",
            "crowd_probability": 0.5,
            "bias": "neutral",
            "confidence_strength": 0.0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


def _get_price_trend() -> dict:
    """Determine recent BTC price trend from cycle snapshots."""
    try:
        import db
        import session_manager
        sid = session_manager.get_session_id()
        if not sid:
            return {"trend": "flat", "change_pct": 0.0, "current_price": 0}

        snapshots = db.get_recent_snapshots(sid, limit=20)
        if not snapshots or len(snapshots) < 2:
            return {"trend": "flat", "change_pct": 0.0, "current_price": 0}

        prices = [s.get("price", 0) for s in snapshots if s.get("price")]
        if len(prices) < 2:
            return {"trend": "flat", "change_pct": 0.0, "current_price": 0}

        current = prices[0]   # most recent (DESC order)
        older = prices[-1]    # oldest in window

        if older <= 0:
            return {"trend": "flat", "change_pct": 0.0, "current_price": current}

        change_pct = ((current - older) / older) * 100

        if change_pct > 0.15:
            trend = "up"
        elif change_pct < -0.15:
            trend = "down"
        else:
            trend = "flat"

        return {
            "trend": trend,
            "change_pct": round(change_pct, 3),
            "current_price": current,
        }
    except Exception:
        return {"trend": "flat", "change_pct": 0.0, "current_price": 0}


# ---------------------------------------------------------------------------
# Alignment + Divergence computation
# ---------------------------------------------------------------------------

def _compute_alignment(crowd_bias: str, crowd_confidence: float,
                       price_trend: str, price_change_pct: float) -> dict:
    """Compute alignment between crowd belief and market reality.

    Returns alignment (aligned/diverging/unclear) and divergence_score (0–100).
    """
    # Weak crowd signal → unclear
    if crowd_confidence < 0.15:
        return {
            "alignment": "unclear",
            "divergence_score": 20,
            "reason": "Crowd signal too weak to judge.",
        }

    # Flat / indecisive price → unclear
    if price_trend == "flat" and abs(price_change_pct) < 0.1:
        return {
            "alignment": "unclear",
            "divergence_score": 30,
            "reason": "Price barely moving — too early to call.",
        }

    # Neutral crowd → unclear
    if crowd_bias == "neutral":
        return {
            "alignment": "unclear",
            "divergence_score": 25,
            "reason": "Crowd has no strong lean.",
        }

    # ── Aligned checks ──
    if crowd_bias == "bullish" and price_trend == "up":
        strength = min(100, int(crowd_confidence * 50 + abs(price_change_pct) * 30))
        return {
            "alignment": "aligned",
            "divergence_score": max(0, 100 - strength),
            "reason": "Crowd bullish and price confirming.",
        }

    if crowd_bias == "bearish" and price_trend == "down":
        strength = min(100, int(crowd_confidence * 50 + abs(price_change_pct) * 30))
        return {
            "alignment": "aligned",
            "divergence_score": max(0, 100 - strength),
            "reason": "Crowd bearish and price confirming.",
        }

    # ── Diverging checks ──
    if crowd_bias == "bullish" and price_trend == "down":
        div = min(100, int(30 + crowd_confidence * 40 + abs(price_change_pct) * 20))
        return {
            "alignment": "diverging",
            "divergence_score": div,
            "reason": "Crowd leaning bullish, but price not confirming.",
        }

    if crowd_bias == "bearish" and price_trend == "up":
        div = min(100, int(30 + crowd_confidence * 40 + abs(price_change_pct) * 20))
        return {
            "alignment": "diverging",
            "divergence_score": div,
            "reason": "Crowd leaning bearish, but price is rising.",
        }

    # Mild divergence: crowd directional but price flat
    if crowd_bias in ("bullish", "bearish") and price_trend == "flat":
        return {
            "alignment": "diverging",
            "divergence_score": min(55, int(20 + crowd_confidence * 35)),
            "reason": f"Crowd leaning {crowd_bias}, but price is flat.",
        }

    return {
        "alignment": "unclear",
        "divergence_score": 30,
        "reason": "Mixed signals — can't determine alignment.",
    }


# ---------------------------------------------------------------------------
# One-liner insights
# ---------------------------------------------------------------------------

_INSIGHTS = {
    ("aligned", "bullish"):  [
        "Belief and reality aligned — bullish trend looks stable.",
        "Crowd is optimistic and price agrees. Momentum intact.",
        "Strong alignment between price and sentiment.",
    ],
    ("aligned", "bearish"):  [
        "Crowd expects weakness and price is following.",
        "Bearish consensus confirmed by price action.",
        "Belief and reality aligned — both pointing down.",
    ],
    ("diverging", "bullish"): [
        "Crowd is optimistic, price is not convinced.",
        "Narrative looks strong, but follow-through is weak.",
        "Strong narrative, weak follow-through.",
        "Crowd leaning bullish, but price not confirming.",
    ],
    ("diverging", "bearish"): [
        "Crowd leaning one way, market moving the other.",
        "Bearish narrative, but price refuses to drop.",
        "Crowd expects pain but market disagrees.",
    ],
    ("unclear", "neutral"): [
        "Too early to trust the crowd.",
        "No strong conviction from either side.",
        "Waiting for a clearer signal.",
    ],
    ("unclear", "bullish"): [
        "Crowd is mildly optimistic — not enough to call it.",
        "Weak bullish lean, price undecided.",
    ],
    ("unclear", "bearish"): [
        "Mild bearish lean, but nothing definitive.",
        "Crowd slightly negative — watching for confirmation.",
    ],
    ("diverging", "neutral"): [
        "Mixed signals — crowd and price tell different stories.",
        "Can't determine clear alignment right now.",
    ],
}


def _pick_insight(alignment: str, bias: str) -> str:
    """Pick a one-liner insight."""
    key = (alignment, bias)
    options = _INSIGHTS.get(key, _INSIGHTS.get(("unclear", "neutral"), []))
    if not options:
        return "Watching for crowd signals."
    # Rotate based on time to avoid repetition
    idx = int(time.time() / 120) % len(options)
    return options[idx]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute() -> dict:
    """Compute crowd sentiment vs reality snapshot.

    Returns full state dict with crowd_bias, crowd_strength, price_trend,
    alignment, divergence_score, and insight.
    """
    global _cache, _cache_ts

    now = time.time()
    if _cache and (now - _cache_ts) < _CACHE_TTL:
        return _cache

    crowd = _fetch_crowd_data()
    price_info = _get_price_trend()

    bias = crowd.get("bias", "neutral")
    confidence = crowd.get("confidence_strength", 0)
    probability = crowd.get("crowd_probability", 0.5)
    trend = price_info.get("trend", "flat")
    change_pct = price_info.get("change_pct", 0)

    align = _compute_alignment(bias, confidence, trend, change_pct)

    insight = _pick_insight(align["alignment"], bias)

    result = {
        # Crowd side
        "crowd_bias": bias,
        "crowd_probability": round(probability * 100, 1),  # as percentage
        "crowd_strength": round(confidence * 100, 1),       # as percentage
        "source": crowd.get("source", "internal_sentiment"),
        "question": crowd.get("question", ""),

        # Price side
        "price_trend": trend,
        "price_change_pct": change_pct,
        "current_price": price_info.get("current_price", 0),

        # Alignment
        "alignment": align["alignment"],
        "divergence_score": align["divergence_score"],
        "alignment_reason": align["reason"],

        # Insight
        "insight": insight,

        # Meta
        "warming_up": crowd.get("confidence_strength", 0) < 0.05,
        "data_source": "synthetic",  # will become "polymarket" etc.
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    with _lock:
        _cache = result
        _cache_ts = now

    return result


def get_latest() -> dict:
    """Get the latest crowd sentiment snapshot."""
    return compute()


def get_belief_vs_reality() -> dict:
    """Get the belief vs reality comparison."""
    snap = compute()
    return {
        "crowd": {
            "bias": snap["crowd_bias"],
            "probability": snap["crowd_probability"],
            "strength": snap["crowd_strength"],
        },
        "reality": {
            "price_trend": snap["price_trend"],
            "price_change_pct": snap["price_change_pct"],
            "current_price": snap["current_price"],
        },
        "comparison": {
            "alignment": snap["alignment"],
            "divergence_score": snap["divergence_score"],
            "reason": snap["alignment_reason"],
            "insight": snap["insight"],
        },
        "warming_up": snap["warming_up"],
        "data_source": snap["data_source"],
        "timestamp": snap["timestamp"],
    }


# ---------------------------------------------------------------------------
# Feed integration — generates mind feed items when divergence is notable
# ---------------------------------------------------------------------------

def generate_feed_items() -> list[dict]:
    """Generate feed items for significant crowd sentiment events.

    Called by the observer pipeline. Returns list of items for
    mind_feed_engine to consider.
    """
    snap = compute()
    items = []

    alignment = snap.get("alignment", "unclear")
    div_score = snap.get("divergence_score", 0)
    insight = snap.get("insight", "")

    # Only emit feed items when there's something notable
    if alignment == "diverging" and div_score >= 40:
        items.append({
            "type": "crowd_divergence",
            "message": insight,
            "detail": f"Divergence: {div_score}/100 — crowd {snap['crowd_bias']}, price {snap['price_trend']}",
            "importance": min(8, 4 + div_score // 20),
        })
    elif alignment == "aligned" and snap.get("crowd_strength", 0) > 30:
        items.append({
            "type": "crowd_aligned",
            "message": insight,
            "detail": f"Crowd and price in agreement. Confidence: {snap['crowd_strength']:.0f}%",
            "importance": 3,
        })

    return items


# ---------------------------------------------------------------------------
# DB persistence helper
# ---------------------------------------------------------------------------

def persist_snapshot() -> int | None:
    """Persist current crowd sentiment to DB. Returns event_id or None."""
    try:
        import db
        snap = compute()
        if snap.get("warming_up"):
            return None

        import json as _json
        notes = {
            "price_change_pct": snap.get("price_change_pct"),
            "alignment_reason": snap.get("alignment_reason"),
            "insight": snap.get("insight"),
            "data_source": snap.get("data_source"),
        }

        event_id = db.insert_crowd_sentiment_event(
            source=snap.get("source", "internal_sentiment"),
            event_id=f"bvr_{int(time.time())}",
            question=snap.get("question", ""),
            crowd_probability=snap.get("crowd_probability", 50) / 100,
            bias=snap.get("crowd_bias", "neutral"),
            confidence_strength=snap.get("crowd_strength", 0) / 100,
            notes_json=_json.dumps(notes),
        )
        return event_id
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Truth validation support — was the crowd right?
# ---------------------------------------------------------------------------

def evaluate_past_beliefs(hours_back: int = 24) -> list[dict]:
    """Evaluate past crowd sentiment events against actual price movement.

    Returns list of evaluated beliefs with verdicts:
    correct, wrong, mixed, faded.
    """
    try:
        import db
        events = db.get_crowd_sentiment_events(limit=50)
        if not events:
            return []

        price_info = _get_price_trend()
        current_price = price_info.get("current_price", 0)
        if current_price <= 0:
            return []

        results = []
        for ev in events[:20]:
            notes = {}
            try:
                import json as _json
                notes = _json.loads(ev.get("notes_json") or "{}") or {}
            except Exception:
                pass

            recorded_price = notes.get("current_price", 0)
            if recorded_price and recorded_price > 0:
                move_pct = ((current_price - recorded_price) / recorded_price) * 100
            else:
                move_pct = 0

            bias = ev.get("bias", "neutral")

            if abs(move_pct) < 0.15:
                verdict = "unclear"
                explanation = "Price barely moved since this belief."
            elif bias == "bullish" and move_pct > 0.15:
                verdict = "correct"
                explanation = f"Crowd was bullish, price rose {move_pct:+.2f}%."
            elif bias == "bearish" and move_pct < -0.15:
                verdict = "correct"
                explanation = f"Crowd was bearish, price fell {move_pct:+.2f}%."
            elif bias == "bullish" and move_pct < -0.15:
                verdict = "wrong"
                explanation = f"Crowd was bullish but price fell {move_pct:+.2f}%."
            elif bias == "bearish" and move_pct > 0.15:
                verdict = "wrong"
                explanation = f"Crowd was bearish but price rose {move_pct:+.2f}%."
            elif bias == "neutral":
                verdict = "mixed"
                explanation = "Crowd was neutral — hard to grade."
            else:
                verdict = "mixed"
                explanation = f"Ambiguous outcome. Move: {move_pct:+.2f}%."

            results.append({
                "event_id": ev.get("id"),
                "timestamp": ev.get("timestamp"),
                "bias": bias,
                "crowd_probability": ev.get("crowd_probability"),
                "actual_move_pct": round(move_pct, 3),
                "verdict": verdict,
                "explanation": explanation,
            })

        return results
    except Exception:
        return []
