"""
claude_insight_engine.py — CryptoMind v7.8.2

Claude-powered voice layer. Session insights + daily reviews.

Rules:
  - Claude is NEVER in the 30-second trading loop
  - Insights generated only on meaningful state changes
  - Background thread — never blocks trading
  - Template fallback on any failure
  - Hard throttle: 10min gap, 6/hour, 60/day
  - No trading advice in output — observation only

Architecture:
  check_insight_trigger(state) → called after each cycle
    → evaluates edge band, regime, trade events
    → if trigger fires AND throttle allows → background Claude call
    → stores result in system_state.insight_state_json
    → if Claude fails → template fallback, no retry

  generate_daily_review() → called once per day
    → uses Sonnet for richer reflection
    → stores in daily_reviews table
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# Edge band classification
# ---------------------------------------------------------------------------

def classify_edge_band(score: float, confidence: float, regime: str) -> str:
    """Classify current state into an edge band.
    Simple, auditable, not over-coupled to regime."""
    if score > 60 and confidence > 0.15:
        return "action_edge"
    if score > 50 and confidence > 0.08:
        return "possible_edge"
    if regime in ("ACTIVE", "WAKING_UP", "BREAKOUT") or score > 40:
        return "watching"
    return "no_edge"


# ---------------------------------------------------------------------------
# Throttle state (module-level, resets on restart)
# ---------------------------------------------------------------------------

_last_call_time: float = 0.0
_calls_this_hour: int = 0
_calls_today: int = 0
_hour_start: float = 0.0
_day_start: str = ""

_MIN_GAP_SECONDS: float = 600.0     # 10 minutes
_MAX_PER_HOUR: int = 6
_MAX_PER_DAY: int = 60
_HEARTBEAT_SECONDS: float = 1800.0  # 30 minutes

# Last stored state for change detection
_last_edge_band: str = ""
_last_regime: str = ""
_last_state_hash: str = ""
_last_insight_time: float = 0.0


def _reset_hourly_if_needed():
    global _calls_this_hour, _hour_start
    now = time.time()
    if now - _hour_start > 3600:
        _calls_this_hour = 0
        _hour_start = now


def _reset_daily_if_needed():
    global _calls_today, _day_start
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if today != _day_start:
        _calls_today = 0
        _day_start = today


def _can_call() -> bool:
    """Check all throttle limits."""
    _reset_hourly_if_needed()
    _reset_daily_if_needed()

    now = time.time()
    if (now - _last_call_time) < _MIN_GAP_SECONDS:
        return False
    if _calls_this_hour >= _MAX_PER_HOUR:
        return False
    if _calls_today >= _MAX_PER_DAY:
        return False
    return True


def _record_call():
    global _last_call_time, _calls_this_hour, _calls_today
    _last_call_time = time.time()
    _calls_this_hour += 1
    _calls_today += 1


# ---------------------------------------------------------------------------
# State hash for dedup
# ---------------------------------------------------------------------------

def _compute_state_hash(state: dict) -> str:
    """Hash key fields to detect meaningful change."""
    key = f"{state.get('regime','')}-{state.get('edge_band','')}-{state.get('score',0):.0f}-{state.get('trade_count',0)}"
    return hashlib.md5(key.encode()).hexdigest()[:8]


# ---------------------------------------------------------------------------
# Trigger check — called after each cycle
# ---------------------------------------------------------------------------

def check_insight_trigger(state: dict) -> None:
    """Evaluate whether to generate a new Claude insight.

    State should contain: regime, score, confidence, price, trend, volatility,
    equity, exposure, cycle_count, trade_count, pnl, last_action
    """
    global _last_edge_band, _last_regime, _last_state_hash, _last_insight_time

    edge_band = classify_edge_band(
        state.get("score", 50),
        state.get("confidence", 0),
        state.get("regime", "SLEEPING"),
    )
    state["edge_band"] = edge_band

    # Determine trigger reason
    trigger = None

    if state.get("trade_just_executed"):
        trigger = "trade_executed"
    elif edge_band != _last_edge_band and _last_edge_band != "":
        trigger = "edge_band_changed"
    elif state.get("regime", "") != _last_regime and _last_regime != "":
        trigger = "regime_changed"
    elif (time.time() - _last_insight_time) > _HEARTBEAT_SECONDS:
        trigger = "heartbeat"

    # Update tracking
    _last_edge_band = edge_band
    _last_regime = state.get("regime", "")

    if not trigger:
        return

    # Check state hash — skip if nothing meaningful changed (except heartbeat)
    state_hash = _compute_state_hash(state)
    if trigger != "heartbeat" and trigger != "trade_executed" and state_hash == _last_state_hash:
        return
    _last_state_hash = state_hash

    # Check throttle
    if not _can_call():
        return

    # Fire in background thread
    _last_insight_time = time.time()
    t = threading.Thread(
        target=_generate_insight,
        args=(state.copy(), trigger, edge_band),
        daemon=True,
    )
    t.start()


# ---------------------------------------------------------------------------
# Insight generation (runs in background thread)
# ---------------------------------------------------------------------------

def _generate_insight(state: dict, trigger: str, edge_band: str) -> None:
    """Generate a Claude insight and store it. Fallback to template on failure."""
    try:
        text = _call_claude_insight(state, trigger)
        source = "claude"
    except Exception as e:
        print(f"[insight] Claude failed ({e}), using template")
        text = _template_insight(state, trigger)
        source = "template_fallback"

    # Validate
    if not text or len(text) < 10 or len(text) > 300:
        text = _template_insight(state, trigger)
        source = "template_fallback"

    # Strip any markdown that slipped through
    text = _clean_text(text)

    # Store
    _record_call()
    _store_insight(text, trigger, edge_band, source)

    print(f"[insight] {source}: \"{text[:60]}...\" (trigger={trigger})")


def _call_claude_insight(state: dict, trigger: str) -> str:
    """Call Claude Haiku for a session insight."""
    import anthropic
    from config import get_insight_model

    model = get_insight_model()
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("No API key")

    client = anthropic.Anthropic(api_key=api_key)

    system_prompt = (
        "You are CryptoMind's inner voice. Describe what you observe in 1-2 short sentences. "
        "Plain text only. No markdown, lists, emojis, or jargon. No trading advice. "
        "Be honest and grounded. Max 2 sentences."
    )

    user_prompt = (
        f"State: {state.get('regime', 'SLEEPING')}, score {state.get('score', 50):.0f}/100, "
        f"confidence {state.get('confidence', 0)*100:.0f}%\n"
        f"Edge: {state.get('edge_band', 'no_edge')}\n"
        f"Trigger: {trigger}\n"
        f"Price: ${state.get('price', 0):,.2f}, trend: {state.get('trend', 'sideways')}, "
        f"volatility: {state.get('volatility', 0):.4f}\n"
        f"Portfolio: ${state.get('equity', 100):.2f} equity, "
        f"{state.get('exposure', 0):.1f}% exposed\n"
        f"Session: {state.get('cycle_count', 0)} cycles, "
        f"{state.get('trade_count', 0)} trades, P&L ${state.get('pnl', 0):.4f}\n"
        f"Last action: {state.get('last_action', 'HOLD')}"
    )

    response = client.messages.create(
        model=model,
        max_tokens=80,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    return response.content[0].text.strip()


def _template_insight(state: dict, trigger: str) -> str:
    """Template-based fallback when Claude is unavailable."""
    regime = state.get("regime", "SLEEPING")
    score = state.get("score", 50)
    edge_band = state.get("edge_band", "no_edge")

    if trigger == "trade_executed":
        action = state.get("last_action", "HOLD")
        if action == "BUY":
            return "Took a position. Low conviction — testing the water."
        elif action == "SELL":
            return "Closed position. Reviewing outcome."
        return "Trade executed."

    if edge_band == "action_edge":
        return "Signals aligning. Close to action threshold."
    if edge_band == "possible_edge":
        return "Something forming. Not convincing yet."
    if edge_band == "watching":
        return "Market showing signs of life. Watching."

    if regime == "SLEEPING":
        return "Dead quiet. No edge in sight."
    if regime == "WAKING_UP":
        return "Market stirring. Nothing decisive yet."
    if regime == "ACTIVE":
        return "Active environment. Scanning for edge."
    if regime == "BREAKOUT":
        return "Sharp movement detected. Evaluating."

    return "Observing. Nothing decisive yet."


# ---------------------------------------------------------------------------
# Daily review generation
# ---------------------------------------------------------------------------

def generate_daily_review(date: str = None) -> dict:
    """Generate a Claude-powered daily review. Called once per day.
    Returns {review_text, source, date}."""
    if not date:
        date = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%d")

    # Check if already reviewed today
    try:
        import db as v7db
        existing = v7db.get_lifetime_daily_reviews(limit=1)
        if existing and existing[0].get("review_date") == date:
            return {"review_text": existing[0].get("next_day_bias", ""), "source": "cached", "date": date}
    except Exception:
        pass

    # Gather day's data
    day_data = _gather_daily_data()

    try:
        text = _call_claude_daily_review(day_data, date)
        source = "claude"
    except Exception as e:
        print(f"[insight] Daily review Claude failed ({e}), using template")
        text = _template_daily_review(day_data)
        source = "template_fallback"

    text = _clean_text(text)

    # Store in daily_reviews table
    try:
        import db as v7db
        import session_manager
        sid = session_manager.get_session_id() or 1
        v7db.insert_daily_review(
            session_id=sid,
            review_date=date,
            trades_count=day_data.get("total_trades", 0),
            winning_trades=day_data.get("wins", 0),
            losing_trades=day_data.get("losses", 0),
            net_pnl=day_data.get("pnl", 0),
            what_worked="",
            what_failed="",
            behavior_observation=text,
            next_day_bias=text,
        )
    except Exception as e:
        print(f"[insight] Could not store daily review: {e}")

    return {"review_text": text, "source": source, "date": date}


def _call_claude_daily_review(day_data: dict, date: str) -> str:
    """Call Claude Sonnet for daily review."""
    import anthropic
    from config import get_review_model

    model = get_review_model()
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("No API key")

    client = anthropic.Anthropic(api_key=api_key)

    system_prompt = (
        "You are CryptoMind reflecting on today's trading session. "
        "Write a 3-4 sentence honest review. Plain text only. "
        "No markdown, lists, emojis, or jargon. Be specific about what happened."
    )

    user_prompt = (
        f"Date: {date}\n"
        f"Cycles: {day_data.get('total_cycles', 0)}\n"
        f"Trades: {day_data.get('total_trades', 0)} "
        f"({day_data.get('buys', 0)} buys, {day_data.get('sells', 0)} sells)\n"
        f"Wins: {day_data.get('wins', 0)}, Losses: {day_data.get('losses', 0)}\n"
        f"P&L: ${day_data.get('pnl', 0):.4f}\n"
        f"Regime: mostly {day_data.get('dominant_regime', 'SLEEPING')}\n"
        f"Probes: {day_data.get('probes', 0)}\n"
    )

    response = client.messages.create(
        model=model,
        max_tokens=200,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    return response.content[0].text.strip()


def _template_daily_review(day_data: dict) -> str:
    """Template fallback for daily review."""
    trades = day_data.get("total_trades", 0)
    regime = day_data.get("dominant_regime", "SLEEPING")
    pnl = day_data.get("pnl", 0)

    if trades == 0:
        return f"Quiet day. Market stayed {regime}. No trades executed. Patience held."
    elif pnl > 0:
        return f"{trades} trades today. Net positive. Market was {regime} for most of the session."
    else:
        return f"{trades} trades today. Small loss. Market was {regime}. Need to be more selective."


def _gather_daily_data() -> dict:
    """Gather today's trading data for daily review."""
    try:
        import db as v7db
        stats = v7db.get_trade_stats_by_scope(scope="daily")
        system = v7db.get_system_state() or {}
        return {
            "total_cycles": system.get("total_lifetime_cycles", 0),
            "total_trades": stats.get("total", 0),
            "buys": stats.get("buys", 0),
            "sells": stats.get("sells", 0),
            "wins": stats.get("wins", 0),
            "losses": stats.get("losses", 0),
            "pnl": stats.get("total_pnl", 0),
            "dominant_regime": system.get("current_regime", "SLEEPING"),
            "probes": 0,
        }
    except Exception:
        return {"total_cycles": 0, "total_trades": 0, "dominant_regime": "SLEEPING"}


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _store_insight(text: str, trigger: str, edge_band: str, source: str) -> None:
    """Store insight in system_state.insight_state_json."""
    payload = {
        "text": text,
        "trigger": trigger,
        "edge_band": edge_band,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": "haiku" if source == "claude" else "template",
        "source": source,
        "call_count_today": _calls_today,
    }
    try:
        import db as v7db
        v7db.upsert_system_state(insight_state_json=json.dumps(payload))
    except Exception as e:
        print(f"[insight] Could not store insight: {e}")


def get_current_insight() -> dict:
    """Get the latest stored insight."""
    try:
        import db as v7db
        system = v7db.get_system_state()
        raw = system.get("insight_state_json") if system else None
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return {"text": "Observing. Nothing decisive yet.", "source": "default", "trigger": "none"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_text(text: str) -> str:
    """Strip markdown artifacts from Claude output."""
    text = re.sub(r'^[#*\-]+\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'[`*_]', '', text)
    text = text.strip().strip('"').strip("'")
    return text
