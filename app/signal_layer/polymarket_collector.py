"""
polymarket_collector.py — Polymarket / prediction market signal collector.

Observes crowd positioning on BTC-related prediction markets.
Currently uses synthetic data derived from existing crowd_sentiment_engine;
designed so a real Polymarket API integration just replaces _fetch().

Observer-only — NEVER influences trades.
"""

from __future__ import annotations

import time
import threading
from datetime import datetime, timezone

from signal_layer.base_normalizer import normalize

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_CACHE_TTL = 60  # seconds between fetches
_lock = threading.Lock()
_cache: list[dict] = []
_cache_ts: float = 0


# ---------------------------------------------------------------------------
# Data source (synthetic — replace with real API later)
# ---------------------------------------------------------------------------

def _fetch() -> list[dict]:
    """Fetch Polymarket-style prediction data.

    Currently derives synthetic signals from crowd_sentiment_engine.
    Real integration replaces only this function.
    """
    try:
        import crowd_sentiment_engine
        crowd = crowd_sentiment_engine.compute()
        if not crowd or crowd.get("warming_up"):
            return []

        bias = crowd.get("crowd_bias", "neutral")
        prob = crowd.get("crowd_probability", 50) / 100  # normalize to 0-1
        strength_raw = crowd.get("confidence_strength", 0) / 100

        # Direction mapping
        if bias == "bullish":
            direction = "bullish"
        elif bias == "bearish":
            direction = "bearish"
        else:
            direction = "neutral"

        # Confidence based on how far from 50/50
        confidence = min(1.0, abs(prob - 0.5) * 2 + 0.3)

        signals = [
            normalize(
                source="polymarket",
                signal_type="btc_price_prediction",
                direction=direction,
                strength=strength_raw,
                confidence=confidence,
                raw_value=prob,
                context=f"Crowd {bias} at {prob*100:.0f}% conviction",
                meta={
                    "crowd_bias": bias,
                    "crowd_probability": round(prob * 100, 1),
                    "alignment": crowd.get("alignment", "unclear"),
                },
            ),
        ]

        # If divergence is high, add a divergence signal
        div = crowd.get("divergence_score", 0)
        if div > 40:
            signals.append(
                normalize(
                    source="polymarket",
                    signal_type="crowd_divergence",
                    direction="bearish" if bias == "bullish" else "bullish",
                    strength=min(1.0, div / 100),
                    confidence=0.5,
                    raw_value=div,
                    context=f"Crowd divergence at {div}/100 — crowd may be wrong",
                    meta={"divergence_score": div},
                )
            )

        return signals

    except Exception:
        return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def collect() -> list[dict]:
    """Return latest Polymarket signals (cached)."""
    global _cache, _cache_ts
    now = time.time()
    if _cache and (now - _cache_ts) < _CACHE_TTL:
        return _cache
    with _lock:
        _cache = _fetch()
        _cache_ts = now
    return _cache
