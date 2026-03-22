"""
mind_feed_engine.py — CryptoMind v7.4 Observer Core: Mind Feed.

Produces a live, human-readable feed of what the system is observing.
Combines news observations, trading events, mind state changes, and
internal reflections into a single chronological stream.

The system's internal monologue — visible to the user.
"""

from __future__ import annotations

import time
import threading
from datetime import datetime, timezone
from collections import deque

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_MAX_ITEMS       = 200
_DEDUP_SEC       = 45   # don't repeat the same event within this window
_TOPIC_COOLDOWN  = 300  # 5 min cooldown per topic/category before re-emitting
_SIMILARITY_THR  = 0.65 # suppress headlines with >65% word overlap

# ---------------------------------------------------------------------------
# Feed item types
# ---------------------------------------------------------------------------

TYPES = {
    "news_interesting":  {"icon": "◆", "color": "#22c55e", "label": "Signal"},
    "news_watch":        {"icon": "◇", "color": "#3b82f6", "label": "Watching"},
    "news_reject":       {"icon": "○", "color": "#6b7280", "label": "Rejected"},
    "news_unclear":      {"icon": "?", "color": "#8b5cf6", "label": "Unclear"},
    "news_noise":        {"icon": "·", "color": "#4b5563", "label": "Noise"},
    "trade_buy":         {"icon": "▲", "color": "#22c55e", "label": "Bought"},
    "trade_sell":        {"icon": "▼", "color": "#ef4444", "label": "Sold"},
    "mind_thought":      {"icon": "◎", "color": "#8b5cf6", "label": "Thought"},
    "mind_concern":      {"icon": "◈", "color": "#d97706", "label": "Concern"},
    "mind_opportunity":  {"icon": "●", "color": "#22c55e", "label": "Opportunity"},
    "mood_change":       {"icon": "◉", "color": "#8b5cf6", "label": "Mood Shift"},
    "radar_alert":       {"icon": "⬡", "color": "#ef4444", "label": "Radar Alert"},
    "market_shift":      {"icon": "◐", "color": "#3b82f6", "label": "Market Shift"},
    "fear_greed":        {"icon": "◑", "color": "#d97706", "label": "Fear & Greed"},
    "narration":         {"icon": "◫", "color": "#8b5cf6", "label": "Narration"},
    "crowd_divergence":  {"icon": "⬢", "color": "#f59e0b", "label": "Crowd Signal"},
    "crowd_aligned":     {"icon": "⬡", "color": "#22c55e", "label": "Crowd Signal"},
    "signal_alignment":  {"icon": "◈", "color": "#22c55e", "label": "Signal"},
    "signal_divergence": {"icon": "◈", "color": "#f59e0b", "label": "Signal"},
    "signal_warning":    {"icon": "◈", "color": "#ef4444", "label": "Signal Alert"},
    "signal_info":       {"icon": "◈", "color": "#3b82f6", "label": "Signal"},
    "system":            {"icon": "◻", "color": "#6b7280", "label": "System"},
}

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_lock         = threading.Lock()
_feed: deque  = deque(maxlen=_MAX_ITEMS)
_dedup: dict  = {}          # key → timestamp
_topic_last: dict = {}      # category → last_emit_timestamp
_recent_words: list = []    # recent headline word sets for similarity check
_last_mood    = ""
_last_mkt     = ""
_last_fg      = -1

# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _ok(key: str) -> bool:
    """Returns True if this key hasn't been added recently."""
    now = time.time()
    # purge old
    expired = [k for k, t in _dedup.items() if now - t > _DEDUP_SEC]
    for k in expired:
        del _dedup[k]
    if key in _dedup:
        return False
    _dedup[key] = now
    return True


def _topic_ok(category: str) -> bool:
    """Topic cooldown — suppress repeated category emissions."""
    if not category:
        return True
    now = time.time()
    last = _topic_last.get(category, 0)
    if (now - last) < _TOPIC_COOLDOWN:
        return False
    _topic_last[category] = now
    return True


