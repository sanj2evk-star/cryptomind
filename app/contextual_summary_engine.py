"""
contextual_summary_engine.py — CryptoMind v7.4 Chunk 3: Daily Context Summary.

Generates a daily summary covering:
    - Market behavior (dominant regime, volatility, trend direction)
    - News tone vs actual price reaction
    - What worked / what failed in trades
    - Next-day posture hint
    - Key stats (trades, PnL, win rate, mood arc)

Observer module — reads from multiple tables, writes NOTHING to execution tables.
All data is returned on-demand, not persisted (stateless compute).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, date

# Cache
_cache = None
_cache_ts = 0
_CACHE_TTL = 120  # seconds


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Sub-computations
# ---------------------------------------------------------------------------

def _market_summary(snapshots: list[dict]) -> dict:
    """Summarise market behavior from cycle snapshots."""
    if not snapshots:
        return {
            "dominant_regime": "unknown",
            "regime_changes": 0,
            "avg_quality": 0,
            "trend_bias": "flat",
            "volatility_desc": "unknown",
            "price_range_pct": 0,
            "summary": "Not enough data for a market summary.",
        }

    regimes = [s.get("regime", "SLEEPING") for s in snapshots if s.get("regime")]
    prices = [s.get("price", 0) for s in snapshots if s.get("price")]
    qualities = [s.get("market_quality_score", 0) for s in snapshots
                 if s.get("market_quality_score") is not None]
    vols = [s.get("volatility", 0) for s in snapshots if s.get("volatility")]

    # Dominant regime (most frequent)
    regime_counts = {}
    for r in regimes:
        regime_counts[r] = regime_counts.get(r, 0) + 1
    dominant = max(regime_counts, key=regime_counts.get) if regime_counts else "SLEEPING"

    # Regime changes
    changes = sum(1 for i in range(1, len(regimes)) if regimes[i] != regimes[i-1])

    # Price range
    if prices:
        hi, lo = max(prices), min(prices)
        range_pct = ((hi - lo) / max(lo, 1)) * 100
    else:
        range_pct = 0

    # Trend bias (compare first quarter avg to last quarter avg)
    if len(prices) >= 4:
        q = len(prices) // 4
        first_q = sum(prices[:q]) / q
        last_q = sum(prices[-q:]) / q
        diff = ((last_q - first_q) / max(first_q, 1)) * 100
        trend_bias = "bullish" if diff > 0.2 else "bearish" if diff < -0.2 else "flat"
    else:
        trend_bias = "flat"

    avg_vol = sum(vols) / max(len(vols), 1)
    vol_desc = "high" if avg_vol > 0.02 else "moderate" if avg_vol > 0.008 else "low"

    avg_q = round(sum(qualities) / max(len(qualities), 1))

    lines = []
    lines.append(f"Dominant regime: {dominant} ({regime_counts.get(dominant, 0)}/{len(regimes)} cycles)")
    if changes > 0:
        lines.append(f"Regime shifted {changes} time(s)")
    lines.append(f"Market quality averaged {avg_q}/100")
    lines.append(f"Price range: {range_pct:.2f}% ({vol_desc} volatility)")
    lines.append(f"Trend bias: {trend_bias}")

    return {
        "dominant_regime": dominant,
        "regime_changes": changes,
        "avg_quality": avg_q,
        "trend_bias": trend_bias,
        "volatility_desc": vol_desc,
        "price_range_pct": round(range_pct, 3),
        "summary": " ".join(lines),
    }


def _trade_summary(trades: list[dict]) -> dict:
    """Summarise trading activity."""
    if not trades:
        return {
            "total": 0,
            "buys": 0,
            "sells": 0,
            "wins": 0,
            "losses": 0,
            "net_pnl": 0,
            "win_rate": 0,
            "best_strategy": None,
            "summary": "No trades today.",
        }

    buys = [t for t in trades if t.get("action") == "BUY"]
    sells = [t for t in trades if t.get("action") == "SELL"]
    wins = [t for t in sells if (t.get("pnl", 0) or 0) > 0]
    losses = [t for t in sells if (t.get("pnl", 0) or 0) < 0]
    net_pnl = sum(t.get("pnl", 0) or 0 for t in trades)
    wr = round(len(wins) / max(len(sells), 1) * 100, 1)

    # Best strategy by count
    strat_counts = {}
    for t in trades:
        s = t.get("strategy", "unknown")
        strat_counts[s] = strat_counts.get(s, 0) + 1
    best_strat = max(strat_counts, key=strat_counts.get) if strat_counts else None

    lines = [f"{len(trades)} trades ({len(buys)} buys, {len(sells)} sells)"]
    if sells:
        lines.append(f"Win rate: {wr}% ({len(wins)}W/{len(losses)}L)")
    lines.append(f"Net PnL: {net_pnl:+.4f}")
    if best_strat:
        lines.append(f"Most active strategy: {best_strat}")

    return {
        "total": len(trades),
        "buys": len(buys),
        "sells": len(sells),
        "wins": len(wins),
        "losses": len(losses),
        "net_pnl": round(net_pnl, 6),
        "win_rate": wr,
        "best_strategy": best_strat,
        "summary": " ".join(lines),
    }


def _news_vs_price(news_analyses: list[dict], price_start: float,
                    price_end: float) -> dict:
    """Compare news sentiment tone to actual price action."""
    if not news_analyses:
        return {
            "bullish_count": 0,
            "bearish_count": 0,
            "neutral_count": 0,
            "dominant_tone": "quiet",
            "price_reaction": "flat",
            "alignment": "unknown",
            "summary": "No significant news to compare.",
        }

    bullish = sum(1 for n in news_analyses if n.get("sentiment") == "bullish")
    bearish = sum(1 for n in news_analyses if n.get("sentiment") == "bearish")
    neutral = len(news_analyses) - bullish - bearish

    dominant = "bullish" if bullish > bearish else "bearish" if bearish > bullish else "neutral"

    price_change = ((price_end - price_start) / max(price_start, 1)) * 100
    reaction = "up" if price_change > 0.1 else "down" if price_change < -0.1 else "flat"

    # Alignment check
    if dominant == "bullish" and reaction == "up":
        alignment = "aligned"
        desc = "Bullish news aligned with upward price action."
    elif dominant == "bearish" and reaction == "down":
        alignment = "aligned"
        desc = "Bearish news aligned with downward price action."
    elif dominant == "bullish" and reaction == "down":
        alignment = "divergent"
        desc = "Bullish news but price fell — sentiment didn't hold."
    elif dominant == "bearish" and reaction == "up":
        alignment = "divergent"
        desc = "Bearish news but price rose — market shrugged it off."
    else:
        alignment = "neutral"
        desc = "No strong news-price alignment to note."

    return {
        "bullish_count": bullish,
        "bearish_count": bearish,
        "neutral_count": neutral,
        "dominant_tone": dominant,
        "price_reaction": reaction,
        "price_change_pct": round(price_change, 3),
        "alignment": alignment,
        "summary": desc,
    }


def _posture_hint(market: dict, trades: dict, news_price: dict) -> dict:
    """Generate a next-day posture hint based on all summaries."""
    hints = []
    posture = "neutral"
    confidence = 0.3

    quality = market.get("avg_quality", 0)
    trend = market.get("trend_bias", "flat")
    wr = trades.get("win_rate", 0)
    alignment = news_price.get("alignment", "unknown")

    if quality >= 60 and wr >= 55:
        posture = "opportunistic"
        confidence = 0.6
        hints.append("Market quality is decent and trades are winning — stay active.")
    elif quality < 30 or (wr < 40 and trades.get("total", 0) > 3):
        posture = "defensive"
        confidence = 0.5
        hints.append("Low quality or losing streak — tighten up tomorrow.")
    elif trend == "bullish" and alignment == "aligned":
        posture = "trend_friendly"
        confidence = 0.5
        hints.append("Trend and news both bullish — lean into the direction.")
    elif alignment == "divergent":
        posture = "cautious"
        confidence = 0.4
        hints.append("News and price diverged — be skeptical of narratives.")
    else:
        hints.append("No strong signals — stay neutral and responsive.")

    return {
        "posture": posture,
        "confidence": round(confidence, 2),
        "hints": hints,
        "summary": hints[0] if hints else "Stay neutral.",
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute(session_id: int = None) -> dict:
    """Generate the daily context summary.

    Returns a dict with market, trades, news_vs_price, posture sections.
    """
    global _cache, _cache_ts
    import time
    now = time.time()
    if _cache and (now - _cache_ts) < _CACHE_TTL:
        return _cache

    import db
    import session_manager

    sid = session_id or session_manager.get_session_id()
    if not sid:
        return {"error": "No active session", "warming_up": True}

    # Get today's data
    snapshots = db.get_recent_snapshots(sid, limit=500)
    trades_list, _ = db.get_trades(session_id=sid, limit=200)
    news_list = db.get_news_analyses(limit=100)

    today = date.today().isoformat()

    # Warm-up guard: not enough data for a meaningful summary
    sells = [t for t in trades_list if t.get("action") == "SELL"]
    is_warming = len(snapshots) < 10 or (len(trades_list) < 5 and len(sells) < 2)

    if is_warming:
        result = {
            "date": today,
            "session_id": sid,
            "market": _market_summary(snapshots),
            "trades": _trade_summary(trades_list),
            "news_vs_price": {
                "summary": "Too early to draw strong conclusions.",
                "alignment": "unknown",
            },
            "posture": {
                "posture": "neutral",
                "confidence": 0.1,
                "hints": ["Not enough data yet — defaulting to neutral."],
                "summary": "Too early to draw strong conclusions.",
            },
            "warming_up": True,
        }
        _cache = result
        _cache_ts = now
        return result

    # Market summary
    market = _market_summary(snapshots)

    # Trade summary
    trade_sum = _trade_summary(trades_list)

    # News vs price
    prices = [s.get("price", 0) for s in snapshots if s.get("price")]
    price_start = prices[-1] if prices else 0  # oldest (snapshots are DESC)
    price_end = prices[0] if prices else 0     # newest
    news_price = _news_vs_price(news_list, price_start, price_end)

    # Posture hint
    posture = _posture_hint(market, trade_sum, news_price)

    # Crowd sentiment overlay (v7.5)
    crowd_data = {}
    try:
        import crowd_sentiment_engine
        crowd_data = crowd_sentiment_engine.get_belief_vs_reality()
    except Exception:
        pass

    # Signal layer overlay (v7.6)
    signal_data = {}
    try:
        from signal_layer import ENABLE_SIGNAL_LAYER
        if ENABLE_SIGNAL_LAYER:
            from signal_layer.signal_aggregator import aggregate
            agg = aggregate()
            if agg and not agg.get("warming_up"):
                composite = agg.get("composite", {})
                signal_data = {
                    "alignment": composite.get("alignment", "unclear"),
                    "tension_score": composite.get("tension_score", 0),
                    "narrative_state": composite.get("narrative_state", "calm"),
                    "overall_direction": composite.get("overall_direction", "neutral"),
                    "summary": composite.get("summary", ""),
                    "signal_count": agg.get("signal_count", 0),
                }
    except Exception:
        pass

    result = {
        "date": today,
        "session_id": sid,
        "market": market,
        "trades": trade_sum,
        "news_vs_price": news_price,
        "posture": posture,
        "crowd_vs_reality": crowd_data if crowd_data else None,
        "signal_context": signal_data if signal_data else None,
        "warming_up": False,
    }

    _cache = result
    _cache_ts = now
    return result
