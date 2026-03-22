"""
crowd_interpreter.py — Interprets prediction market / crowd signals.

Reads Polymarket-style signals to assess crowd conviction, direction,
and potential divergence from price reality.

Observer-only — NEVER influences trades.
"""

from __future__ import annotations


def interpret(signals: list[dict]) -> dict | None:
    """Interpret crowd/prediction market signals.

    Returns a dict with:
      - crowd_conviction: "strong" | "moderate" | "weak" | "conflicted"
      - crowd_direction: "bullish" | "bearish" | "neutral"
      - divergence_risk: "none" | "low" | "moderate" | "high"
      - narrative: human-readable explanation
      - confidence: 0.0 – 1.0
    """
    poly = [s for s in signals if s.get("source") == "polymarket"]
    if not poly:
        return None

    predictions = [s for s in poly if s["signal_type"] == "btc_price_prediction"]
    divergences = [s for s in poly if s["signal_type"] == "crowd_divergence"]

    if not predictions:
        return None

    # Main prediction signal
    main = predictions[0]
    direction = main["direction"]
    strength = main["strength"]
    prob = main.get("meta", {}).get("crowd_probability", 50)

    # Conviction classification
    if strength > 0.7:
        conviction = "strong"
    elif strength > 0.4:
        conviction = "moderate"
    elif strength > 0.2:
        conviction = "weak"
    else:
        conviction = "conflicted"

    # Divergence assessment
    div_risk = "none"
    div_score = 0
    if divergences:
        div_signal = divergences[0]
        div_score = div_signal.get("meta", {}).get("divergence_score", 0)
        if div_score > 70:
            div_risk = "high"
        elif div_score > 50:
            div_risk = "moderate"
        elif div_score > 30:
            div_risk = "low"

    # Narrative
    if div_risk == "high":
        narrative = f"Crowd is {conviction}ly {direction} ({prob:.0f}% conviction) but reality diverges sharply — contrarian signal."
    elif div_risk == "moderate":
        narrative = f"Crowd leans {direction} ({prob:.0f}%) with some divergence from price — watching closely."
    elif conviction == "strong":
        narrative = f"Crowd strongly {direction} at {prob:.0f}% — high conviction, aligned with positioning."
    elif conviction == "weak" or conviction == "conflicted":
        narrative = f"Crowd is uncertain — {prob:.0f}% probability, weak conviction. Market lacks clear narrative."
    else:
        narrative = f"Crowd moderately {direction} at {prob:.0f}% — reasonable conviction."

    # Overall confidence
    conf = main["confidence"]
    if divergences:
        conf = conf * 0.8  # reduce confidence when divergence present

    return {
        "interpretation": "crowd",
        "crowd_conviction": conviction,
        "crowd_direction": direction,
        "crowd_probability": round(prob, 1),
        "divergence_risk": div_risk,
        "divergence_score": div_score,
        "confidence": round(conf, 3),
        "narrative": narrative,
        "signal_count": len(poly),
    }
