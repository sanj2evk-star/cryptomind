"""
review_export_engine.py — CryptoMind v7.5.2: Review Export / Black Box System.

Generates structured, explainable review exports of system behavior,
decisions, learning, and evolution over any time range.

Supports:
    - daily / weekly / monthly / custom review types
    - session / version / lifetime scope
    - summary / detailed output modes
    - human-readable text + structured JSON

Reads from lifetime-persistent layers:
    - trade_ledger, version_sessions, system_state
    - experience_memory, behavior_profile, adaptation_journal
    - mind_journal_entries, action_reflections, daily_reviews
    - news_truth_reviews, news_event_analysis, crowd_sentiment_events
    - lifetime_identity, lifetime_portfolio, milestones
    - replay_markers

Rule-based, deterministic. No LLM dependency.
Observer-only — no effect on execution.
Preserves full continuity across versions — version upgrades are NOT resets.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone, timedelta
from collections import Counter

# ---------------------------------------------------------------------------
# Cache (short TTL — reviews are heavy)
# ---------------------------------------------------------------------------
_cache: dict = {}
_cache_ts: float = 0
_CACHE_TTL = 60  # seconds


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe(fn, default=None):
    """Call fn, return default on any exception."""
    try:
        return fn()
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Date range helpers
# ---------------------------------------------------------------------------

def _resolve_dates(review_type: str, start_date: str = None,
                   end_date: str = None) -> tuple[str, str]:
    """Resolve start/end dates from review_type or explicit params.

    Returns (start_iso, end_iso) as ISO date strings (YYYY-MM-DD).
    """
    today = datetime.now(timezone.utc).date()

    if review_type == "custom" and start_date and end_date:
        return start_date, end_date
    elif review_type == "custom" and start_date:
        return start_date, today.isoformat()

    if review_type == "daily":
        return today.isoformat(), today.isoformat()
    elif review_type == "weekly":
        start = today - timedelta(days=7)
        return start.isoformat(), today.isoformat()
    elif review_type == "monthly":
        start = today - timedelta(days=30)
        return start.isoformat(), today.isoformat()
    else:
        # Fallback: daily
        return today.isoformat(), today.isoformat()


def _in_range(timestamp_str: str, start: str, end: str) -> bool:
    """Check if a timestamp falls within [start, end] date range."""
    if not timestamp_str:
        return False
    ts_date = timestamp_str[:10]
    return start <= ts_date <= end


# ---------------------------------------------------------------------------
# Section builders — each returns a dict
# ---------------------------------------------------------------------------

def build_header(review_type: str, scope: str, start_date: str,
                 end_date: str) -> dict:
    """Section A: header metadata."""
    try:
        import db as v7db
        import session_manager
    except Exception:
        return {
            "version": "unknown", "session_id": 0,
            "review_type": review_type, "scope": scope,
            "start_date": start_date, "end_date": end_date,
            "generated_at": _now_utc(),
            "total_cycles_in_range": 0, "total_cycles_lifetime": 0,
            "total_sessions_lifetime": 0,
        }

    system = _safe(v7db.get_system_state, {}) or {}
    identity = _safe(v7db.get_lifetime_identity, {}) or {}
    sid = _safe(session_manager.get_session_id, 0)
    version = getattr(session_manager, "APP_VERSION", "?")

    return {
        "version": version,
        "session_id": sid,
        "review_type": review_type,
        "scope": scope,
        "start_date": start_date,
        "end_date": end_date,
        "generated_at": _now_utc(),
        "total_cycles_in_range": system.get("system_age_cycles", 0),
        "total_cycles_lifetime": identity.get("total_cycles", 0) or system.get("total_lifetime_cycles", 0),
        "total_sessions_lifetime": identity.get("total_sessions", 0),
    }


def build_mind_state() -> dict:
    """Section B: current mind state."""
    try:
        import mind_evolution
        mind = mind_evolution.get_full_mind_state()
    except Exception:
        mind = {}

    try:
        import session_intent_engine
        intent = session_intent_engine.compute()
    except Exception:
        intent = {}

    try:
        import db as v7db
        identity = v7db.get_lifetime_identity() or {}
    except Exception:
        identity = {}

    level_info = mind.get("mind_level", {})
    confidence = mind.get("confidence", {})
    evidence = mind.get("evidence_strength", {})

    return {
        "current_level": level_info.get("level", "Seed"),
        "evolution_score": mind.get("evolution_score", 0),
        "confidence_label": confidence.get("label", "Very Low"),
        "confidence_score": confidence.get("score", 0),
        "evidence_strength_pct": evidence.get("pct", 0),
        "session_intent": intent.get("intent", "neutral"),
        "intent_confidence": intent.get("confidence", 0),
        "continuity_score": identity.get("continuity_score", 0),
        "identity_status": "forming" if (identity.get("total_cycles", 0) or 0) < 100 else "established",
    }


def build_market_context(start: str, end: str) -> dict:
    """Section C: market context during the review period."""
    try:
        import bullshit_radar
        radar = bullshit_radar.compute()
    except Exception:
        radar = {}

    try:
        import news_ingestor
        fg = news_ingestor.get_fear_greed()
    except Exception:
        fg = {}

    try:
        import crowd_sentiment_engine
        crowd = crowd_sentiment_engine.get_belief_vs_reality()
    except Exception:
        crowd = {}

    # Regime info from auto_trader state
    try:
        import auto_trader
        state = auto_trader.get_state()
        mkt = state.get("market_state", {})
        regime = mkt.get("state", "SLEEPING")
        quality = mkt.get("confidence_score", 0)
    except Exception:
        regime, quality = "SLEEPING", 0

    return {
        "dominant_regime": regime,
        "market_quality": quality,
        "fear_greed_value": fg.get("value"),
        "fear_greed_class": fg.get("classification", "Unknown"),
        "noise_level": radar.get("level", "clear"),
        "hype_alert": radar.get("hype_alert", False),
        "radar_summary": radar.get("summary", ""),
        "crowd_bias": crowd.get("crowd", {}).get("bias", "neutral") if isinstance(crowd.get("crowd"), dict) else "neutral",
        "crowd_alignment": crowd.get("comparison", {}).get("alignment", "unclear") if isinstance(crowd.get("comparison"), dict) else "unclear",
        "crowd_divergence": crowd.get("comparison", {}).get("divergence_score", 0) if isinstance(crowd.get("comparison"), dict) else 0,
    }


def build_activity_summary(start: str, end: str, scope: str) -> dict:
    """Section D: activity summary — trades, holds, exposure."""
    trades = _get_trades_in_range(start, end, scope)

    buys = [t for t in trades if t.get("action") == "BUY"]
    sells = [t for t in trades if t.get("action") == "SELL"]
    holds = [t for t in trades if t.get("action") == "HOLD"]

    probes = [t for t in buys if t.get("entry_type") == "probe"]
    full_entries = [t for t in buys if t.get("entry_type") == "full"]
    reentries = [t for t in buys if t.get("entry_type") == "reentry"]

    exposures = [float(t.get("exposure_pct_after", 0) or 0) for t in trades]
    avg_exposure = round(sum(exposures) / max(len(exposures), 1), 2)
    max_exposure = round(max(exposures) if exposures else 0, 2)

    return {
        "trades_taken": len(buys) + len(sells),
        "buys": len(buys),
        "sells": len(sells),
        "holds": len(holds),
        "probes": len(probes),
        "full_entries": len(full_entries),
        "reentries": len(reentries),
        "average_exposure": avg_exposure,
        "max_exposure": max_exposure,
    }


def build_performance_summary(start: str, end: str, scope: str) -> dict:
    """Section E: performance summary — PnL, win rate, drawdown."""
    trades = _get_trades_in_range(start, end, scope)
    sells = [t for t in trades if t.get("action") == "SELL"]

    pnls = [float(t.get("pnl", 0) or 0) for t in sells]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    realized_pnl = round(sum(pnls), 6)
    win_rate = round(len(wins) / max(len(pnls), 1) * 100, 1)
    avg_win = round(sum(wins) / max(len(wins), 1), 6) if wins else 0
    avg_loss = round(sum(losses) / max(len(losses), 1), 6) if losses else 0
    best_trade = round(max(pnls), 6) if pnls else 0
    worst_trade = round(min(pnls), 6) if pnls else 0

    # Max drawdown
    peak = cum = max_dd = 0.0
    for p in pnls:
        cum += p
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd

    # Equity from portfolio
    try:
        import db as v7db
        portfolio = v7db.get_lifetime_portfolio() or {}
        equity_end = float(portfolio.get("total_equity", 0) or 0)
    except Exception:
        equity_end = 0

    return {
        "realized_pnl": realized_pnl,
        "win_rate": win_rate,
        "total_sells": len(sells),
        "wins": len(wins),
        "losses": len(losses),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "best_trade": best_trade,
        "worst_trade": worst_trade,
        "max_drawdown": round(max_dd, 6),
        "equity_end": round(equity_end, 4),
    }


def build_strategy_breakdown(start: str, end: str, scope: str) -> list[dict]:
    """Section F: per-strategy breakdown."""
    trades = _get_trades_in_range(start, end, scope)
    sells = [t for t in trades if t.get("action") == "SELL"]

    strat_map: dict[str, dict] = {}
    for t in sells:
        name = t.get("strategy", "unknown")
        if name not in strat_map:
            strat_map[name] = {"name": name, "trades": 0, "pnl": 0.0, "wins": 0, "losses": 0}
        s = strat_map[name]
        s["trades"] += 1
        pnl = float(t.get("pnl", 0) or 0)
        s["pnl"] += pnl
        if pnl > 0:
            s["wins"] += 1
        elif pnl < 0:
            s["losses"] += 1

    result = []
    for s in strat_map.values():
        s["pnl"] = round(s["pnl"], 6)
        s["avg_pnl"] = round(s["pnl"] / max(s["trades"], 1), 6)
        s["win_rate"] = round(s["wins"] / max(s["trades"], 1) * 100, 1)
        result.append(s)

    result.sort(key=lambda x: x["pnl"], reverse=True)
    return result


def build_decision_quality(start: str, end: str, scope: str) -> dict:
    """Section G: decision quality assessment."""
    try:
        import db as v7db
        reflections = v7db.get_lifetime_reflections(limit=200)
    except Exception:
        reflections = []

    # Filter by date range
    reflections = [r for r in reflections if _in_range(r.get("created_at", ""), start, end)]

    good_decisions = []
    bad_decisions = []
    timing_issues = 0
    confidence_mismatches = 0

    for r in reflections:
        grade = r.get("overall_grade", "C")
        if grade in ("A", "B"):
            good_decisions.append(r.get("what_went_well", "")[:100])
        elif grade in ("D", "F"):
            bad_decisions.append(r.get("what_could_improve", "")[:100])

        timing_grade = r.get("entry_timing_grade", "C")
        if timing_grade in ("D", "F"):
            timing_issues += 1

        # Confidence mismatch: high confidence but bad outcome
        if grade in ("D", "F") and r.get("patience_impact") != "helped":
            confidence_mismatches += 1

    trades = _get_trades_in_range(start, end, scope)
    buys = [t for t in trades if t.get("action") == "BUY"]
    sells = [t for t in trades if t.get("action") == "SELL"]

    total_trades = len(buys) + len(sells)
    overtrading_sign = total_trades > 20 and len(sells) > 0 and (
        sum(1 for s in sells if float(s.get("pnl", 0) or 0) < 0) / len(sells) > 0.6
    )

    return {
        "top_good_decisions": good_decisions[:3],
        "top_bad_decisions": bad_decisions[:3],
        "timing_issues_count": timing_issues,
        "confidence_mismatch_count": confidence_mismatches,
        "overtrading_signs": overtrading_sign,
        "total_reflections": len(reflections),
        "probe_quality": "limited data" if len(reflections) < 5 else (
            "good" if timing_issues < len(reflections) * 0.3 else "needs work"
        ),
    }


def build_reflection_learning(start: str, end: str) -> dict:
    """Section H: reflection and learning summary."""
    try:
        import pattern_insight_engine
        patterns = pattern_insight_engine.compute()
    except Exception:
        patterns = {}

    try:
        import db as v7db
        journals = v7db.get_lifetime_journals(limit=50)
        journals = [j for j in journals if _in_range(j.get("created_at", ""), start, end)]
    except Exception:
        journals = []

    try:
        memories = v7db.get_lifetime_memories(limit=100)
    except Exception:
        memories = []

    # Top recurring patterns
    top_strengths = [s.get("label", "") for s in patterns.get("top_strengths", [])[:3]]
    top_mistakes = [m.get("label", "") for m in patterns.get("top_mistakes", [])[:3]]

    # Most repeated lesson from memories
    lesson_texts = [m.get("lesson_text", "") for m in memories if m.get("times_observed", 0) > 1]
    most_repeated = lesson_texts[0] if lesson_texts else "Not enough repeated lessons yet."

    # Insights from pattern engine
    insights = patterns.get("insights", [])
    key_insight = insights[0].get("insight", "") if insights else "Still gathering evidence."

    # What worked / failed from journals
    what_worked = []
    what_failed = []
    for j in journals[:5]:
        text = j.get("text", "") or j.get("lessons_text", "")
        if text:
            if any(w in text.lower() for w in ["good", "worked", "strength", "patient"]):
                what_worked.append(text[:80])
            elif any(w in text.lower() for w in ["mistake", "fail", "wrong", "poor"]):
                what_failed.append(text[:80])

    return {
        "key_insight": key_insight,
        "most_repeated_lesson": most_repeated,
        "top_recurring_strengths": top_strengths,
        "top_recurring_mistakes": top_mistakes,
        "what_worked": what_worked[:3],
        "what_failed": what_failed[:3],
        "journal_entries_in_range": len(journals),
        "warming_up": patterns.get("warming_up", True),
    }


def build_adaptation_discipline(start: str, end: str) -> dict:
    """Section I: adaptation and discipline summary."""
    try:
        import db as v7db
        adaptations = v7db.get_adaptation_journal(limit=100)
    except Exception:
        adaptations = []

    adaptations = [a for a in adaptations if _in_range(a.get("timestamp", ""), start, end)]

    allowed = [a for a in adaptations if a.get("allowed_or_blocked") == "allowed"]
    blocked = [a for a in adaptations if a.get("allowed_or_blocked") == "blocked"]

    block_reasons = Counter()
    for b in blocked:
        reason = b.get("blocked_reason", "unknown")
        block_reasons[reason] += 1

    top_block_reasons = [{"reason": r, "count": c} for r, c in block_reasons.most_common(3)]

    # Discipline guard status
    try:
        import discipline_guard
        disc = discipline_guard.get_discipline_status()
    except Exception:
        disc = {}

    return {
        "attempted_adaptations": len(adaptations),
        "allowed_adaptations": len(allowed),
        "blocked_adaptations": len(blocked),
        "top_block_reasons": top_block_reasons,
        "discipline_interventions": disc.get("total_blocks", 0),
        "system_stability": "stable" if len(blocked) >= len(allowed) and len(adaptations) > 0
                            else "adaptive" if len(allowed) > len(blocked)
                            else "quiet",
    }


def build_observer_summary(start: str, end: str) -> dict:
    """Section J: observer summary — news, radar, crowd."""
    try:
        import db as v7db
        news = v7db.get_news_analyses(limit=100)
    except Exception:
        news = []

    news = [n for n in news if _in_range(n.get("classified_at", n.get("fetched_at", "")), start, end)]

    rejected = [n for n in news if n.get("verdict") in ("reject", "noise")]
    interesting = [n for n in news if n.get("verdict") in ("interesting", "watch")]

    # Truth reviews
    try:
        truth_reviews = v7db.get_lifetime_truth_reviews(limit=50)
        truth_reviews = [t for t in truth_reviews if _in_range(t.get("created_at", ""), start, end)]
        correct = sum(1 for t in truth_reviews if t.get("verdict") == "correct")
        wrong = sum(1 for t in truth_reviews if t.get("verdict") == "wrong")
        total_graded = correct + wrong
        accuracy = round(correct / max(total_graded, 1) * 100, 1)
    except Exception:
        truth_reviews = []
        accuracy = 0
        total_graded = 0

    # Crowd events
    try:
        crowd_events = v7db.get_crowd_sentiment_events(limit=30)
        crowd_events = [c for c in crowd_events if _in_range(c.get("timestamp", ""), start, end)]
    except Exception:
        crowd_events = []

    return {
        "total_news_classified": len(news),
        "rejected_noise": len(rejected),
        "interesting_signals": len(interesting),
        "truth_reviews_in_range": len(truth_reviews),
        "truth_accuracy_pct": accuracy,
        "truth_total_graded": total_graded,
        "crowd_events_in_range": len(crowd_events),
        "observer_posture": (
            "balanced" if len(rejected) > 0 and len(interesting) > 0
            else "too skeptical" if len(rejected) > 5 and len(interesting) == 0
            else "too reactive" if len(interesting) > 5 and len(rejected) == 0
            else "quiet"
        ),
    }


def build_continuity_comparison(start: str, end: str, scope: str) -> dict:
    """Section K: compare current range vs lifetime."""
    # Current range stats
    range_trades = _get_trades_in_range(start, end, scope)
    range_sells = [t for t in range_trades if t.get("action") == "SELL"]
    range_pnls = [float(t.get("pnl", 0) or 0) for t in range_sells]
    range_pnl = sum(range_pnls)
    range_wins = sum(1 for p in range_pnls if p > 0)
    range_wr = round(range_wins / max(len(range_pnls), 1) * 100, 1)

    # Lifetime stats
    try:
        import db as v7db
        lt_stats = v7db.get_trade_stats_by_scope(scope="lifetime")
    except Exception:
        lt_stats = {}

    lt_pnl = float(lt_stats.get("total_pnl", 0) or 0)
    lt_wr = float(lt_stats.get("win_rate", 0) or 0)
    lt_trades = int(lt_stats.get("sells", 0) or 0)

    # Pattern comparison
    try:
        import pattern_insight_engine
        patterns = pattern_insight_engine.compute()
        warming = patterns.get("warming_up", True)
    except Exception:
        patterns = {}
        warming = True

    top_mistakes = [m.get("label", "") for m in patterns.get("top_mistakes", [])[:2]]
    top_strengths = [s.get("label", "") for s in patterns.get("top_strengths", [])[:2]]

    # Compute deltas
    pnl_improving = range_pnl > 0 and (lt_pnl <= 0 or range_pnl > lt_pnl / max(lt_trades, 1) * len(range_sells))
    wr_improving = range_wr > lt_wr if lt_wr > 0 else None

    # Identity depth
    try:
        identity = v7db.get_lifetime_identity() or {}
        continuity = identity.get("continuity_score", 0) or 0
    except Exception:
        continuity = 0

    if warming or lt_trades < 5:
        assessment = "Too early for meaningful comparison."
    elif pnl_improving and wr_improving:
        assessment = "This period appears to be an improvement over lifetime averages."
    elif not pnl_improving and not wr_improving:
        assessment = "This period may be underperforming relative to lifetime trends."
    elif wr_improving:
        assessment = "Win rate is improving, but PnL trails — possible sizing issue."
    else:
        assessment = "Mixed signals — some metrics improving, others flat."

    return {
        "range_pnl": round(range_pnl, 6),
        "range_win_rate": range_wr,
        "range_trades": len(range_sells),
        "lifetime_pnl": round(lt_pnl, 6),
        "lifetime_win_rate": lt_wr,
        "lifetime_trades": lt_trades,
        "pnl_improving": pnl_improving,
        "win_rate_improving": wr_improving,
        "continuity_score": continuity,
        "mistakes_recurring": len(top_mistakes) > 0,
        "strengths_stabilizing": len(top_strengths) > 0,
        "assessment": assessment,
        "identity_depth": (
            "thin" if continuity < 20
            else "forming" if continuity < 50
            else "established" if continuity < 80
            else "deep"
        ),
    }


def build_appendix(start: str, end: str, scope: str, detailed: bool = False) -> dict:
    """Section L: optional raw detail appendix."""
    if not detailed:
        return {"included": False}

    trades = _get_trades_in_range(start, end, scope)
    key_trades = []
    for t in trades:
        if t.get("action") in ("BUY", "SELL"):
            key_trades.append({
                "trade_id": t.get("trade_id"),
                "action": t.get("action"),
                "price": t.get("price"),
                "pnl": t.get("pnl", 0),
                "strategy": t.get("strategy"),
                "timestamp": t.get("timestamp"),
                "entry_type": t.get("entry_type"),
            })

    try:
        import db as v7db
        journals = v7db.get_lifetime_journals(limit=10)
        journals = [j for j in journals if _in_range(j.get("created_at", ""), start, end)]
        journal_excerpts = [{"date": j.get("created_at", "")[:10], "text": (j.get("text") or "")[:200]} for j in journals[:5]]
    except Exception:
        journal_excerpts = []

    try:
        memories = v7db.get_lifetime_memories(limit=20)
        memory_excerpts = [{"lesson": m.get("lesson_text", "")[:120], "times": m.get("times_observed", 0)} for m in memories[:5]]
    except Exception:
        memory_excerpts = []

    return {
        "included": True,
        "key_trades": key_trades[:20],
        "key_journal_entries": journal_excerpts,
        "key_memories": memory_excerpts,
    }


# ---------------------------------------------------------------------------
# Trade fetcher (with date + scope filter)
# ---------------------------------------------------------------------------

def _get_trades_in_range(start: str, end: str, scope: str) -> list[dict]:
    """Get trades within date range, respecting scope."""
    try:
        import db as v7db
        import session_manager
        sid = session_manager.get_session_id()
        version = getattr(session_manager, "APP_VERSION", "7.5.2")
    except Exception:
        return []

    try:
        trades, _ = v7db.get_trades_by_scope(
            scope=scope, session_id=sid, version=version, limit=500
        )
    except Exception:
        return []

    # Filter by date range
    return [t for t in trades if _in_range(t.get("timestamp", ""), start, end)]


# ---------------------------------------------------------------------------
# Text renderer
# ---------------------------------------------------------------------------

def render_text_export(export: dict) -> str:
    """Convert structured export to human-readable text."""
    lines = []
    h = export.get("header", {})

    lines.append("=" * 50)
    lines.append("  CryptoMind Review Export")
    lines.append("=" * 50)
    lines.append(f"  Type:      {h.get('review_type', 'daily')}")
    lines.append(f"  Scope:     {h.get('scope', 'session')}")
    lines.append(f"  Range:     {h.get('start_date', '?')} -> {h.get('end_date', '?')}")
    lines.append(f"  Version:   v{h.get('version', '?')}")
    lines.append(f"  Session:   #{h.get('session_id', 0)}")
    lines.append(f"  Generated: {h.get('generated_at', '')[:19]}")
    lines.append(f"  Lifetime:  {h.get('total_cycles_lifetime', 0)} cycles / {h.get('total_sessions_lifetime', 0)} sessions")
    lines.append("")

    # Mind State
    ms = export.get("mind_state", {})
    lines.append("--- Mind State ---")
    lines.append(f"  Level:       {ms.get('current_level', 'Seed')}")
    lines.append(f"  Score:       {ms.get('evolution_score', 0)} / 1000")
    lines.append(f"  Confidence:  {ms.get('confidence_label', 'Very Low')} ({ms.get('confidence_score', 0)}%)")
    lines.append(f"  Evidence:    {ms.get('evidence_strength_pct', 0)}%")
    lines.append(f"  Intent:      {ms.get('session_intent', 'neutral')}")
    lines.append(f"  Identity:    {ms.get('identity_status', 'forming')}")
    lines.append(f"  Continuity:  {ms.get('continuity_score', 0)}")
    lines.append("")

    # Market Context
    mc = export.get("market_context", {})
    lines.append("--- Market Context ---")
    lines.append(f"  Regime:      {mc.get('dominant_regime', 'SLEEPING')}")
    lines.append(f"  Quality:     {mc.get('market_quality', 0)}")
    lines.append(f"  Fear/Greed:  {mc.get('fear_greed_value', '?')} ({mc.get('fear_greed_class', 'Unknown')})")
    lines.append(f"  Noise:       {mc.get('noise_level', 'clear')}")
    lines.append(f"  Crowd:       {mc.get('crowd_bias', 'neutral')} (align: {mc.get('crowd_alignment', 'unclear')})")
    lines.append("")

    # Activity Summary
    act = export.get("activity_summary", {})
    lines.append("--- Activity Summary ---")
    lines.append(f"  Trades:      {act.get('trades_taken', 0)} (Buy: {act.get('buys', 0)} / Sell: {act.get('sells', 0)})")
    lines.append(f"  Holds:       {act.get('holds', 0)}")
    lines.append(f"  Probes:      {act.get('probes', 0)} / Full: {act.get('full_entries', 0)} / Re-entry: {act.get('reentries', 0)}")
    lines.append(f"  Avg Exp:     {act.get('average_exposure', 0)}%")
    lines.append(f"  Max Exp:     {act.get('max_exposure', 0)}%")
    lines.append("")

    # Performance
    perf = export.get("performance_summary", {})
    lines.append("--- Performance ---")
    lines.append(f"  Realized PnL:  ${perf.get('realized_pnl', 0)}")
    lines.append(f"  Win Rate:      {perf.get('win_rate', 0)}% ({perf.get('wins', 0)}W / {perf.get('losses', 0)}L)")
    lines.append(f"  Best Trade:    ${perf.get('best_trade', 0)}")
    lines.append(f"  Worst Trade:   ${perf.get('worst_trade', 0)}")
    lines.append(f"  Max Drawdown:  ${perf.get('max_drawdown', 0)}")
    lines.append(f"  Avg Win:       ${perf.get('avg_win', 0)}")
    lines.append(f"  Avg Loss:      ${perf.get('avg_loss', 0)}")
    lines.append("")

    # Strategy Breakdown
    strats = export.get("strategy_breakdown", [])
    if strats:
        lines.append("--- Strategy Breakdown ---")
        for s in strats:
            lines.append(f"  {s['name']:12s}  {s['trades']}T  WR:{s['win_rate']}%  PnL:${s['pnl']}")
        lines.append("")

    # Decision Quality
    dq = export.get("decision_quality", {})
    lines.append("--- Decision Quality ---")
    lines.append(f"  Reflections:   {dq.get('total_reflections', 0)}")
    lines.append(f"  Timing Issues: {dq.get('timing_issues_count', 0)}")
    lines.append(f"  Conf Mismatch: {dq.get('confidence_mismatch_count', 0)}")
    lines.append(f"  Overtrading:   {'Yes' if dq.get('overtrading_signs') else 'No'}")
    lines.append(f"  Probe Quality: {dq.get('probe_quality', 'limited data')}")
    if dq.get("top_good_decisions"):
        lines.append(f"  Good: {dq['top_good_decisions'][0]}")
    if dq.get("top_bad_decisions"):
        lines.append(f"  Bad:  {dq['top_bad_decisions'][0]}")
    lines.append("")

    # Reflection & Learning
    rl = export.get("reflection_learning", {})
    lines.append("--- Reflection & Learning ---")
    lines.append(f"  Key Insight:     {rl.get('key_insight', 'Still gathering evidence.')}")
    lines.append(f"  Repeated Lesson: {rl.get('most_repeated_lesson', 'Not enough data.')}")
    if rl.get("top_recurring_strengths"):
        lines.append(f"  Strengths:       {', '.join(rl['top_recurring_strengths'])}")
    if rl.get("top_recurring_mistakes"):
        lines.append(f"  Mistakes:        {', '.join(rl['top_recurring_mistakes'])}")
    lines.append("")

    # Adaptation & Discipline
    ad = export.get("adaptation_discipline", {})
    lines.append("--- Adaptation & Discipline ---")
    lines.append(f"  Attempted:     {ad.get('attempted_adaptations', 0)}")
    lines.append(f"  Allowed:       {ad.get('allowed_adaptations', 0)}")
    lines.append(f"  Blocked:       {ad.get('blocked_adaptations', 0)}")
    lines.append(f"  Stability:     {ad.get('system_stability', 'quiet')}")
    if ad.get("top_block_reasons"):
        for br in ad["top_block_reasons"]:
            lines.append(f"    Block: {br['reason']} ({br['count']}x)")
    lines.append("")

    # Observer Summary
    obs = export.get("observer_summary", {})
    lines.append("--- Observer Summary ---")
    lines.append(f"  News Classified: {obs.get('total_news_classified', 0)}")
    lines.append(f"  Rejected Noise:  {obs.get('rejected_noise', 0)}")
    lines.append(f"  Signals Found:   {obs.get('interesting_signals', 0)}")
    lines.append(f"  Truth Accuracy:  {obs.get('truth_accuracy_pct', 0)}% ({obs.get('truth_total_graded', 0)} graded)")
    lines.append(f"  Posture:         {obs.get('observer_posture', 'quiet')}")
    lines.append("")

    # Continuity Comparison
    cc = export.get("continuity_comparison", {})
    lines.append("--- Continuity vs Lifetime ---")
    lines.append(f"  Range PnL:     ${cc.get('range_pnl', 0)}  |  Lifetime: ${cc.get('lifetime_pnl', 0)}")
    lines.append(f"  Range WR:      {cc.get('range_win_rate', 0)}%  |  Lifetime: {cc.get('lifetime_win_rate', 0)}%")
    lines.append(f"  PnL Improving: {'Yes' if cc.get('pnl_improving') else 'No'}")
    lines.append(f"  WR Improving:  {'Yes' if cc.get('win_rate_improving') else 'Unknown' if cc.get('win_rate_improving') is None else 'No'}")
    lines.append(f"  Identity:      {cc.get('identity_depth', 'thin')}")
    lines.append(f"  Assessment:    {cc.get('assessment', 'Too early.')}")
    lines.append("")

    # Appendix
    appendix = export.get("appendix", {})
    if appendix.get("included"):
        lines.append("--- Appendix ---")
        for t in (appendix.get("key_trades") or [])[:10]:
            lines.append(f"  #{t.get('trade_id', '?')} {t.get('action', '?')} @ ${t.get('price', 0)} PnL:${t.get('pnl', 0)} [{t.get('strategy', '?')}]")
        lines.append("")

    lines.append("=" * 50)
    lines.append("  Same mind. Same memory. Different window.")
    lines.append("=" * 50)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_export(review_type: str = "daily", scope: str = "session",
                    mode: str = "summary", start_date: str = None,
                    end_date: str = None) -> dict:
    """Generate a full review export.

    Args:
        review_type: daily / weekly / monthly / custom
        scope: session / version / lifetime
        mode: summary / detailed
        start_date: ISO date string (for custom, or override)
        end_date: ISO date string (for custom, or override)

    Returns:
        Structured export dict with all sections + rendered text.
    """
    global _cache, _cache_ts

    cache_key = f"{review_type}:{scope}:{mode}:{start_date}:{end_date}"
    now = time.time()
    if cache_key in _cache and (now - _cache_ts) < _CACHE_TTL:
        return _cache[cache_key]

    start, end = _resolve_dates(review_type, start_date, end_date)
    detailed = mode == "detailed"

    export = {
        "header": build_header(review_type, scope, start, end),
        "mind_state": build_mind_state(),
        "market_context": build_market_context(start, end),
        "activity_summary": build_activity_summary(start, end, scope),
        "performance_summary": build_performance_summary(start, end, scope),
        "strategy_breakdown": build_strategy_breakdown(start, end, scope),
        "decision_quality": build_decision_quality(start, end, scope),
        "reflection_learning": build_reflection_learning(start, end),
        "adaptation_discipline": build_adaptation_discipline(start, end),
        "observer_summary": build_observer_summary(start, end),
        "continuity_comparison": build_continuity_comparison(start, end, scope),
        "appendix": build_appendix(start, end, scope, detailed),
    }

    # Low-data honesty
    act = export["activity_summary"]
    perf = export["performance_summary"]
    if act.get("trades_taken", 0) == 0 and perf.get("total_sells", 0) == 0:
        export["low_data_warning"] = "No trades in this range. Review reflects system state only."
    elif perf.get("total_sells", 0) < 3:
        export["low_data_warning"] = "Very few closed trades. Conclusions should be held lightly."

    # Render text
    export["text_export"] = render_text_export(export)

    _cache[cache_key] = export
    _cache_ts = now
    return export
