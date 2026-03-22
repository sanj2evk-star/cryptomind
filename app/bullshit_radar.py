"""
bullshit_radar.py — CryptoMind v7.4 Observer Core: BS Detector.

Evaluates the overall quality of the current information environment.
Produces a human-readable "noise level" and tracks:
    - signal vs garbage ratio
    - narrative distortion (is the crowd hyping one direction?)
    - crowd heat (extreme fear/greed, or balanced?)
    - hype alerts

The system's immune system against information noise.
It defaults to skepticism.  High trust must be earned.
"""

from __future__ import annotations

import time
import threading
from datetime import datetime, timezone
from collections import deque

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_WINDOW       = 100   # last N classified items
_MIN_FOR_CALC = 3     # need at least this many to compute

_LEVELS = [
    (0.00, 0.20, "clear",    "Clean feed. Most news looks genuine and relevant."),
    (0.20, 0.40, "mild",     "Some noise. Good signals still getting through."),
    (0.40, 0.55, "moderate", "Noisy. About half the feed is hype or filler."),
    (0.55, 0.70, "elevated", "Heavy noise. Lots of hype, FUD, or irrelevant chatter."),
    (0.70, 0.85, "high",     "Mostly garbage. Very few useful signals."),
    (0.85, 1.01, "extreme",  "Almost pure noise. Trust nothing without checking."),
]

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_lock    = threading.Lock()
_history: deque = deque(maxlen=_WINDOW)
_state: dict = {
    "noise_ratio":           0.0,
    "level":                 "clear",
    "description":           "No data yet — waiting for news.",
    "signal_quality":        0.5,
    "narrative_distortion":  0.0,
    "crowd_heat":            "neutral",
    "hype_alert":            False,
    "hype_reason":           None,
    "total_analysed":        0,
    "last_updated":          None,
}
_last_calc: float = 0

# ---------------------------------------------------------------------------
# Feed + Compute
# ---------------------------------------------------------------------------

def feed(classified: list[dict]) -> None:
    """Feed classified items into the radar window."""
    with _lock:
        for c in classified:
            _history.append({
                "verdict":    c.get("verdict", "noise"),
                "sentiment":  c.get("sentiment", "neutral"),
                "impact":     c.get("impact", "noise"),
                "hype_score": c.get("hype_score", 0),
                "bs_risk":    c.get("bs_risk", 0),
                "trust":      c.get("trust", 0.5),
                "relevance":  c.get("relevance", 0),
                "ts":         c.get("classified_at", datetime.now(timezone.utc).isoformat()),
            })


