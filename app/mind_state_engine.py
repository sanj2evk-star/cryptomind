"""
mind_state_engine.py — CryptoMind v7.4 Observer Core: Mind State.

Synthesises the system's current "mental state" from all available data:
    - Trading engine state (regime, market quality, exposure)
    - News environment (fear/greed, noise level, sentiment)
    - System behaviour (adaptation activity, discipline)
    - Performance context (recent PnL, drawdown, win rate)

Produces a human-readable mind state.
This is the consciousness layer — pure observation, no execution.
"""

from __future__ import annotations

import json
import time
import threading
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Mood vocabulary
# ---------------------------------------------------------------------------

MOODS = {
    "calm_observing": {
        "label":       "Calm & Observing",
        "sigil":       "◉",
        "description": "Quietly watching.  No urgency.",
        "color":       "#6b7280",
    },
    "focused_selective": {
        "label":       "Focused & Selective",
        "sigil":       "◎",
        "description": "Looking for clean entries.  Filter is tight.",
        "color":       "#3b82f6",
    },
    "cautious_defensive": {
        "label":       "Cautious & Defensive",
        "sigil":       "◈",
        "description": "Market feels risky.  Tightening everything.",
        "color":       "#d97706",
    },
    "confident_steady": {
        "label":       "Confident & Steady",
        "sigil":       "●",
        "description": "Conviction improved, size still modest.",
        "color":       "#22c55e",
    },
    "alert_volatile": {
        "label":       "Alert & Volatile",
        "sigil":       "◆",
        "description": "High volatility. Extra careful.",
        "color":       "#ef4444",
    },
    "skeptical_filtering": {
        "label":       "Skeptical & Filtering",
        "sigil":       "◇",
        "description": "Noisy environment. Filtering aggressively.",
        "color":       "#8b5cf6",
    },
    "recovering_learning": {
        "label":       "Recovering & Learning",
        "sigil":       "◌",
        "description": "Recent losses. Reviewing what went wrong.",
        "color":       "#f59e0b",
    },
    "idle_waiting": {
        "label":       "Idle & Waiting",
        "sigil":       "○",
        "description": "Dead market. Nothing to do. Patience.",
        "color":       "#4b5563",
    },
}

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_state: dict = {
    "mood":           "idle_waiting",
    "mood_label":     "Idle & Waiting",
    "mood_sigil":     "○",
    "mood_desc":      "Starting up. Gathering data.",
    "mood_color":     "#4b5563",
    "action_impulse": "none",       # none / watch / consider / ready
    "clarity":        50,           # 0-100
    "current_focus":  "warming up",
    "thoughts":       [],
    "concerns":       [],
    "opportunities":  [],
    "reasoning":      "",
    "last_updated":   None,
}
_last_compute: float = 0

# ---------------------------------------------------------------------------
# Computation
# ---------------------------------------------------------------------------

