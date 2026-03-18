"""
portfolio_manager.py - Multi-asset capital allocation.

Allocates capital across assets based on confidence, volatility,
and recent performance. Enforces per-asset risk limits.

Allocation flow:
1. Score each asset (confidence, volatility, performance)
2. Normalize scores into weights
3. Apply per-asset caps
4. Compute USDT allocation per asset
5. Return allocation decisions

Usage:
    allocations = allocate(asset_data, portfolio)
"""

from __future__ import annotations

from config import SYMBOLS, RISK_PER_TRADE_PERCENT

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

MAX_ALLOCATION_PCT = 0.40   # No single asset gets more than 40% of capital
MIN_ALLOCATION_PCT = 0.05   # Minimum 5% if trading at all
CASH_RESERVE_PCT = 0.10     # Always keep 10% cash as reserve

# Scoring weights
CONFIDENCE_WEIGHT = 0.50
VOLATILITY_WEIGHT = 0.30
PERFORMANCE_WEIGHT = 0.20


# ---------------------------------------------------------------------------
# Asset scoring
# ---------------------------------------------------------------------------

def score_asset(asset: dict) -> float:
    """Compute a composite score for a single asset.

    Higher score = more capital deserved. Factors:
    - Confidence: higher is better (from Claude/RL decision).
    - Volatility: lower is better (calmer markets get more capital).
    - Performance: positive recent P&L boosts score.

    Args:
        asset: dict with keys:
            - confidence: float 0-1
            - volatility: float (ATR as % of price, e.g. 0.02)
            - recent_pnl: float (recent realized P&L)

    Returns:
        Composite score (0.0 to 1.0).
    """
    confidence = float(asset.get("confidence", 0.0))
    volatility = float(asset.get("volatility", 0.02))
    recent_pnl = float(asset.get("recent_pnl", 0.0))

    # Confidence score: direct (0-1)
    conf_score = min(max(confidence, 0.0), 1.0)

    # Volatility score: inverse — low vol = high score
    # Map 0-5% ATR to 1.0-0.0
    vol_score = max(1.0 - (volatility / 0.05), 0.0)

    # Performance score: normalize around 0, cap at ±1
    perf_score = 0.5 + min(max(recent_pnl * 10, -0.5), 0.5)

    return (
        CONFIDENCE_WEIGHT * conf_score
        + VOLATILITY_WEIGHT * vol_score
        + PERFORMANCE_WEIGHT * perf_score
    )


# ---------------------------------------------------------------------------
# Allocation
# ---------------------------------------------------------------------------

def allocate(asset_data: dict[str, dict], total_cash: float) -> dict[str, dict]:
    """Allocate capital across assets based on scores.

    Args:
        asset_data: Dict mapping symbol to asset info:
            {
                "BTC/USDT": {
                    "confidence": 0.8,
                    "volatility": 0.015,
                    "recent_pnl": 0.05,
                    "regime": "trending_up",
                    "position_open": False,
                },
                ...
            }
        total_cash: Total available USDT in portfolio.

    Returns:
        Dict mapping symbol to allocation decision:
            {
                "BTC/USDT": {
                    "score": 0.72,
                    "weight": 0.45,
                    "allocation_usdt": 36.0,
                    "allocation_pct": 0.45,
                    "tradeable": True,
                    "reason": "...",
                },
                ...
            }
    """
    if total_cash <= 0 or not asset_data:
        return {sym: _skip_allocation(sym, "No capital available.") for sym in asset_data}

    deployable = total_cash * (1.0 - CASH_RESERVE_PCT)

    # Step 1: Score each asset
    scores = {}
    for symbol, data in asset_data.items():
        # Skip assets already in a position
        if data.get("position_open", False):
            scores[symbol] = 0.0
        # Skip high volatility regimes
        elif data.get("regime") == "high_volatility":
            scores[symbol] = 0.0
        else:
            scores[symbol] = score_asset(data)

    total_score = sum(scores.values())

    # Step 2: Compute raw weights
    if total_score == 0:
        return {
            sym: _skip_allocation(sym, _skip_reason(scores[sym], asset_data[sym]))
            for sym in asset_data
        }

    allocations = {}

    for symbol, data in asset_data.items():
        raw_weight = scores[symbol] / total_score if total_score > 0 else 0.0

        # Step 3: Apply caps
        capped_weight = min(raw_weight, MAX_ALLOCATION_PCT)

        if 0 < capped_weight < MIN_ALLOCATION_PCT:
            capped_weight = 0.0  # Below minimum, don't bother

        # Step 4: Compute USDT amount
        alloc_usdt = deployable * capped_weight

        tradeable = capped_weight > 0 and not data.get("position_open", False)

        if not tradeable:
            reason = _skip_reason(scores[symbol], data)
        else:
            reason = (
                f"Score {scores[symbol]:.2f}, "
                f"weight {capped_weight:.1%}, "
                f"${alloc_usdt:,.2f} allocated"
            )

        allocations[symbol] = {
            "score": round(scores[symbol], 4),
            "weight": round(capped_weight, 4),
            "allocation_usdt": round(alloc_usdt, 4),
            "allocation_pct": round(capped_weight, 4),
            "tradeable": tradeable,
            "reason": reason,
        }

    return allocations


def _skip_allocation(symbol: str, reason: str) -> dict:
    """Return a zero-allocation entry.

    Args:
        symbol: Trading pair.
        reason: Why allocation was skipped.

    Returns:
        Allocation dict with zeros.
    """
    return {
        "score": 0.0,
        "weight": 0.0,
        "allocation_usdt": 0.0,
        "allocation_pct": 0.0,
        "tradeable": False,
        "reason": reason,
    }


def _skip_reason(score: float, data: dict) -> str:
    """Generate a reason for why an asset was skipped.

    Args:
        score: Asset's composite score.
        data: Asset data dict.

    Returns:
        Human-readable reason string.
    """
    if data.get("position_open"):
        return "Position already open."
    if data.get("regime") == "high_volatility":
        return "High volatility regime, skipped."
    if score == 0:
        return "Zero score, no allocation."
    return "Below minimum allocation threshold."


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_allocations(allocations: dict[str, dict], total_cash: float) -> None:
    """Print a formatted allocation summary.

    Args:
        allocations: Output from allocate().
        total_cash: Total available cash.
    """
    reserve = total_cash * CASH_RESERVE_PCT
    deployed = sum(a["allocation_usdt"] for a in allocations.values())

    print("\n" + "=" * 60)
    print("  Capital Allocation")
    print("=" * 60)
    print(f"  Total Cash:  ${total_cash:,.2f}")
    print(f"  Reserve:     ${reserve:,.2f} ({CASH_RESERVE_PCT:.0%})")
    print(f"  Deployed:    ${deployed:,.2f}")
    print("-" * 60)

    for symbol, alloc in allocations.items():
        asset = symbol.split("/")[0]
        marker = ">>>" if alloc["tradeable"] else "   "
        print(
            f"  {marker} {asset:4s}  "
            f"score={alloc['score']:.2f}  "
            f"weight={alloc['weight']:.1%}  "
            f"${alloc['allocation_usdt']:>8,.2f}  "
            f"{'TRADE' if alloc['tradeable'] else 'SKIP ':5s}  "
            f"{alloc['reason']}"
        )

    print("=" * 60)
    print()
