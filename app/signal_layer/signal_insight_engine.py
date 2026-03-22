"""
signal_insight_engine.py — Generates human-readable narratives from signals.

Produces insights for the Mind Feed, Lab panel, and context summary.
Focuses on what's interesting, what's unusual, and what the user should
pay attention to.

Observer-only — NEVER influences trades.
"""

from __future__ import annotations

import time
import threading
from datetime import datetime, timezone

from signal_layer.signal_aggregator import aggregate

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_CACHE_TTL = 60
_lock = threading.Lock()
_cache: list[dict] = []
_cache_ts: float = 0


# ---------------------------------------------------------------------------
# Insight generation
# ---------------------------------------------------------------------------

def generate_insights() -> list[dict]:
    """Generate a list of signal insights from current aggregated state.

    Each insight is:
      - type: "signal_alignment" | "signal_divergence" | "signal_warning" | "signal_info"
      - title: short headline
      - detail: explanation
      - importance: 1-10
      - source: which signal source triggered it
    """
    global _cache, _cache_ts

    now = time.time()
    if _cache and (now - _cache_ts) < _CACHE_TTL:
        return _cache

    with _lock:
        agg = aggregate()

        if not agg.get("enabled") or agg.get("warming_up"):
            _cache = [{
                "type": "signal_info",
                "title": "Signal Layer Warming Up",
                "detail": "Collecting initial positioning data. Insights will appear once enough signals arrive.",
                "importance": 2,
                "source": "system",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }]
            _cache_ts = now
            return _cache

        insights = []
        interps = agg.get("interpretations", {})
        composite = agg.get("composite", {})

        # 1. Overall alignment insight
        alignment = composite.get("alignment", "unclear")
        tension = composite.get("tension_score", 0)
        narrative = composite.get("narrative_state", "calm")

        if alignment == "aligned":
            direction = composite.get("overall_direction", "neutral")
            insights.append({
                "type": "signal_alignment",
                "title": f"Signals Aligned {direction.title()}",
                "detail": f"All signal sources agree: {direction}. Tension: {tension}/100. Narrative: {narrative}.",
                "importance": 6 if tension < 50 else 7,
                "source": "composite",
            })
        elif alignment == "diverging":
            insights.append({
                "type": "signal_divergence",
                "title": "Signal Divergence Detected",
                "detail": f"Sources disagree on direction. Tension: {tension}/100. This often precedes sharp moves.",
                "importance": 8,
                "source": "composite",
            })

        # 2. Positioning risk
        pos = interps.get("positioning")
        if pos:
            risk = pos.get("risk_level", "low")
            if risk in ("high", "extreme"):
                insights.append({
                    "type": "signal_warning",
                    "title": f"Leverage Risk: {risk.title()}",
                    "detail": pos.get("narrative", "High leverage detected."),
                    "importance": 9 if risk == "extreme" else 7,
                    "source": "derivatives",
                })
            elif pos.get("positioning") in ("overcrowded_long", "overcrowded_short"):
                insights.append({
                    "type": "signal_warning",
                    "title": f"Overcrowded {pos['positioning'].split('_')[1].title()}s",
                    "detail": pos.get("narrative", "Position crowding detected."),
                    "importance": 6,
                    "source": "derivatives",
                })

        # 3. Crowd divergence
        crowd = interps.get("crowd")
        if crowd:
            div_risk = crowd.get("divergence_risk", "none")
            if div_risk in ("moderate", "high"):
                insights.append({
                    "type": "signal_divergence",
                    "title": f"Crowd Divergence: {div_risk.title()}",
                    "detail": crowd.get("narrative", "Crowd belief doesn't match price."),
                    "importance": 7 if div_risk == "high" else 5,
                    "source": "polymarket",
                })

        # 4. Liquidation events
        liq = interps.get("liquidation")
        if liq:
            sev = liq.get("severity", "negligible")
            if sev in ("major", "extreme"):
                insights.append({
                    "type": "signal_warning",
                    "title": f"Liquidation: {liq['event_type'].replace('_', ' ').title()}",
                    "detail": liq.get("narrative", "Significant liquidation event."),
                    "importance": 8 if sev == "extreme" else 6,
                    "source": "liquidation",
                })

        # 5. Overheated narrative
        if narrative == "overheated":
            insights.append({
                "type": "signal_warning",
                "title": "Market Overheated",
                "detail": f"Signal tension at {tension}/100. Multiple sources showing extreme readings. Caution warranted.",
                "importance": 8,
                "source": "composite",
            })

        # Add timestamps
        ts = datetime.now(timezone.utc).isoformat()
        for i in insights:
            i["timestamp"] = ts

        # Sort by importance (highest first), cap at 5
        insights.sort(key=lambda x: x.get("importance", 0), reverse=True)
        insights = insights[:5]

        _cache = insights
        _cache_ts = now
        return insights


def get_oneliner() -> str:
    """Return a single-line signal summary for compact displays."""
    agg = aggregate()
    composite = agg.get("composite", {})
    return composite.get("summary", "Signal layer warming up.")