def _headline_similar(headline: str) -> bool:
    """Check if headline is too similar to recently emitted ones."""
    words = set(headline.lower().split())
    if len(words) < 3:
        return False
    now = time.time()
    # Trim old entries (keep last 2 min)
    while _recent_words and (now - _recent_words[0][1]) > 120:
        _recent_words.pop(0)
    for prev_words, _ in _recent_words:
        if not prev_words:
            continue
        overlap = len(words & prev_words) / max(len(words | prev_words), 1)
        if overlap >= _SIMILARITY_THR:
            return True
    _recent_words.append((words, now))
    return False


def _add(feed_type: str, message: str, detail: str = None,
         meta: dict = None, linked_news_id: int = None,
         linked_trade_id: int = None, linked_cycle_id: int = None) -> bool:
    """Add an item.  Returns True if accepted."""
    dedup_key = f"{feed_type}:{message[:60]}"
    if not _ok(dedup_key):
        return False
    ti = TYPES.get(feed_type, TYPES["system"])
    item = {
        "type":       feed_type,
        "icon":       ti["icon"],
        "color":      ti["color"],
        "label":      ti["label"],
        "message":    message,
        "detail":     detail,
        "meta":       meta or {},
        "linked_news_event_id":     linked_news_id,
        "linked_trade_id":          linked_trade_id,
        "linked_cycle_snapshot_id": linked_cycle_id,
        "timestamp":  datetime.now(timezone.utc).isoformat(),
    }
    with _lock:
        _feed.appendleft(item)
    return True

# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------

def on_news_classified(classified: list[dict]) -> int:
    """Process classified news into feed events.  Returns count added."""
    added = 0
    for c in classified:
        v   = c.get("verdict", "noise")
        h   = c.get("headline", "?")
        ex  = c.get("explanation", "")
        src = c.get("source_name", "")
        cat = c.get("category", "general")

        # --- near-duplicate suppression ---
        if _headline_similar(h):
            continue

        if v == "interesting":
            ft = "news_interesting"
            det = f"{ex}" + (f" — via {src}" if src else "")
        elif v == "watch":
            ft = "news_watch"
            det = f"{ex}"
            # topic cooldown for watch-level (don't spam similar categories)
            if not _topic_ok(cat):
                continue
        elif v == "unclear":
            ft = "news_watch"
            det = f"{ex}" + (f" — via {src}" if src else "")
        elif v == "reject":
            ft = "news_reject"
            det = f"{ex}"
            # topic cooldown for rejected too
            if not _topic_ok(f"rej_{cat}"):
                continue
        else:
            # only surface occasional noise
            if added % 5 != 0:
                continue
            ft = "news_noise"
            det = "Filtered as noise."

        if _add(ft, h, detail=det, meta={
            "sentiment":       c.get("sentiment"),
            "impact":          c.get("impact"),
            "bs_risk":         c.get("bs_risk"),
            "source":          src,
            "category":        cat,
            "verdict":         v,
            "trust":           c.get("trust"),
            "relevance":       c.get("relevance"),
            "hype_score":      c.get("hype_score"),
            "url":             c.get("url"),
            "body":            (c.get("body") or "")[:300] or None,
            "reasoning_text":  c.get("reasoning_text"),
            "bullish_signals": c.get("bullish_signals", []),
            "bearish_signals": c.get("bearish_signals", []),
        }):
            added += 1
    return added


def on_mind_state(old_mood: str, new_mood: str,
                  thoughts: list[str], concerns: list[str],
                  opportunities: list[str]) -> None:
    """React to mind state change."""
    global _last_mood
    if new_mood != _last_mood:
        _add("mood_change", f"Mind → {new_mood}",
             detail=thoughts[0] if thoughts else None)
        _last_mood = new_mood
    for t in thoughts[:2]:
        _add("mind_thought", t)
    for c in concerns[:2]:
        _add("mind_concern", c)
    for o in opportunities[:1]:
        _add("mind_opportunity", o)


def on_market_shift(old: str, new: str, reason: str = "") -> None:
    global _last_mkt
    if new != _last_mkt:
        _add("market_shift", f"Market: {old} → {new}", detail=reason or None)
        _last_mkt = new


