"""
liquidation_collector.py — Liquidation event signal collector.

Observes mass liquidation events (long/short squeezes).
Currently synthetic; designed for real Coinglass/exchange API integration.

Observer-only — NEVER influences trades.
"""

from __future__ import annotations

import time
import random
import threading
from datetime import datetime, timezone

from signal_layer.base_normalizer import normalize

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_CACHE_TTL = 60
_lock = threading.Lock()
_cache: list[dict] = []
_cache_ts: float = 0

# Thresholds for liquidation significance
_MINOR_THRESHOLD = 5    # $5M — worth noting
_MAJOR_THRESHOLD = 25   # $25M — significant squeeze
_EXTREME_THRESHOLD = 80 # $80M — massive flush


# ---------------------------------------------------------------------------
# Synthetic data source
# ---------------------------------------------------------------------------

def _fetch() -> list[dict]:
    """Generate synthetic liquidation signals from price volatility.

    Real integration: replace with Coinglass API or exchange websocket.
    """
    signals = []

    try:
        import auto_trader
        state = auto_trader._state
        prices = state.get("price_history", [])
        if len(prices) < 10:
            return []

        # Detect sharp moves → synthetic liquidation events
        recent = prices[-5:]
        move_pct = (recent[-1] - recent[0]) / max(recent[0], 1) * 100

        # Only generate liquidation signals on sharp moves (>0.5%)
        if abs(move_pct) < 0.5:
            return []

        # Larger moves → bigger liquidation amounts (synthetic)
        base_amount = abs(move_pct) * 10 + random.gauss(0, 3)
        base_amount = max(1, base_amount)  # millions USD

        if move_pct < -0.5:
            # Price dropped → long liquidations
            signals.append(
                normalize(
                    source="liquidation",
                    signal_type="long_liquidation",
                    direction="bearish",
                    strength=min(1.0, base_amount / _EXTREME_THRESHOLD),
                    confidence=0.65,
                    raw_value=base_amount,
                    context=_liquidation_context("Long", base_amount, move_pct),
                    meta={
                        "liquidation_type": "long",
                        "estimated_amount_m": round(base_amount, 1),
                        "price_move_pct": round(move_pct, 2),
                        "severity": _severity(base_amount),
                    },
                )
            )
        elif move_pct > 0.5:
            # Price rose → short liquidations
            signals.append(
                normalize(
                    source="liquidation",
                    signal_type="short_liquidation",
                    direction="bullish",
                    strength=min(1.0, base_amount / _EXTREME_THRESHOLD),
                    confidence=0.65,
                    raw_value=base_amount,
                    context=_liquidation_context("Short", base_amount, move_pct),
                    meta={
                        "liquidation_type": "short",
                        "estimated_amount_m": round(base_amount, 1),
                        "price_move_pct": round(move_pct, 2),
                        "severity": _severity(base_amount),
                    },
                )
            )

        return signals

    except Exception:
        return []


def _severity(amount: float) -> str:
    if amount >= _EXTREME_THRESHOLD:
        return "extreme"
    if amount >= _MAJOR_THRESHOLD:
        return "major"
    if amount >= _MINOR_THRESHOLD:
        return "minor"
    return "negligible"


def _liquidation_context(side: str, amount: float, move_pct: float) -> str:
    sev = _severity(amount)
    if sev == "extreme":
        return f"{side} squeeze: ~${amount:.0f}M liquidated on {move_pct:+.1f}% move — massive flush"
    if sev == "major":
        return f"{side} liquidations: ~${amount:.0f}M on {move_pct:+.1f}% move — significant"
    if sev == "minor":
        return f"{side} liquidations: ~${amount:.0f}M on {move_pct:+.1f}% move"
    return f"Minor {side.lower()} liquidations: ~${amount:.0f}M"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def collect() -> list[dict]:
    """Return latest liquidation signals (cached)."""
    global _cache, _cache_ts
    now = time.time()
    if _cache and (now - _cache_ts) < _CACHE_TTL:
        return _cache
    with _lock:
        _cache = _fetch()
        _cache_ts = now
    return _cache
