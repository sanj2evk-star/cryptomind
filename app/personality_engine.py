"""
personality_engine.py — CryptoMind v7.4 Chunk 2: Personality Layer.

Derives visible personality traits from REAL system data:
    - behavior_profile  (patience, aggressiveness, conviction_threshold, etc.)
    - behavior_states   (modifiers, reward/self states)
    - adaptation_journal (how many adaptations allowed vs blocked)
    - experience_memory  (lessons learned, confidence weights)
    - trade_ledger       (win rate, avg PnL, strategy distribution)
    - bullshit_radar     (noise tolerance from actual filtering)

Every trait is evidence-based.  No random labels, no roleplay.
This module is READ-ONLY — it observes the system, never modifies it.
"""

from __future__ import annotations

import time
import threading
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Trait definitions
# ---------------------------------------------------------------------------

TRAITS = {
    "patience": {
        "label": "Patience",
        "high":  "Slow to trust, slow to act. Lets setups come to it.",
        "mid":   "Measured. Waits for confirmation but doesn't over-delay.",
        "low":   "Itchy trigger finger. Tends to act before the picture clears.",
    },
    "aggression_control": {
        "label": "Aggression Control",
        "high":  "Keeps size small and risk tight, even when tempted.",
        "mid":   "Reasonable sizing. Occasionally stretches when excited.",
        "low":   "Oversizes when confident. Needs better position discipline.",
    },
    "hype_resistance": {
        "label": "Hype Resistance",
        "high":  "Calm under noise. Doesn't flinch at headlines.",
        "mid":   "Mostly filters well, occasionally distracted by big narratives.",
        "low":   "Susceptible to crowd mood. Needs thicker skin.",
    },
    "adaptability": {
        "label": "Adaptability",
        "high":  "Learns from mistakes and adjusts behaviour consistently.",
        "mid":   "Adapts when evidence is strong. Slow otherwise.",
        "low":   "Rigid. Not adjusting even when data says it should.",
    },
    "discipline": {
        "label": "Discipline",
        "high":  "Rules followed, cooldowns respected, no impulsive trades.",
        "mid":   "Generally disciplined. Occasional lapses under pressure.",
        "low":   "Breaking rules too often. Needs tighter self-control.",
    },
    "self_correction": {
        "label": "Self-Correction",
        "high":  "Improving at self-correction. Catches own mistakes.",
        "mid":   "Starting to learn from errors, but slowly.",
        "low":   "Repeating the same mistakes. Not learning fast enough.",
    },
    "risk_awareness": {
        "label": "Risk Awareness",
        "high":  "Respects drawdown limits and cuts losses cleanly.",
        "mid":   "Generally risk-aware. Occasionally holds losing trades too long.",
        "low":   "Ignoring stop levels. Needs better loss management.",
    },
}

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_state: dict = {}
_last_compute: float = 0
_COMPUTE_INTERVAL = 60  # recompute at most once per minute

# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute(session_id: int = None) -> dict:
    """Compute personality traits from real system data.

    Returns dict with: traits, dominant_trait, oneliner, evidence, computed_at.
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
            return _warm_up_state()

        # --- Gather evidence ---
        profile = db.get_active_profile(sid) or {}
        bstate = db.get_behavior_state(sid) or {}
        journal = db.get_adaptation_journal(session_id=sid, limit=100)
        memories = db.get_active_memories(session_id=sid, limit=100)
        trade_summary = db.get_trade_summary(session_id=sid)
        total_trades = trade_summary.get("total", 0)

        if total_trades < 3:
            return _warm_up_state()

        # --- Compute each trait (0-100) ---
        traits = {}

        # 1. Patience: from profile patience + hold_extension_bias + behavior patience_modifier
        raw_patience = float(profile.get("patience", 0.5))
        patience_mod = float(bstate.get("patience_modifier", 0))
        hold_ext = float(profile.get("hold_extension_bias", 0.5))
        patience_score = _clamp(int((raw_patience + hold_ext) / 2 * 100 + patience_mod * 50))
        traits["patience"] = _make_trait("patience", patience_score, total_trades)

        # 2. Aggression Control: inverse of aggressiveness + probe_bias
        raw_agg = float(profile.get("aggressiveness", 0.5))
        probe = float(profile.get("probe_bias", 0.5))
        agg_mod = float(bstate.get("aggression_modifier", 0))
        # High aggressiveness = low aggression control
        agg_control = _clamp(int((1 - raw_agg) * 60 + probe * 20 + 20 - agg_mod * 50))
        traits["aggression_control"] = _make_trait("aggression_control", agg_control, total_trades)

        # 3. Hype Resistance: from noise_tolerance profile + radar filtering behaviour
        noise_tol = float(profile.get("noise_tolerance", 0.5))
        try:
            import bullshit_radar
            radar = bullshit_radar.get_radar()
            noise_ratio = radar.get("noise_ratio", 0)
            # If noise is high but system is still calm, that's hype resistance
            hype_resist = _clamp(int(noise_tol * 50 + (1 - noise_ratio) * 30 + 20))
        except Exception:
            hype_resist = _clamp(int(noise_tol * 80 + 20))
        traits["hype_resistance"] = _make_trait("hype_resistance", hype_resist, total_trades)

        # 4. Adaptability: ratio of allowed vs blocked adaptations + memory depth
        allowed = sum(1 for j in journal if j.get("allowed_or_blocked") == "allowed")
        blocked = sum(1 for j in journal if j.get("allowed_or_blocked") == "blocked")
        total_j = allowed + blocked
        memory_count = len(memories)
        if total_j > 0:
            adapt_ratio = allowed / total_j
            adapt_score = _clamp(int(adapt_ratio * 60 + min(memory_count, 20) * 2))
        else:
            adapt_score = _clamp(int(30 + min(memory_count, 20) * 2))
        traits["adaptability"] = _make_trait("adaptability", adapt_score, total_j + memory_count)

        # 5. Discipline: from overtrade_penalty + conviction_threshold + blocked ratio
        overtrade = float(profile.get("overtrade_penalty", 0.5))
        conviction = float(profile.get("conviction_threshold", 0.5))
        blocked_ratio = blocked / max(total_j, 1) if total_j > 0 else 0.5
        # High blocked ratio = guard is working = discipline maintained
        disc_score = _clamp(int(conviction * 30 + overtrade * 30 + blocked_ratio * 20 + 20))
        traits["discipline"] = _make_trait("discipline", disc_score, total_trades)

        # 6. Self-Correction: memory confidence weights + outcome-based learning
        avg_conf = 0.5
        if memories:
            avg_conf = sum(float(m.get("confidence_weight", 0.5)) for m in memories) / len(memories)
        times_obs = sum(int(m.get("times_observed", 1)) for m in memories) if memories else 0
        sc_score = _clamp(int(avg_conf * 50 + min(times_obs, 50) + 10))
        traits["self_correction"] = _make_trait("self_correction", sc_score, len(memories))

        # 7. Risk Awareness: exit_tightness + exposure_modifier + drawdown behaviour
        exit_tight = float(profile.get("exit_tightness", 0.5))
        exp_mod = float(bstate.get("exposure_modifier", 0))
        win_rate = float(trade_summary.get("win_rate", 0.5))
        risk_score = _clamp(int(exit_tight * 40 + (1 - abs(exp_mod)) * 30 + win_rate * 30))
        traits["risk_awareness"] = _make_trait("risk_awareness", risk_score, total_trades)

        # --- Dominant trait (highest score) ---
        sorted_traits = sorted(traits.values(), key=lambda t: t["score"], reverse=True)
        dominant = sorted_traits[0] if sorted_traits else None
        supporting = sorted_traits[1:3]

        # --- Oneliner ---
        if dominant:
            oneliner = dominant["description"]
        else:
            oneliner = "Still learning who it is."

        result = {
            "traits":         traits,
            "dominant_trait":  dominant,
            "supporting":     supporting,
            "oneliner":       oneliner,
            "evidence": {
                "total_trades":      total_trades,
                "memory_count":      memory_count,
                "adaptations":       total_j,
                "allowed_adaptations": allowed,
                "blocked_adaptations": blocked,
                "win_rate":          round(float(trade_summary.get("win_rate", 0.5)), 3),
            },
            "warming_up": total_trades < 10,
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

        with _lock:
            _state = result
            _last_compute = time.time()

        return result

    except Exception as e:
        return {"error": str(e), "traits": {}, "dominant_trait": None, "warming_up": True}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamp(v: int) -> int:
    return max(5, min(95, v))


def _make_trait(name: str, score: int, evidence: int) -> dict:
    t = TRAITS.get(name, {})
    if score >= 65:
        level, description = "high", t.get("high", "Strong.")
    elif score >= 40:
        level, description = "mid", t.get("mid", "Developing.")
    else:
        level, description = "low", t.get("low", "Needs work.")

    return {
        "name":        name,
        "label":       t.get("label", name),
        "score":       score,
        "level":       level,
        "description": description,
        "evidence":    evidence,
        "warming_up":  evidence < 5,
    }


def _warm_up_state() -> dict:
    return {
        "traits":        {},
        "dominant_trait": None,
        "supporting":    [],
        "oneliner":      "Still too early for a personality read. Need more trades.",
        "evidence":      {"total_trades": 0},
        "warming_up":    True,
        "computed_at":   datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get() -> dict:
    """Get last computed personality. Call compute() first if needed."""
    if not _state:
        return compute()
    return _state


def get_oneliner() -> str:
    s = get()
    return s.get("oneliner", "Warming up…")
