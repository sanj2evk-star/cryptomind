"""
decision_engine.py - Deterministic decision combiner.

Accepts decisions from multiple strategy bots and a risk manager
verdict, then produces a single final action using fixed rules:

1. Both bots agree (same action)  → strong signal, average confidence.
2. One acts, the other HOLDs      → weak signal, reduced confidence.
3. Bots conflict (BUY vs SELL)    → forced HOLD.
4. Risk manager can veto any action back to HOLD.
"""

# Confidence penalty when only one bot supports the action
WEAK_SIGNAL_PENALTY = 0.5


def combine_decisions(trend: dict, mean_rev: dict) -> dict:
    """Combine Trend Bot and Mean Reversion Bot decisions.

    Rules (deterministic, no randomness):
    - Both agree on BUY/SELL  → strong signal, confidence = average of both.
    - One acts, other HOLDs   → weak signal, confidence = actor's * penalty.
    - Both HOLD               → HOLD, confidence = max of both.
    - Conflict (BUY vs SELL)  → HOLD, confidence = 0.

    Args:
        trend: Trend Bot decision dict.
        mean_rev: Mean Reversion Bot decision dict.

    Returns:
        Combined decision dict with action, confidence, reasoning, signals.
    """
    t_action = trend.get("action", "HOLD").upper()
    m_action = mean_rev.get("action", "HOLD").upper()
    t_conf = float(trend.get("confidence", 0.0))
    m_conf = float(mean_rev.get("confidence", 0.0))

    t_signals = trend.get("signals", [])
    m_signals = mean_rev.get("signals", [])
    all_signals = list(set(
        (t_signals if isinstance(t_signals, list) else [])
        + (m_signals if isinstance(m_signals, list) else [])
    ))

    # Both HOLD
    if t_action == "HOLD" and m_action == "HOLD":
        return {
            "action": "HOLD",
            "confidence": max(t_conf, m_conf),
            "reasoning": "Both bots recommend HOLD.",
            "signals": all_signals,
            "risk": trend.get("risk", "N/A"),
            "strength": "none",
        }

    # Both agree on BUY or SELL → strong signal
    if t_action == m_action:
        return {
            "action": t_action,
            "confidence": round((t_conf + m_conf) / 2, 4),
            "reasoning": f"Both bots agree on {t_action}.",
            "signals": all_signals,
            "risk": trend.get("risk", mean_rev.get("risk", "N/A")),
            "strength": "strong",
        }

    # One acts, the other HOLDs → weak signal
    if t_action != "HOLD" and m_action == "HOLD":
        return {
            "action": t_action,
            "confidence": round(t_conf * WEAK_SIGNAL_PENALTY, 4),
            "reasoning": f"Only Trend Bot suggests {t_action}; Mean Rev is neutral.",
            "signals": all_signals,
            "risk": trend.get("risk", "N/A"),
            "strength": "weak",
        }

    if m_action != "HOLD" and t_action == "HOLD":
        return {
            "action": m_action,
            "confidence": round(m_conf * WEAK_SIGNAL_PENALTY, 4),
            "reasoning": f"Only Mean Rev Bot suggests {m_action}; Trend is neutral.",
            "signals": all_signals,
            "risk": mean_rev.get("risk", "N/A"),
            "strength": "weak",
        }

    # Conflict: BUY vs SELL → forced HOLD
    return {
        "action": "HOLD",
        "confidence": 0.0,
        "reasoning": f"Conflict: Trend={t_action}, MeanRev={m_action}. Forced HOLD.",
        "signals": all_signals,
        "risk": "N/A",
        "strength": "conflict",
    }


def apply_risk_verdict(decision: dict, verdict: dict) -> dict:
    """Apply the Risk Manager's verdict to the combined decision.

    If the Risk Manager rejects, the action is forced to HOLD.
    If the decision is already HOLD, the verdict is irrelevant.

    Args:
        decision: Combined decision from combine_decisions().
        verdict: Risk Manager verdict dict with 'approved' (bool).

    Returns:
        Final decision dict, potentially overridden to HOLD.
    """
    if decision["action"] == "HOLD":
        return decision

    if verdict.get("approved", False):
        decision["reasoning"] += " Risk Manager: APPROVED."
        return decision

    return {
        "action": "HOLD",
        "confidence": 0.0,
        "reasoning": f"Risk Manager VETOED: {verdict.get('reasoning', 'no reason given')}",
        "signals": decision.get("signals", []),
        "risk": decision.get("risk", "N/A"),
        "strength": "vetoed",
    }


def resolve(trend: dict, mean_rev: dict, verdict: dict, market_condition: str = "unknown") -> dict:
    """Full pipeline: combine bot decisions, apply risk verdict, tag metadata.

    Args:
        trend: Trend Bot decision dict.
        mean_rev: Mean Reversion Bot decision dict.
        verdict: Risk Manager verdict dict.
        market_condition: Current market condition (e.g. 'upward', 'downward', 'sideways').

    Returns:
        Final decision dict ready for paper_broker.execute_trade().
    """
    combined = combine_decisions(trend, mean_rev)
    final = apply_risk_verdict(combined, verdict)
    final["market_condition"] = market_condition
    return final
