"""
replay_engine.py — CryptoMind v7.4 Chunk 3: Timeline Reconstruction.

Reconstructs the session timeline:
    news → interpretation → mind state → action → outcome

Creates replay markers from trades, news events, mind state changes,
and milestone events, then assembles them into a chronological timeline.

Observer module — reads from multiple tables, writes ONLY to replay_markers
(observer-owned table).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

# Cache
_cache = None
_cache_ts = 0
_CACHE_TTL = 90  # seconds


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Marker generation
# ---------------------------------------------------------------------------

def _markers_from_trades(trades: list[dict], session_id: int) -> list[dict]:
    """Create timeline markers from trades."""
    markers = []
    for t in trades:
        action = t.get("action", "HOLD")
        if action == "HOLD":
            continue
        pnl = t.get("pnl", 0) or 0
        strategy = t.get("strategy", "")
        price = t.get("price", 0)

        if action == "BUY":
            title = f"Buy @ ${price:,.0f}"
            detail = f"Strategy: {strategy}, Score: {t.get('score', 0):.0%}, Confidence: {t.get('confidence', 0):.0%}"
            importance = 7
        else:
            title = f"Sell @ ${price:,.0f} ({pnl:+.4f})"
            detail = f"Strategy: {strategy}, PnL: {pnl:+.4f}"
            importance = 8 if abs(pnl) > 0.01 else 6

        markers.append({
            "session_id": session_id,
            "marker_type": "trade",
            "title": title,
            "detail": detail,
            "linked_trade_id": t.get("trade_id"),
            "price_at_marker": price,
            "importance": importance,
            "timestamp": t.get("timestamp", ""),
            "_sort_ts": t.get("timestamp", ""),
        })

    return markers


def _markers_from_news(analyses: list[dict], session_id: int) -> list[dict]:
    """Create timeline markers from classified news."""
    markers = []
    for n in analyses:
        verdict = n.get("verdict", "noise")
        if verdict not in ("interesting", "watch"):
            continue

        headline = n.get("headline", "")
        sentiment = n.get("sentiment", "neutral")
        importance = 6 if verdict == "interesting" else 4

        markers.append({
            "session_id": session_id,
            "marker_type": "news",
            "title": f"📰 {headline[:60]}{'…' if len(headline) > 60 else ''}",
            "detail": f"{sentiment} | {verdict} | Trust: {n.get('trust_score', 0.5):.0%}",
            "linked_news_analysis_id": n.get("analysis_id"),
            "importance": importance,
            "timestamp": n.get("timestamp", ""),
            "_sort_ts": n.get("timestamp", ""),
        })

    return markers


def _markers_from_mind_states(states: list[dict], session_id: int) -> list[dict]:
    """Create markers from significant mind state changes."""
    if not states:
        return []

    markers = []
    prev_mood = None

    for s in reversed(states):  # oldest first
        mood = s.get("mind_state", "idle_waiting")
        if mood == prev_mood:
            continue  # skip duplicate moods
        prev_mood = mood

        label = s.get("mind_state_label", mood.replace("_", " "))
        clarity = s.get("clarity", 50)

        markers.append({
            "session_id": session_id,
            "marker_type": "mood_shift",
            "title": f"Mood → {label}",
            "detail": f"Clarity: {clarity}%",
            "linked_mind_state": mood,
            "mood_at_marker": mood,
            "importance": 3,
            "timestamp": s.get("timestamp", ""),
            "_sort_ts": s.get("timestamp", ""),
        })

    return markers


def _markers_from_milestones(milestones: list[dict], session_id: int) -> list[dict]:
    """Create markers from milestone achievements."""
    markers = []
    for m in milestones:
        markers.append({
            "session_id": session_id,
            "marker_type": "milestone",
            "title": f"🏆 {m.get('title', 'Milestone')}",
            "detail": m.get("description", ""),
            "importance": 9,
            "timestamp": m.get("timestamp", ""),
            "_sort_ts": m.get("timestamp", ""),
        })
    return markers


def _markers_from_regime_changes(snapshots: list[dict], session_id: int) -> list[dict]:
    """Create markers from regime transitions."""
    if not snapshots:
        return []

    markers = []
    prev_regime = None

    for s in reversed(snapshots):  # oldest first
        regime = s.get("regime")
        if not regime or regime == prev_regime:
            continue
        prev_regime = regime

        markers.append({
            "session_id": session_id,
            "marker_type": "regime_change",
            "title": f"Regime → {regime}",
            "detail": f"Price: ${s.get('price', 0):,.0f}, Quality: {s.get('market_quality_score', 0)}",
            "cycle_number": s.get("cycle_number"),
            "price_at_marker": s.get("price"),
            "importance": 5,
            "timestamp": s.get("timestamp", ""),
            "_sort_ts": s.get("timestamp", ""),
        })

    return markers


def _markers_from_crowd_events(events: list[dict], session_id: int) -> list[dict]:
    """Create markers from crowd sentiment divergence events."""
    markers = []
    for ev in events:
        notes = {}
        try:
            import json as _json
            notes = _json.loads(ev.get("notes_json") or "{}") or {}
        except Exception:
            pass

        insight = notes.get("insight", "")
        alignment = notes.get("alignment_reason", "")
        bias = ev.get("bias", "neutral")
        prob = ev.get("crowd_probability", 0.5)

        title = f"Crowd: {bias} ({prob*100:.0f}%)"
        detail = insight or alignment or f"Crowd sentiment snapshot — {bias}"

        markers.append({
            "session_id": session_id,
            "marker_type": "crowd_sentiment",
            "title": title,
            "detail": detail,
            "importance": 3,
            "timestamp": ev.get("timestamp", ""),
            "_sort_ts": ev.get("timestamp", ""),
        })
    return markers


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_replay(session_id: int = None, persist: bool = True) -> dict:
    """Build the full session replay timeline.

    Assembles markers from all sources, sorted chronologically.
    Returns dict with timeline array and stats.
    """
    global _cache, _cache_ts
    import time
    now = time.time()
    if _cache and (now - _cache_ts) < _CACHE_TTL:
        return _cache

    import db
    import session_manager

    sid = session_id or session_manager.get_session_id()
    if not sid:
        return {"timeline": [], "warming_up": True, "error": "No active session"}

    # Gather data from all sources
    trades_list, _ = db.get_trades(session_id=sid, limit=100)
    news_list = db.get_news_analyses(limit=50)
    mind_states = db.get_mind_state_history(session_id=sid, limit=100)
    milestones = db.get_milestones(session_id=sid, limit=20)
    snapshots = db.get_recent_snapshots(sid, limit=200)

    # Crowd sentiment events
    crowd_events = []
    try:
        crowd_events = db.get_crowd_sentiment_events(limit=20)
    except Exception:
        pass

    # Generate markers
    all_markers = []
    all_markers.extend(_markers_from_trades(trades_list, sid))
    all_markers.extend(_markers_from_news(news_list, sid))
    all_markers.extend(_markers_from_mind_states(mind_states, sid))
    all_markers.extend(_markers_from_milestones(milestones, sid))
    all_markers.extend(_markers_from_regime_changes(snapshots, sid))
    all_markers.extend(_markers_from_crowd_events(crowd_events, sid))

    # Sort by timestamp
    all_markers.sort(key=lambda m: m.get("_sort_ts", ""))

    # Dedupe: suppress similar markers within 60-second windows
    deduped = []
    _seen = set()
    for m in all_markers:
        ts = m.get("_sort_ts", "")[:16]  # truncate to minute precision
        mtype = m.get("marker_type", "")
        dedup_key = f"{mtype}:{m.get('title', '')}:{ts}"
        if dedup_key in _seen:
            continue
        _seen.add(dedup_key)
        deduped.append(m)

    # Hard cap at 100 markers per response (keep highest importance)
    _MAX_MARKERS = 100
    if len(deduped) > _MAX_MARKERS:
        deduped.sort(key=lambda m: m.get("importance", 0), reverse=True)
        deduped = deduped[:_MAX_MARKERS]
        deduped.sort(key=lambda m: m.get("_sort_ts", ""))

    # Clean up internal sort key and persist
    timeline = []
    for m in deduped:
        m.pop("_sort_ts", None)
        timeline.append(m)

        if persist:
            try:
                db.insert_replay_marker(
                    session_id=sid,
                    title=m.get("title", ""),
                    marker_type=m.get("marker_type", "event"),
                    cycle_number=m.get("cycle_number"),
                    detail=m.get("detail"),
                    linked_trade_id=m.get("linked_trade_id"),
                    linked_news_analysis_id=m.get("linked_news_analysis_id"),
                    linked_mind_state=m.get("linked_mind_state"),
                    price_at_marker=m.get("price_at_marker"),
                    mood_at_marker=m.get("mood_at_marker"),
                    importance=m.get("importance", 5),
                )
            except Exception:
                pass

    # Stats
    type_counts = {}
    for m in timeline:
        t = m.get("marker_type", "event")
        type_counts[t] = type_counts.get(t, 0) + 1

    result = {
        "timeline": timeline,
        "total_markers": len(timeline),
        "marker_types": type_counts,
        "session_id": sid,
        "warming_up": len(timeline) < 3,
    }

    _cache = result
    _cache_ts = now
    return result


def get_replay_segment(session_id: int, cycle_start: int = 0,
                        cycle_end: int = 999999) -> dict:
    """Get a segment of the replay timeline by cycle range."""
    import db
    markers = db.get_replay_timeline(session_id, cycle_start, cycle_end)
    return {
        "markers": markers,
        "cycle_range": [cycle_start, cycle_end],
        "total": len(markers),
    }
