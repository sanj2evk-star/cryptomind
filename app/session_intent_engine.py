"""
session_intent_engine.py — CryptoMind v7.4 Chunk 2: Session Intent.

Generates a daily posture / session stance from real signals:
    - daily_bias     (overall_stance, threshold adjustments)
    - regime         (current market state)
    - performance    (recent PnL, win rate, drawdown)
    - volatility     (market quality, radar noise level)

Intent types:
    defensive         — protect capital, reduce exposure, tighten filters
    neutral           — standard operation, no strong bias
    opportunistic     — conditions look favourable, slightly wider filters
    trend_friendly    — strong trend detected, follow it with modest size
    headline_sensitive — news environment is volatile, filter extra hard

This is READ-ONLY.  Intent does NOT override execution rules.
It describes the system's posture, not control it.
"""

from __future__ import annotations

import time
import threading
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Intent vocabulary
# ---------------------------------------------------------------------------

INTENTS = {
    "defensive": {
        "label":       "Defensive",
        "icon":        "◈",
        "color":       "#d97706",
        "description": "Capital protection mode. Tighter filters, smaller size.",
        "reasoning_template": "Recent losses or high drawdown. Pulling back to protect.",
    },
    "neutral": {
        "label":       "Neutral",
        "icon":        "◉",
        "color":       "#6b7280",
        "description": "Standard operation. No strong bias either way.",
        "reasoning_template": "Nothing unusual. Operating normally.",
    },
    "opportunistic": {
        "label":       "Opportunistic",
        "icon":        "●",
        "color":       "#22c55e",
        "description": "Conditions look decent. Slightly wider aperture.",
        "reasoning_template": "Recent performance is solid and market quality is reasonable.",
    },
    "trend_friendly": {
        "label":       "Trend-Friendly",
        "icon":        "◎",
        "color":       "#3b82f6",
        "description": "Strong directional signal. Leaning into the trend.",
        "reasoning_template": "Clear trend with supporting signals. Following, not forcing.",
    },
    "headline_sensitive": {
        "label":       "Headline-Sensitive",
        "icon":        "◇",
        "color":       "#8b5cf6",
        "description": "Noisy news environment. Extra filtering on everything.",
        "reasoning_template": "High noise from news sources. Being extra skeptical.",
    },
}

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_state: dict = {}
_last_compute: float = 0
_COMPUTE_INTERVAL = 120  # 2 min

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def compute(session_id: int = None) -> dict:
    """Compute session intent from real signals.

    Returns dict with: intent, label, confidence, reasoning, factors, computed_at.
    """
    global _state, _last_compute

    now = time.time()
    if (now - _last_compute) < _COMPUTE_INTERVAL and _state:
        return _state

    try:
        import db
        import session_manager
        sid = session_id or session_manager.get_session_id()
        if not sid:
            return _default_state("neutral", "No active session.")

        # --- Gather signals ---
        bias = db.get_active_bias(sid)
        bstate = db.get_behavior_state(sid) or {}
        trade_summary = db.get_trade_summary(session_id=sid)
        system = db.get_system_state() or {}

        total_trades = trade_summary.get("total", 0)
        win_rate = float(trade_summary.get("win_rate", 0.5))
        net_pnl = float(trade_summary.get("net_pnl", 0))
        regime = system.get("current_regime", "SLEEPING")
        mq = system.get("current_market_quality", 0)

        # Radar noise
        noise_ratio = 0.0
        try:
            import bullshit_radar
            radar = bullshit_radar.get_radar()
            noise_ratio = float(radar.get("noise_ratio", 0))
        except Exception:
            pass

        # Fear & greed
        fg_value = 50
        try:
            import news_ingestor
            fg = news_ingestor.get_fear_greed()
            fg_value = int(fg.get("value", 50))
        except Exception:
            pass

        # Bias stance
        bias_stance = (bias.get("overall_stance", "neutral") if bias else "neutral").lower()
        bias_confidence = float(bias.get("confidence_in_bias", 0.5)) if bias else 0.5

        # Reward state
        reward_state = bstate.get("market_reward_state", "neutral")
        self_state = bstate.get("system_self_state", "learning")
        recent_win_rate = float(bstate.get("recent_win_rate", 0.5))

        factors = []
        score = {
            "defensive": 0, "neutral": 25, "opportunistic": 0,
            "trend_friendly": 0, "headline_sensitive": 0,
        }

        # --- Decision logic (weighted scoring) ---

        # Performance pressure
        if net_pnl < -0.5 or recent_win_rate < 0.35:
            score["defensive"] += 35
            factors.append(f"Down ${abs(net_pnl):.2f} with {recent_win_rate*100:.0f}% win rate — pulling back.")
        elif net_pnl > 0.5 and recent_win_rate > 0.55:
            score["opportunistic"] += 30
            factors.append(f"Up ${net_pnl:.2f} with strong {recent_win_rate*100:.0f}% win rate.")
        else:
            score["neutral"] += 15
            factors.append("Performance is neutral — no strong pressure either way.")

        # Regime signal
        if regime in ("ACTIVE",):
            score["opportunistic"] += 15
            if mq >= 60:
                score["trend_friendly"] += 20
                factors.append(f"Active market with quality {mq} — trend-friendly conditions.")
            else:
                factors.append(f"Active market, moderate quality ({mq}).")
        elif regime == "BREAKOUT":
            score["trend_friendly"] += 25
            factors.append("Breakout detected — leaning into direction.")
        elif regime == "SLEEPING":
            score["neutral"] += 20
            factors.append("Market sleeping. Nothing to lean into.")
        elif regime == "WAKING_UP":
            score["opportunistic"] += 10
            factors.append("Market waking up — staying alert.")

        # Daily bias
        if bias_stance in ("cautious", "defensive"):
            score["defensive"] += 20 * bias_confidence
            factors.append(f"Daily review suggests caution (confidence {bias_confidence*100:.0f}%).")
        elif bias_stance in ("aggressive", "opportunistic"):
            score["opportunistic"] += 15 * bias_confidence
            factors.append(f"Daily review suggests opportunity (confidence {bias_confidence*100:.0f}%).")

        # Noise environment
        if noise_ratio > 0.5:
            score["headline_sensitive"] += 30
            score["defensive"] += 10
            factors.append(f"News noise at {noise_ratio*100:.0f}% — filtering hard.")
        elif noise_ratio > 0.3:
            score["headline_sensitive"] += 15
            factors.append(f"Moderate news noise ({noise_ratio*100:.0f}%).")

        # Fear & Greed extremes
        if fg_value < 20:
            score["defensive"] += 15
            factors.append(f"Extreme Fear ({fg_value}) — defensive posture.")
        elif fg_value > 80:
            score["defensive"] += 10
            score["headline_sensitive"] += 10
            factors.append(f"Extreme Greed ({fg_value}) — crowd euphoria, being careful.")

        # Reward state
        if reward_state == "punishing":
            score["defensive"] += 20
            factors.append("Market has been punishing recent trades.")
        elif reward_state == "rewarding":
            score["opportunistic"] += 15
            factors.append("Market has been rewarding the current approach.")

        # Self state
        if self_state == "overfit":
            score["defensive"] += 15
            factors.append("System may be overfitting — pulling back.")

        # --- Pick winner ---
        intent = max(score, key=score.get)
        best_score = score[intent]
        total_score = sum(score.values())
        confidence = round(best_score / max(total_score, 1), 3)

        # Low-data discount
        if total_trades < 5:
            intent = "neutral"
            confidence = 0.3
            factors = ["Too few trades for a strong stance. Defaulting to neutral."]

        intent_info = INTENTS.get(intent, INTENTS["neutral"])
        reasoning = factors[0] if factors else intent_info["reasoning_template"]

        result = {
            "intent":       intent,
            "label":        intent_info["label"],
            "icon":         intent_info["icon"],
            "color":        intent_info["color"],
            "description":  intent_info["description"],
            "confidence":   confidence,
            "reasoning":    reasoning,
            "factors":      factors[:5],
            "score_breakdown": score,
            "context": {
                "regime":       regime,
                "market_quality": mq,
                "noise_ratio":  round(noise_ratio, 3),
                "fear_greed":   fg_value,
                "bias_stance":  bias_stance,
                "reward_state": reward_state,
                "self_state":   self_state,
                "total_trades": total_trades,
                "win_rate":     round(win_rate, 3),
                "net_pnl":      round(net_pnl, 4),
            },
            "warming_up": total_trades < 5,
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

        with _lock:
            _state = result
            _last_compute = time.time()

        return result

    except Exception as e:
        return _default_state("neutral", f"Error computing intent: {e}")


def _default_state(intent: str, reason: str) -> dict:
    info = INTENTS.get(intent, INTENTS["neutral"])
    return {
        "intent":      intent,
        "label":       info["label"],
        "icon":        info["icon"],
        "color":       info["color"],
        "description": info["description"],
        "confidence":  0.3,
        "reasoning":   reason,
        "factors":     [reason],
        "warming_up":  True,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

def get() -> dict:
    if not _state:
        return compute()
    return _state


def get_oneliner() -> str:
    s = get()
    return f"{s.get('label', 'Neutral')} — {s.get('reasoning', 'Warming up.')}"
