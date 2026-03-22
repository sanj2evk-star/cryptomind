"""
derivatives_collector.py — Derivatives market signal collector.

Observes funding rates, open interest changes, and long/short ratios.
Currently uses synthetic data derived from price behavior and crowd signals;
designed so a real Binance/Bybit futures API replaces only _fetch().

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


# ---------------------------------------------------------------------------
# Synthetic data source
# ---------------------------------------------------------------------------

def _fetch() -> list[dict]:
    """Generate synthetic derivatives signals from market state.

    Real integration: replace with Binance/Bybit futures API calls
    for actual funding rates, OI, and LS ratios.
    """
    signals = []

    try:
        import auto_trader
        state = auto_trader._state
        prices = state.get("price_history", [])
        if len(prices) < 5:
            return []

        # Derive synthetic funding rate from recent price momentum
        recent = prices[-10:] if len(prices) >= 10 else prices
        momentum = (recent[-1] - recent[0]) / max(recent[0], 1) * 100

        # Funding rate: positive = longs paying shorts (bullish overcrowding)
        # Synthetic: correlated with momentum + noise
        funding_rate = momentum * 0.01 + random.gauss(0, 0.005)
        funding_rate = max(-0.1, min(0.1, funding_rate))

        if abs(funding_rate) > 0.01:
            direction = "bearish" if funding_rate > 0.02 else "bullish" if funding_rate < -0.02 else "neutral"
            strength = min(1.0, abs(funding_rate) / 0.05)
            signals.append(
                normalize(
                    source="derivatives",
                    signal_type="funding_rate",
                    direction=direction,
                    strength=strength,
                    confidence=0.6,
                    raw_value=funding_rate,
                    context=f"Funding rate {funding_rate:+.4f}% — {'longs paying (overcrowded)' if funding_rate > 0.01 else 'shorts paying (bearish overcrowded)' if funding_rate < -0.01 else 'balanced'}",
                    meta={"funding_rate_pct": round(funding_rate, 5)},
                )
            )

        # Open interest change (synthetic: derived from price volatility)
        if len(prices) >= 20:
            vol_recent = max(prices[-10:]) - min(prices[-10:])
            vol_prior = max(prices[-20:-10]) - min(prices[-20:-10])
            oi_change = (vol_recent - vol_prior) / max(vol_prior, 1) * 100

            if abs(oi_change) > 5:
                # Rising OI + rising price = bullish conviction
                # Rising OI + falling price = bearish conviction
                price_rising = prices[-1] > prices[-10]
                if oi_change > 0:
                    direction = "bullish" if price_rising else "bearish"
                else:
                    direction = "neutral"

                signals.append(
                    normalize(
                        source="derivatives",
                        signal_type="oi_change",
                        direction=direction,
                        strength=min(1.0, abs(oi_change) / 20),
                        confidence=0.5,
                        raw_value=oi_change,
                        context=f"OI {'rising' if oi_change > 0 else 'falling'} {abs(oi_change):.1f}% — {'building positions' if oi_change > 0 else 'closing positions'}",
                        meta={"oi_change_pct": round(oi_change, 2)},
                    )
                )

        # Long/short ratio (synthetic)
        ls_ratio = 1.0 + momentum * 0.02 + random.gauss(0, 0.1)
        ls_ratio = max(0.5, min(2.0, ls_ratio))
        if abs(ls_ratio - 1.0) > 0.15:
            direction = "bullish" if ls_ratio > 1.15 else "bearish" if ls_ratio < 0.85 else "neutral"
            # Extreme ratios are contrarian signals
            contrarian = ls_ratio > 1.5 or ls_ratio < 0.6
            signals.append(
                normalize(
                    source="derivatives",
                    signal_type="long_short_ratio",
                    direction="bearish" if ls_ratio > 1.5 else "bullish" if ls_ratio < 0.6 else direction,
                    strength=min(1.0, abs(ls_ratio - 1.0) / 0.5),
                    confidence=0.55 if not contrarian else 0.4,
                    raw_value=ls_ratio,
                    context=f"L/S ratio {ls_ratio:.2f} — {'extreme long overcrowding (contrarian bearish)' if ls_ratio > 1.5 else 'extreme short overcrowding (contrarian bullish)' if ls_ratio < 0.6 else 'longs dominate' if ls_ratio > 1.0 else 'shorts dominate'}",
                    meta={"ls_ratio": round(ls_ratio, 3), "contrarian": contrarian},
                )
            )

        return signals

    except Exception:
        return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def collect() -> list[dict]:
    """Return latest derivatives signals (cached)."""
    global _cache, _cache_ts
    now = time.time()
    if _cache and (now - _cache_ts) < _CACHE_TTL:
        return _cache
    with _lock:
        _cache = _fetch()
        _cache_ts = now
    return _cache
