"""
signal_aggregator.py — Collects from all sources, normalizes, interprets, stores.

This is the main orchestrator of the signal layer pipeline:
  collectors → normalizer (already applied in collectors) → interpreters → store → output

Called periodically (every ~60s) by the main loop or on-demand by API.

Observer-only — NEVER influences trades.
"""

from __future__ import annotations

import time
import threading
from datetime import datetime, timezone

from signal_layer import ENABLE_SIGNAL_LAYER
from signal_layer.polymarket_collector import collect as collect_polymarket
from signal_layer.derivatives_collector import collect as collect_derivatives
from signal_layer.liquidation_collector import collect as collect_liquidation
from signal_layer.positioning_interpreter import interpret as interpret_positioning
from signal_layer.crowd_interpreter import interpret as interpret_crowd
from signal_layer.liquidation_interpreter import interpret as interpret_liquidation
from signal_layer.signal_store import insert_signal_event

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_CACHE_TTL = 45  # seconds
_lock = threading.Lock()
_cache: dict | None = None
_cache_ts: float = 0
_last_persist_ts: float = 0
_PERSIST_INTERVAL = 120  # seconds between DB writes


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def aggregate() -> dict:
    """Run the full signal pipeline and return aggregated result.

    Returns dict with:
      - signals: list of all raw normalized signals
      - interpretations: dict of interpreter outputs (positioning, crowd, liquidation)
      - composite: overall signal assessment
      - timestamp: when this was computed
    """
    global _cache, _cache_ts

    if not ENABLE_SIGNAL_LAYER:
        return {"enabled": False, "signals": [], "interpretations": {}, "composite": {}}

    now = time.time()
    if _cache and (now - _cache_ts) < _CACHE_TTL:
        return _cache

    with _lock:
        # Collect from all sources
        all_signals = []
        all_signals.extend(collect_polymarket())
        all_signals.extend(collect_derivatives())
        all_signals.extend(collect_liquidation())

        if not all_signals:
            result = {
                "enabled": True,
                "warming_up": True,
                "signals": [],
                "signal_count": 0,
                "interpretations": {},
                "composite": {
                    "overall_direction": "neutral",
                    "tension_score": 0,
                    "narrative_state": "calm",
                    "alignment": "unclear",
                    "confidence": 0.0,
                    "summary": "Signal layer warming up — not enough data yet.",
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            _cache = result
            _cache_ts = now
            return result

        # Interpret
        positioning = interpret_positioning(all_signals)
        crowd = interpret_crowd(all_signals)
        liquidation = interpret_liquidation(all_signals)

        interpretations = {}
        if positioning:
            interpretations["positioning"] = positioning
        if crowd:
            interpretations["crowd"] = crowd
        if liquidation:
            interpretations["liquidation"] = liquidation

        # Composite assessment
        composite = _build_composite(all_signals, interpretations)

        # Persist to DB periodically
        _maybe_persist(all_signals)

        result = {
            "enabled": True,
            "warming_up": False,
            "signals": all_signals,
            "signal_count": len(all_signals),
            "interpretations": interpretations,
            "composite": composite,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        _cache = result
        _cache_ts = now
        return result


def _build_composite(signals: list[dict], interps: dict) -> dict:
    """Build a composite assessment from all interpretations."""

    # Direction consensus
    directions = [s["direction"] for s in signals]
    bullish = sum(1 for d in directions if d == "bullish")
    bearish = sum(1 for d in directions if d == "bearish")
    total = len(directions)

    if total == 0:
        return {
            "overall_direction": "neutral",
            "tension_score": 0,
            "narrative_state": "calm",
            "alignment": "unclear",
            "confidence": 0.0,
            "summary": "No signal data available.",
        }

    bull_ratio = bullish / total
    bear_ratio = bearish / total

    if bull_ratio > 0.6:
        overall_dir = "bullish"
    elif bear_ratio > 0.6:
        overall_dir = "bearish"
    else:
        overall_dir = "mixed"

    # Tension score (0-100): how stressed is the market?
    avg_strength = sum(s["strength"] for s in signals) / total
    tension = int(avg_strength * 100)

    # Check for conflicting signals (high tension)
    if bullish > 0 and bearish > 0:
        conflict_ratio = min(bullish, bearish) / max(bullish, bearish)
        tension = int(tension * (1 + conflict_ratio * 0.5))
    tension = min(100, tension)

    # Narrative state
    pos = interps.get("positioning", {})
    liq = interps.get("liquidation", {})
    risk = pos.get("risk_level", "low") if pos else "low"

    if tension > 70 or risk in ("extreme", "high"):
        narrative = "overheated"
    elif tension > 45 or risk == "moderate":
        narrative = "building"
    elif bullish > 0 and bearish > 0 and abs(bullish - bearish) <= 1:
        narrative = "conflicted"
    else:
        narrative = "calm"

    # Alignment: do all sources agree?
    unique_dirs = set(s["direction"] for s in signals if s["direction"] != "neutral")
    if len(unique_dirs) <= 1:
        alignment = "aligned"
    elif len(unique_dirs) == 2 and bull_ratio > 0.3 and bear_ratio > 0.3:
        alignment = "diverging"
    else:
        alignment = "unclear"

    # Confidence
    avg_conf = sum(s["confidence"] for s in signals) / total

    # Summary
    parts = []
    if crowd := interps.get("crowd"):
        parts.append(f"Crowd {crowd['crowd_direction']} ({crowd['crowd_conviction']})")
    if pos:
        parts.append(f"positioning {pos['positioning'].replace('_', ' ')}")
    if liq:
        parts.append(f"{liq['event_type'].replace('_', ' ')}")
    summary = " · ".join(parts) if parts else "Gathering signal data."

    return {
        "overall_direction": overall_dir,
        "bullish_signals": bullish,
        "bearish_signals": bearish,
        "neutral_signals": total - bullish - bearish,
        "tension_score": tension,
        "narrative_state": narrative,
        "alignment": alignment,
        "confidence": round(avg_conf, 3),
        "summary": summary,
    }


def _maybe_persist(signals: list[dict]) -> None:
    """Persist signals to DB at intervals (not every call)."""
    global _last_persist_ts
    now = time.time()
    if (now - _last_persist_ts) < _PERSIST_INTERVAL:
        return
    _last_persist_ts = now

    for s in signals:
        try:
            insert_signal_event(
                source=s["source"],
                signal_type=s["signal_type"],
                direction=s["direction"],
                strength=s["strength"],
                confidence=s["confidence"],
                raw_value=s["raw_value"],
                context=s["context"],
                meta=s.get("meta"),
            )
        except Exception:
            pass
