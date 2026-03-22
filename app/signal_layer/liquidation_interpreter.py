"""
liquidation_interpreter.py — Interprets liquidation event signals.

Assesses whether recent liquidations indicate a squeeze, flush, or
normal market movement.

Observer-only — NEVER influences trades.
"""

from __future__ import annotations


def interpret(signals: list[dict]) -> dict | None:
    """Interpret liquidation signals.

    Returns a dict with:
      - event_type: "long_squeeze" | "short_squeeze" | "mixed_flush" | "calm"
      - severity: "negligible" | "minor" | "major" | "extreme"
      - total_liquidated_m: estimated total in millions USD
      - narrative: human-readable explanation
      - confidence: 0.0 – 1.0
    """
    liqs = [s for s in signals if s.get("source") == "liquidation"]
    if not liqs:
        return None

    long_liqs = [s for s in liqs if s["signal_type"] == "long_liquidation"]
    short_liqs = [s for s in liqs if s["signal_type"] == "short_liquidation"]

    total_long = sum(s["raw_value"] for s in long_liqs)
    total_short = sum(s["raw_value"] for s in short_liqs)
    total = total_long + total_short

    if total < 1:
        return None

    # Classify event
    if total_long > total_short * 2:
        event_type = "long_squeeze"
        direction = "bearish"
    elif total_short > total_long * 2:
        event_type = "short_squeeze"
        direction = "bullish"
    elif total > 10:
        event_type = "mixed_flush"
        direction = "neutral"
    else:
        event_type = "calm"
        direction = "neutral"

    # Severity
    max_severity = max((s.get("meta", {}).get("severity", "negligible") for s in liqs), key=lambda x: {"extreme": 4, "major": 3, "minor": 2, "negligible": 1}.get(x, 0))

    # Avg strength and confidence
    avg_strength = sum(s["strength"] for s in liqs) / len(liqs)
    avg_conf = sum(s["confidence"] for s in liqs) / len(liqs)

    # Narrative
    if event_type == "long_squeeze":
        narrative = f"Long squeeze: ~${total_long:.0f}M liquidated — overleveraged longs got flushed."
    elif event_type == "short_squeeze":
        narrative = f"Short squeeze: ~${total_short:.0f}M liquidated — shorts got squeezed out."
    elif event_type == "mixed_flush":
        narrative = f"Mixed liquidation event: ~${total:.0f}M total — both sides getting flushed."
    else:
        narrative = f"Minor liquidation activity: ~${total:.0f}M — nothing unusual."

    # Post-squeeze interpretation
    if max_severity in ("major", "extreme"):
        if event_type == "long_squeeze":
            narrative += " Post-flush: overleveraged longs cleared, potential relief rally."
        elif event_type == "short_squeeze":
            narrative += " Post-flush: shorts cleared, momentum may continue upward."

    return {
        "interpretation": "liquidation",
        "event_type": event_type,
        "severity": max_severity,
        "direction": direction,
        "total_liquidated_m": round(total, 1),
        "long_liquidated_m": round(total_long, 1),
        "short_liquidated_m": round(total_short, 1),
        "avg_strength": round(avg_strength, 3),
        "confidence": round(avg_conf, 3),
        "narrative": narrative,
        "signal_count": len(liqs),
    }
