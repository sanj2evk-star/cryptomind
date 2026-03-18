"""
meta_engine.py - Meta decision engine.

Combines three signal sources into one final trading decision:
1. Rule-based: Claude bots + decision engine (trend/mean rev/risk manager)
2. RL agent: Q-learning recommendation from learned state-action values
3. Historical: strategy performance in current regime from strategy_store

Each source votes on BUY / SELL / HOLD with a weight.
The meta engine tallies weighted votes, picks the winning action,
computes blended confidence, and returns a fully explainable decision.

Usage:
    from meta_engine import meta_decide
    decision = meta_decide(rule_decision, rl_signal, history_signal)
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Source weights (must sum to 1.0)
# ---------------------------------------------------------------------------

RULE_WEIGHT = 0.50      # Claude bots + decision engine
RL_WEIGHT = 0.20        # Q-learning agent
HISTORY_WEIGHT = 0.30   # Strategy store track record

# Minimum combined confidence to allow a trade
MIN_META_CONFIDENCE = 0.55

ACTIONS = ["BUY", "SELL", "HOLD"]


# ---------------------------------------------------------------------------
# Signal builders
# ---------------------------------------------------------------------------

def build_rule_signal(decision: dict) -> dict:
    """Extract a normalized signal from the rule-based decision.

    Args:
        decision: Output from decision_engine.resolve().

    Returns:
        Signal dict with action, confidence, source.
    """
    return {
        "source": "rules",
        "action": decision.get("action", "HOLD"),
        "confidence": float(decision.get("confidence", 0.0)),
        "detail": decision.get("reasoning", ""),
    }


def build_rl_signal(
    rl_action: int,
    rl_q_values: list[float],
    agent_ready: bool,
) -> dict:
    """Extract a normalized signal from the RL agent.

    Converts Q-values into a confidence estimate. If the agent
    isn't ready, returns a neutral HOLD signal with zero weight.

    Args:
        rl_action: Agent's greedy action index (0=BUY, 1=SELL, 2=HOLD).
        rl_q_values: Q-values for [BUY, SELL, HOLD].
        agent_ready: Whether the agent has sufficient experience.

    Returns:
        Signal dict with action, confidence, source.
    """
    if not agent_ready:
        return {
            "source": "rl",
            "action": "HOLD",
            "confidence": 0.0,
            "detail": "Agent not ready (insufficient experience).",
        }

    action_str = ACTIONS[rl_action]

    # Derive confidence from Q-value spread
    max_q = max(rl_q_values)
    min_q = min(rl_q_values)
    q_range = max_q - min_q if max_q != min_q else 0.0

    # Normalize spread to 0-1 confidence (capped at 0.9)
    confidence = min(q_range * 5, 0.9)

    return {
        "source": "rl",
        "action": action_str,
        "confidence": round(confidence, 4),
        "detail": f"Q={[round(v, 4) for v in rl_q_values]}",
    }


def build_history_signal(strategy: dict | None, regime: str) -> dict:
    """Extract a signal from historical strategy performance in this regime.

    If the strategy has a good track record in the current regime,
    it signals confidence. If poor, it signals caution (HOLD).

    Args:
        strategy: Strategy dict from strategy_store.load_best(), or None.
        regime: Current market regime string.

    Returns:
        Signal dict with action, confidence, source.
    """
    if strategy is None:
        return {
            "source": "history",
            "action": "HOLD",
            "confidence": 0.0,
            "detail": "No strategy history available.",
        }

    regime_stats = strategy.get("regime_stats", {}).get(regime, {})
    wins = regime_stats.get("wins", 0)
    losses = regime_stats.get("losses", 0)
    total = wins + losses

    if total < 2:
        return {
            "source": "history",
            "action": "HOLD",
            "confidence": 0.0,
            "detail": f"Insufficient data for {regime} ({total} trades).",
        }

    win_rate = wins / total
    pnl = regime_stats.get("total_pnl", 0.0)

    # Good track record → support trading, poor → recommend HOLD
    if win_rate >= 0.6 and pnl > 0:
        action = "TRADE"  # supports whatever the rule-based system decides
        confidence = round(win_rate * 0.9, 4)
        detail = f"{regime}: {wins}W/{losses}L ({win_rate:.0%}), PnL ${pnl:.4f}"
    else:
        action = "HOLD"
        confidence = round((1 - win_rate) * 0.7, 4)
        detail = f"{regime}: {wins}W/{losses}L ({win_rate:.0%}), PnL ${pnl:.4f} — caution"

    return {
        "source": "history",
        "action": action,
        "confidence": confidence,
        "detail": detail,
    }


# ---------------------------------------------------------------------------
# Meta decision
# ---------------------------------------------------------------------------

def meta_decide(
    rule_signal: dict,
    rl_signal: dict,
    history_signal: dict,
) -> dict:
    """Combine all signal sources into one final decision.

    Voting system:
    - Each source votes for an action with weighted confidence.
    - History's "TRADE" vote supports the rule-based action.
    - Votes are tallied per action. Highest weighted score wins.
    - If winning action is BUY/SELL, blended confidence must exceed
      MIN_META_CONFIDENCE or it falls back to HOLD.

    Args:
        rule_signal: From build_rule_signal().
        rl_signal: From build_rl_signal().
        history_signal: From build_history_signal().

    Returns:
        Final decision dict with:
            action, confidence, reasoning,
            signals (list), meta_trace (full explanation).
    """
    rule_action = rule_signal["action"]
    rl_action = rl_signal["action"]
    hist_action = history_signal["action"]

    # History's "TRADE" inherits the rule-based action
    if hist_action == "TRADE":
        hist_action = rule_action if rule_action != "HOLD" else "HOLD"

    # Tally weighted votes per action
    votes = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0}

    votes[rule_action] += RULE_WEIGHT * rule_signal["confidence"]
    votes[rl_action] += RL_WEIGHT * rl_signal["confidence"]
    votes[hist_action] += HISTORY_WEIGHT * history_signal["confidence"]

    # Pick winning action
    winning_action = max(votes, key=votes.get)
    winning_score = votes[winning_action]

    # Compute blended confidence (normalized by total possible weight)
    total_possible = RULE_WEIGHT + RL_WEIGHT + HISTORY_WEIGHT
    blended_confidence = round(winning_score / total_possible, 4) if total_possible > 0 else 0.0

    # Confidence gate for trades
    if winning_action in ("BUY", "SELL") and blended_confidence < MIN_META_CONFIDENCE:
        final_action = "HOLD"
        gate_note = f"Gated: {winning_action} conf {blended_confidence:.4f} < {MIN_META_CONFIDENCE}"
    else:
        final_action = winning_action
        gate_note = ""

    # Build trace
    trace = _build_trace(rule_signal, rl_signal, history_signal, votes, winning_action, blended_confidence, gate_note)

    # Collect active signals
    active_signals = []
    if rule_signal["action"] != "HOLD":
        active_signals.append(f"rules:{rule_signal['action']}")
    if rl_signal["action"] != "HOLD":
        active_signals.append(f"rl:{rl_signal['action']}")
    if history_signal["action"] not in ("HOLD", "TRADE"):
        active_signals.append(f"history:{history_signal['action']}")

    return {
        "action": final_action,
        "confidence": blended_confidence if final_action != "HOLD" else 0.0,
        "reasoning": trace["summary"],
        "signals": active_signals,
        "meta_trace": trace,
        "strength": _classify_strength(votes, final_action),
    }


# ---------------------------------------------------------------------------
# Trace and explanation
# ---------------------------------------------------------------------------

def _build_trace(
    rule: dict,
    rl: dict,
    hist: dict,
    votes: dict,
    winner: str,
    confidence: float,
    gate_note: str,
) -> dict:
    """Build a full explainable trace of the meta decision.

    Args:
        rule: Rule signal.
        rl: RL signal.
        hist: History signal.
        votes: Vote tallies.
        winner: Winning action.
        confidence: Blended confidence.
        gate_note: Confidence gate message (empty if passed).

    Returns:
        Trace dict with per-source breakdown and summary.
    """
    sources = [
        {
            "source": "rules",
            "weight": RULE_WEIGHT,
            "action": rule["action"],
            "confidence": rule["confidence"],
            "vote": round(RULE_WEIGHT * rule["confidence"], 4),
            "detail": rule["detail"],
        },
        {
            "source": "rl",
            "weight": RL_WEIGHT,
            "action": rl["action"],
            "confidence": rl["confidence"],
            "vote": round(RL_WEIGHT * rl["confidence"], 4),
            "detail": rl["detail"],
        },
        {
            "source": "history",
            "weight": HISTORY_WEIGHT,
            "action": hist["action"],
            "confidence": hist["confidence"],
            "vote": round(HISTORY_WEIGHT * hist["confidence"], 4),
            "detail": hist["detail"],
        },
    ]

    summary_parts = [f"Rules={rule['action']}({rule['confidence']:.2f})", f"RL={rl['action']}({rl['confidence']:.2f})", f"Hist={hist['action']}({hist['confidence']:.2f})"]
    summary = f"{' | '.join(summary_parts)} -> {winner}({confidence:.4f})"
    if gate_note:
        summary += f" [{gate_note}]"

    return {
        "sources": sources,
        "votes": {k: round(v, 4) for k, v in votes.items()},
        "winner": winner,
        "confidence": confidence,
        "gate_note": gate_note,
        "summary": summary,
    }


def _classify_strength(votes: dict, final_action: str) -> str:
    """Classify the decision strength based on vote distribution.

    Args:
        votes: Vote tallies per action.
        final_action: The chosen action.

    Returns:
        One of: 'strong', 'moderate', 'weak', 'none'.
    """
    if final_action == "HOLD":
        return "none"

    sorted_votes = sorted(votes.values(), reverse=True)

    if len(sorted_votes) >= 2:
        margin = sorted_votes[0] - sorted_votes[1]
    else:
        margin = sorted_votes[0]

    if margin > 0.15:
        return "strong"
    if margin > 0.05:
        return "moderate"
    return "weak"


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_meta_trace(decision: dict) -> None:
    """Print a formatted meta decision trace.

    Args:
        decision: Output from meta_decide().
    """
    trace = decision.get("meta_trace", {})
    sources = trace.get("sources", [])

    print("\n" + "-" * 55)
    print("  Meta Engine Trace")
    print("-" * 55)

    for s in sources:
        print(f"  {s['source']:8s}  {s['action']:5s}  "
              f"conf={s['confidence']:.2f}  "
              f"wt={s['weight']:.0%}  "
              f"vote={s['vote']:.4f}  "
              f"{s['detail'][:40]}")

    votes = trace.get("votes", {})
    print(f"  Votes:    BUY={votes.get('BUY', 0):.4f}  "
          f"SELL={votes.get('SELL', 0):.4f}  "
          f"HOLD={votes.get('HOLD', 0):.4f}")

    print(f"  Result:   {decision['action']} "
          f"(conf={decision['confidence']:.4f}, "
          f"strength={decision.get('strength', '?')})")

    if trace.get("gate_note"):
        print(f"  Gate:     {trace['gate_note']}")

    print("-" * 55)