def compute(
    market_state:       str   = "SLEEPING",
    market_quality:     int   = 0,
    exposure_pct:       float = 0.0,
    recent_pnl:         float = 0.0,
    win_rate:           float = 0.5,
    total_trades:       int   = 0,
    fear_greed:         dict  = None,
    radar:              dict  = None,
    cycle_count:        int   = 0,
    drawdown_pct:       float = 0.0,
    consecutive_losses: int   = 0,
) -> dict:
    """Compute current mind state from all signals.  Returns full dict."""
    global _state, _last_compute

    now = time.time()
    if (now - _last_compute) < 20 and _state.get("last_updated"):
        return _state

    fg    = fear_greed or {}
    rd    = radar or {}
    fg_v  = fg.get("value", 50)
    noise = rd.get("noise_ratio", 0)
    hype  = rd.get("hype_alert", False)
    dist  = rd.get("narrative_distortion", 0)
    sq    = rd.get("signal_quality", 0.5)

    thoughts:      list[str] = []
    concerns:      list[str] = []
    opportunities: list[str] = []

    # ── Mood selection (priority cascade) ──

    if consecutive_losses >= 3 or drawdown_pct > 5:
        mood = "recovering_learning"
        thoughts.append(f"Lost {consecutive_losses} in a row.  Slowing down to review.")
        if drawdown_pct > 5:
            concerns.append(f"Drawdown at {drawdown_pct:.1f}%.  Protecting capital.")
        action_impulse = "none"

    elif noise > 0.55:
        mood = "skeptical_filtering"
        thoughts.append("News environment is very noisy.  Filtering hard.")
        if hype:
            concerns.append(rd.get("hype_reason", "Hype detected."))
        action_impulse = "watch"

    elif market_state == "BREAKOUT":
        mood = "alert_volatile"
        thoughts.append("Explosive move.  Need to be sharp.")
        if exposure_pct > 50:
            concerns.append(f"Already {exposure_pct:.0f}% exposed.  No more adding.")
        else:
            opportunities.append("Breakout with room to add.  Looking for confirmation.")
        action_impulse = "consider"

    elif market_state == "ACTIVE":
        if win_rate > 0.55 and recent_pnl > 0:
            mood = "confident_steady"
            thoughts.append("Reading the market well. Executing with modest conviction.")
            action_impulse = "ready"
        else:
            mood = "focused_selective"
            thoughts.append("Active market. Hunting for quality setups only.")
            action_impulse = "consider"

    elif market_state == "WAKING_UP":
        mood = "focused_selective"
        thoughts.append("Market stirring. Getting ready.")
        if fg_v < 30:
            opportunities.append("Fear is high while market wakes — possible turning point.")
        action_impulse = "watch"

    elif market_state == "SLEEPING":
        mood = "idle_waiting"
        thoughts.append("Dead market. Nothing worth doing. Patience.")
        if total_trades == 0:
            thoughts.append("No trades yet. Waiting for the first real opportunity.")
        action_impulse = "none"

    else:
        mood = "calm_observing"
        thoughts.append("Watching and learning. No strong signal either way.")
        action_impulse = "watch"

    # ── Fear & Greed context ──
    if fg_v < 20:
        thoughts.append(f"Extreme Fear ({fg_v}).  Historically, opportunities hide here.")
    elif fg_v > 80:
        concerns.append(f"Extreme Greed ({fg_v}).  The crowd is euphoric — be careful.")
    elif fg_v < 35:
        thoughts.append(f"Fear elevated ({fg_v}).  Watching for contrarian setups.")
    elif fg_v > 65:
        thoughts.append(f"Greed building ({fg_v}).  Don't chase.")

    # ── Performance context ──
    if total_trades > 10 and win_rate < 0.35:
        concerns.append(f"Win rate at {win_rate*100:.0f}%.  Something might be off.")
    elif total_trades > 10 and win_rate > 0.65:
        thoughts.append(f"Strong {win_rate*100:.0f}% win rate.  System is reading well.")

    if recent_pnl < -1:
        concerns.append(f"Down ${abs(recent_pnl):.2f} recently.  Staying disciplined.")
    elif recent_pnl > 1:
        thoughts.append(f"Up ${recent_pnl:.2f} recently.  Keeping composure.")

    # ── Narrative distortion ──
    if dist > 0.5:
        concerns.append("News feed is one-sided.  Possible narrative manipulation.")

    # ── Clarity score (0-100) ──
    clarity = 50
    if market_state in ("ACTIVE", "BREAKOUT"):  clarity += 12
    if noise < 0.3:                              clarity += 10
    elif noise > 0.5:                            clarity -= 15
    if 25 < fg_v < 65:                           clarity += 5
    else:                                        clarity -= 8
    if win_rate > 0.5 and total_trades > 5:      clarity += 8
    if consecutive_losses >= 2:                   clarity -= 12
    if dist > 0.5:                               clarity -= 10
    clarity = max(10, min(95, clarity))

    # ── Current focus ──
    if mood == "idle_waiting":
        focus = "patience — waiting for the market to wake up"
    elif mood == "recovering_learning":
        focus = "damage review — figuring out what went wrong"
    elif mood == "skeptical_filtering":
        focus = "noise rejection — protecting signal integrity"
    elif mood == "alert_volatile":
        focus = "volatility management — tight risk control"
    elif mood == "confident_steady":
        focus = "clean execution — good setups, modest size"
    else:
        focus = "scanning — looking for clarity"

    # ── Reasoning summary ──
    reasoning = f"{MOODS[mood]['label']}. "
    if thoughts:
        reasoning += thoughts[0]
    if concerns:
        reasoning += f"  Concern: {concerns[0]}"

    mi = MOODS.get(mood, MOODS["calm_observing"])

    with _lock:
        _state = {
            "mood":           mood,
            "mood_label":     mi["label"],
            "mood_sigil":     mi["sigil"],
            "mood_desc":      mi["description"],
            "mood_color":     mi["color"],
            "action_impulse": action_impulse,
            "clarity":        clarity,
            "current_focus":  focus,
            "thoughts":       thoughts[:5],
            "concerns":       concerns[:4],
            "opportunities":  opportunities[:3],
            "reasoning":      reasoning,
            "context": {
                "market_state":  market_state,
                "fear_greed":    fg_v,
                "noise_ratio":   round(noise, 2),
                "signal_quality": round(sq, 2),
                "narrative_distortion": round(dist, 2),
                "exposure_pct":  round(exposure_pct, 1),
                "recent_pnl":    round(recent_pnl, 4),
                "win_rate":      round(win_rate, 3),
                "total_trades":  total_trades,
                "drawdown_pct":  round(drawdown_pct, 1),
                "cycle_count":   cycle_count,
            },
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        _last_compute = time.time()

    return _state


def get() -> dict:
    return _state


def get_oneliner() -> str:
    s = _state
    m = s.get("mood_label", "Starting up")
    c = s.get("clarity", 50)
    t = s["thoughts"][0] if s.get("thoughts") else "Gathering data…"
    return f"{m} (clarity {c}%) — {t}"