def compute() -> dict:
    """Recompute radar from history.  Returns full state dict."""
    global _state, _last_calc

    now = time.time()
    if (now - _last_calc) < 30 and _state.get("total_analysed", 0) > 0:
        return _state

    with _lock:
        items = list(_history)

    n = len(items)
    if n < _MIN_FOR_CALC:
        _state = {
            "noise_ratio":          0.0,
            "level":                "clear",
            "description":          "Not enough data yet.  Need more headlines.",
            "signal_quality":       0.5,
            "narrative_distortion": 0.0,
            "crowd_heat":           "neutral",
            "hype_alert":           False,
            "hype_reason":          None,
            "total_analysed":       n,
            "interesting_count":    0,
            "watch_count":          0,
            "reject_count":         0,
            "noise_count":          0,
            "last_updated":         datetime.now(timezone.utc).isoformat(),
        }
        return _state

    # counts
    interesting = sum(1 for i in items if i["verdict"] == "interesting")
    watched     = sum(1 for i in items if i["verdict"] == "watch")
    rejected    = sum(1 for i in items if i["verdict"] == "reject")
    noise       = sum(1 for i in items if i["verdict"] == "noise")
    unclear     = sum(1 for i in items if i["verdict"] == "unclear")

    noise_ratio = (rejected + noise) / max(n, 1)  # unclear doesn't count as noise
    avg_trust   = sum(i["trust"] for i in items) / max(n, 1)
    avg_hype    = sum(i["hype_score"] for i in items) / max(n, 1)
    avg_bs      = sum(i["bs_risk"] for i in items) / max(n, 1)

    signal_quality = max(0.0, min(1.0, avg_trust * (1 - noise_ratio)))

    # sentiment balance → narrative distortion
    bullish  = sum(1 for i in items if i["sentiment"] == "bullish")
    bearish  = sum(1 for i in items if i["sentiment"] == "bearish")
    dominant = max(bullish, bearish)
    distortion = (dominant / n - 0.5) * 2 if n > 0 else 0  # 0 = balanced, 1 = totally one-sided
    distortion = max(0, min(1, distortion))

    # crowd heat
    if bullish > n * 0.6:
        crowd = "heavily_bullish"
    elif bullish > n * 0.4:
        crowd = "leaning_bullish"
    elif bearish > n * 0.6:
        crowd = "heavily_bearish"
    elif bearish > n * 0.4:
        crowd = "leaning_bearish"
    else:
        crowd = "balanced"

    # hype alert
    hype_alert  = False
    hype_reason = None
    if avg_hype > 0.4:
        hype_alert  = True
        hype_reason = "Feed is saturated with hype language.  Stay skeptical."
    elif distortion > 0.6:
        hype_alert  = True
        side = "bullish" if bullish > bearish else "bearish"
        hype_reason = f"Feed is heavily {side}.  Possible narrative manipulation."
    elif noise_ratio > 0.7:
        hype_alert  = True
        hype_reason = "Extremely noisy.  Most incoming information is low quality."

    # level label
    level = "clear"
    description = ""
    for lo, hi, lbl, desc in _LEVELS:
        if lo <= noise_ratio < hi:
            level       = lbl
            description = desc
            break

    # Crowd sentiment overlay (observer-only)
    crowd_sentiment = {}
    try:
        import crowd_sentiment_engine
        crowd_sentiment = crowd_sentiment_engine.compute()
    except Exception:
        pass

    # Signal layer overlay (v7.6 — observer-only)
    signal_overlay = {}
    try:
        from signal_layer import ENABLE_SIGNAL_LAYER
        if ENABLE_SIGNAL_LAYER:
            from signal_layer.signal_aggregator import aggregate
            agg = aggregate()
            if agg and not agg.get("warming_up"):
                composite = agg.get("composite", {})
                sig_dir = composite.get("overall_direction", "neutral")
                # Compare crowd heat vs signal direction
                crowd_agrees = (
                    (crowd == "heavily_bullish" and sig_dir == "bullish") or
                    (crowd == "heavily_bearish" and sig_dir == "bearish") or
                    (crowd in ("balanced", "leaning_bullish", "leaning_bearish") and sig_dir == "neutral")
                )
                signal_overlay = {
                    "signal_direction": sig_dir,
                    "signal_alignment": composite.get("alignment", "unclear"),
                    "signal_tension": composite.get("tension_score", 0),
                    "crowd_vs_positioning": "aligned" if crowd_agrees else "diverging",
                    "narrative_state": composite.get("narrative_state", "calm"),
                }
    except Exception:
        pass

    _state = {
        "noise_ratio":          round(noise_ratio, 3),
        "level":                level,
        "description":          description,
        "signal_quality":       round(signal_quality, 3),
        "narrative_distortion": round(distortion, 3),
        "crowd_heat":           crowd,
        "avg_trust":            round(avg_trust, 3),
        "avg_hype":             round(avg_hype, 3),
        "avg_bs_risk":          round(avg_bs, 3),
        "hype_alert":           hype_alert,
        "hype_reason":          hype_reason,
        "total_analysed":       n,
        "interesting_count":    interesting,
        "watch_count":          watched,
        "reject_count":         rejected,
        "noise_count":          noise,
        "unclear_count":        unclear,
        "bullish_count":        bullish,
        "bearish_count":        bearish,
        "crowd_sentiment":      crowd_sentiment if crowd_sentiment else None,
        "signal_layer":         signal_overlay if signal_overlay else None,
        "last_updated":         datetime.now(timezone.utc).isoformat(),
    }
    _last_calc = time.time()
    return _state


def get_radar() -> dict:
    return compute()


def get_oneliner() -> str:
    """Dashboard one-liner."""
    r = compute()
    n = r["total_analysed"]
    if n < _MIN_FOR_CALC:
        return "Radar quiet — not enough news yet."
    pct = round(r["noise_ratio"] * 100)
    sig = r.get("interesting_count", 0)
    texts = {
        "clear":    f"Clean feed — {sig} interesting signals, only {pct}% noise.",
        "mild":     f"Mild noise ({pct}%).  {sig} signals getting through.",
        "moderate": f"Noisy feed ({pct}%).  Filter carefully.",
        "elevated": f"Heavy noise ({pct}%).  Most of the feed is hype or filler.",
        "high":     f"Garbage-heavy ({pct}%).  Almost nothing useful.",
        "extreme":  f"Pure noise ({pct}%).  Don't trust anything without proof.",
    }
    txt = texts.get(r["level"], f"Noise: {pct}%")
    if r.get("hype_alert"):
        txt += f"  ⚠ {r['hype_reason']}"
    return txt
