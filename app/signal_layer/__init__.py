"""
signal_layer — CryptoMind v7.6 Tier 1 Signal Layer (Observer-Only).

Collects, normalizes, interprets, and aggregates external positioning signals
(Polymarket, derivatives, liquidations) into a unified insight stream.

NEVER influences trading decisions — strictly read-only observation.
"""

from __future__ import annotations

# Feature flags
ENABLE_SIGNAL_LAYER = True
ENABLE_SIGNAL_INFLUENCE = False  # v7.6 = observer-only, never True yet
