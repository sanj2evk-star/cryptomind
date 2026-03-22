"""
positioning_interpreter.py — Interprets derivatives positioning signals.

Reads funding rates, OI changes, and LS ratios to determine whether the
market is over-leveraged, under-leveraged, or balanced.

Observer-only — NEVER influences trades.
"""

from __future__ import annotations


def interpret(signals: list[dict]) -> dict | None:
    """Interpret derivatives signals into a positioning assessment.

    Returns a dict with:
      - positioning: "overcrowded_long" | "overcrowded_short" | "balanced" | "building"
      - risk_level: "low" | "moderate" | "high" | "extreme"
      - leverage_bias: "bullish" | "bearish" | "neutral"
      - narrative: human-readable explanation
      - confidence: 0.0 – 1.0
    """
    deriv = [s for s in signals if s.get("source") == "derivatives"]
    if not deriv:
        return None

    # Extract sub-signals
    funding = [s for s in deriv if s["signal_type"] == "funding_rate"]
    oi = [s for s in deriv if s["signal_type"] == "oi_change"]
    ls = [s for s in deriv if s["signal_type"] == "long_short_ratio"]

    # Weighted direction score: -1 (bearish) to +1 (bullish)
    score = 0.0
    weight_sum = 0.0

    for s in funding:
        w = 0.4
        val = 1.0 if s["direction"] == "bullish" else -1.0 if s["direction"] == "bearish" else 0.0
        score += val * s["strength"] * w
        weight_sum += w

    for s in oi:
        w = 0.35
        val = 1.0 if s["direction"] == "bullish" else -1.0 if s["direction"] == "bearish" else 0.0
        score += val * s["strength"] * w
        weight_sum += w

    for s in ls:
        w = 0.25
        val = 1.0 if s["direction"] == "bullish" else -1.0 if s["direction"] == "bearish" else 0.0
        score += val * s["strength"] * w
        weight_sum += w

    if weight_sum == 0:
        return None

    score /= weight_sum
    avg_strength = sum(s["strength"] for s in deriv) / len(deriv)
    avg_conf = sum(s["confidence"] for s in deriv) / len(deriv)

    # Classify positioning
    if score > 0.5 and avg_strength > 0.6:
        positioning = "overcrowded_long"
        risk = "high"
        leverage_bias = "bullish"
        narrative = "Longs are overcrowded — high risk of long squeeze if price drops."
    elif score < -0.5 and avg_strength > 0.6:
        positioning = "overcrowded_short"
        risk = "high"
        leverage_bias = "bearish"
        narrative = "Shorts are overcrowded — high risk of short squeeze if price rises."
    elif abs(score) > 0.3:
        positioning = "building"
        risk = "moderate"
        leverage_bias = "bullish" if score > 0 else "bearish"
        narrative = f"Positions building {'long' if score > 0 else 'short'} — not extreme yet."
    else:
        positioning = "balanced"
        risk = "low"
        leverage_bias = "neutral"
        narrative = "Derivatives positioning is balanced — no crowding detected."

    # Extreme funding + extreme LS = very high risk
    if funding and ls:
        f_str = max(s["strength"] for s in funding)
        l_str = max(s["strength"] for s in ls)
        if f_str > 0.7 and l_str > 0.7:
            risk = "extreme"
            narrative = "Extreme leverage + extreme ratio — liquidation cascade risk is very high."

    return {
        "interpretation": "positioning",
        "positioning": positioning,
        "risk_level": risk,
        "leverage_bias": leverage_bias,
        "direction_score": round(score, 3),
        "avg_strength": round(avg_strength, 3),
        "confidence": round(avg_conf, 3),
        "narrative": narrative,
        "signal_count": len(deriv),
    }