def on_fear_greed(value: int, classification: str, direction: str) -> None:
    global _last_fg
    if abs(value - _last_fg) >= 5 or _last_fg < 0:
        arrow = "↑" if direction == "rising" else "↓" if direction == "falling" else "→"
        _add("fear_greed", f"Fear & Greed: {value} ({classification}) {arrow}",
             detail=f"Was {_last_fg}" if _last_fg >= 0 else None)
        _last_fg = value


def on_radar_alert(level: str, reason: str = None) -> None:
    if level in ("elevated", "high", "extreme"):
        _add("radar_alert", f"BS Radar: {level.upper()}", detail=reason)


def on_trade_narration(action: str, price: float, strategy: str,
                       score: float, confidence: float,
                       narration: str = None,
                       trade_id: int = None) -> None:
    """Called by action_narrator after a trade."""
    ft = "trade_buy" if action == "BUY" else "trade_sell" if action == "SELL" else "narration"
    msg = narration or f"{action} @ ${price:,.2f} via {strategy}"
    det = f"Score {score:.0f}, confidence {confidence*100:.0f}%"
    _add(ft, msg, detail=det, linked_trade_id=trade_id)


def on_narration(text: str, detail: str = None) -> None:
    """Generic narration from action_narrator."""
    _add("narration", text, detail=detail)


def on_crowd_sentiment(feed_items: list[dict]) -> int:
    """Process crowd sentiment feed items. Returns count added."""
    added = 0
    for item in feed_items:
        ft = item.get("type", "crowd_divergence")
        msg = item.get("message", "")
        det = item.get("detail", "")
        if _add(ft, msg, detail=det):
            added += 1
    return added


def on_signal_insights(insights: list[dict]) -> int:
    """Process signal layer insights into feed events. Returns count added."""
    added = 0
    for ins in insights:
        ft = ins.get("type", "signal_info")
        if ft not in TYPES:
            ft = "signal_info"
        title = ins.get("title", "Signal")
        detail = ins.get("detail", "")
        if _add(ft, title, detail=detail, meta={"importance": ins.get("importance", 5), "source": ins.get("source", "")}):
            added += 1
    return added

# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def get_feed(limit: int = 50, feed_type: str = None) -> list[dict]:
    with _lock:
        items = list(_feed)
    if feed_type:
        items = [i for i in items if i["type"] == feed_type]
    return items[:limit]


def get_summary() -> dict:
    with _lock:
        items = list(_feed)
    n = len(items)
    if n == 0:
        return {"total": 0, "message": "Feed empty — warming up."}
    types = {}
    for i in items:
        types[i["type"]] = types.get(i["type"], 0) + 1
    return {
        "total":       n,
        "type_counts": types,
        "latest_ts":   items[0]["timestamp"] if items else None,
    }

# ---------------------------------------------------------------------------
# DB persistence
# ---------------------------------------------------------------------------

def persist_important() -> int:
    """Save interesting/watch items + mood changes to DB.  Returns count."""
    try:
        import db as v7db
        import session_manager
        sid = session_manager.get_session_id()
        if not sid:
            return 0
        keep_types = {"news_interesting", "news_watch", "mood_change",
                      "radar_alert", "market_shift", "trade_buy", "trade_sell",
                      "narration", "crowd_divergence", "crowd_aligned"}
        with _lock:
            items = [i for i in _feed if i["type"] in keep_types]
        count = 0
        for i in items[:30]:
            try:
                v7db.insert_mind_feed_event(
                    session_id=sid,
                    event_type=i["type"],
                    title=i["label"],
                    summary=i["message"],
                    detail=i.get("detail"),
                    mood=_last_mood or "unknown",
                    source=i.get("meta", {}).get("sentiment", ""),
                    novelty_score=0.0,
                    relevance_score=0.0,
                    hype_score=i.get("meta", {}).get("bs_risk", 0.0),
                    bs_risk=i.get("meta", {}).get("bs_risk", 0.0),
                    confidence=0.5,
                    linked_news_event_id=i.get("linked_news_event_id"),
                    linked_trade_id=i.get("linked_trade_id"),
                    linked_cycle_snapshot_id=i.get("linked_cycle_snapshot_id"),
                    metadata_json=str(i.get("meta", {})),
                )
                count += 1
            except Exception:
                pass
        return count
    except Exception:
        return 0
