"""
base_normalizer.py — Unified signal format for all collectors.

Every collector must pass its raw data through normalize() to produce a
standard SignalEvent dict that the rest of the pipeline can consume.
"""

from __future__ import annotations

from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Canonical signal schema
# ---------------------------------------------------------------------------

def normalize(
    source: str,
    signal_type: str,
    direction: str,           # "bullish" | "bearish" | "neutral"
    strength: float,          # 0.0 – 1.0
    confidence: float,        # 0.0 – 1.0
    raw_value: float = 0.0,
    context: str = "",
    meta: dict | None = None,
) -> dict:
    """Return a normalized signal event dict.

    Parameters
    ----------
    source : str
        Collector name, e.g. "polymarket", "derivatives", "liquidation".
    signal_type : str
        Sub-type, e.g. "btc_price_prediction", "funding_rate", "oi_change",
        "long_liquidation", "short_liquidation".
    direction : str
        "bullish", "bearish", or "neutral".
    strength : float
        0.0 (weak) to 1.0 (extreme).
    confidence : float
        How reliable this reading is, 0.0 to 1.0.
    raw_value : float
        Original numeric value for audit (e.g. funding rate %).
    context : str
        Human-readable one-liner explaining the reading.
    meta : dict | None
        Arbitrary extra data from the collector.
    """
    return {
        "source": source,
        "signal_type": signal_type,
        "direction": _clamp_direction(direction),
        "strength": round(max(0.0, min(1.0, strength)), 3),
        "confidence": round(max(0.0, min(1.0, confidence)), 3),
        "raw_value": round(raw_value, 6),
        "context": context,
        "meta": meta or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _clamp_direction(d: str) -> str:
    d = (d or "").lower().strip()
    if d in ("bullish", "bearish", "neutral"):
        return d
    return "neutral"
