"""
multi_strategy.py — Multi-strategy simulation engine with leaderboard.

Runs 5 strategy profiles in parallel against the same price feed.
Each strategy has its own portfolio, thresholds, and trade history.
A leaderboard ranks them by total return in real-time.

Strategies:
  MONK        — patient, high conviction, few trades
  HUNTER      — balanced, moderate aggression
  AGGRESSIVE  — fast, low thresholds, big positions
  DEFENSIVE   — ultra-safe, tiny positions
  EXPERIMENTAL— wild card, trades on anything

NO real money. Simulation only.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from auto_trader import (
    get_live_price,
    compute_indicators,
    detect_market_state,
    _score_ema,
    _score_rsi,
    _score_trend,
    _score_acceleration,
    W_EMA, W_RSI, W_TREND, W_MOMENTUM,
    COOLDOWN_SECONDS,
    _state as trader_state,
)

# ---------------------------------------------------------------------------
# Strategy Profiles
# ---------------------------------------------------------------------------

PROFILES = {
    "MONK": {
        "label": "The Monk",
        "desc": "Patient. High conviction only. Few but precise trades.",
        "buy_threshold": 70,
        "sell_threshold": 30,
        "min_confidence": 0.25,
        "position_pct": 0.20,
        "cooldown": 120,
        "color": "#8b5cf6",
    },
    "HUNTER": {
        "label": "The Hunter",
        "desc": "Balanced. Waits for good setups, acts decisively.",
        "buy_threshold": 60,
        "sell_threshold": 40,
        "min_confidence": 0.20,
        "position_pct": 0.40,
        "cooldown": 90,
        "color": "#3b82f6",
    },
    "AGGRESSIVE": {
        "label": "The Aggressor",
        "desc": "Fast and bold. Big positions, tight thresholds.",
        "buy_threshold": 55,
        "sell_threshold": 45,
        "min_confidence": 0.10,
        "position_pct": 0.60,
        "cooldown": 60,
        "color": "#ef4444",
    },
    "DEFENSIVE": {
        "label": "The Guardian",
        "desc": "Ultra-safe. Tiny positions, massive conviction required.",
        "buy_threshold": 75,
        "sell_threshold": 25,
        "min_confidence": 0.30,
        "position_pct": 0.15,
        "cooldown": 180,
        "color": "#22c55e",
    },
    "EXPERIMENTAL": {
        "label": "The Wildcard",
        "desc": "Trades on anything. Low conviction, small size, high frequency.",
        "buy_threshold": 50,
        "sell_threshold": 50,
        "min_confidence": 0.05,
        "position_pct": 0.10,
        "cooldown": 30,
        "color": "#eab308",
    },
}

INITIAL_BALANCE = 100.0

# ---------------------------------------------------------------------------
# State — each strategy has its own portfolio
# ---------------------------------------------------------------------------

_multi_state: dict[str, dict] = {}
_leaderboard: list[dict] = []
_cycle_count = 0
_last_market_state = {"state": "SLEEPING", "confidence_score": 0, "reason": ""}


def _init_strategy(name: str) -> dict:
    """Initialize a strategy's state."""
    return {
        "name": name,
        "balance": INITIAL_BALANCE,
        "btc_holdings": 0.0,
        "entry_price": 0.0,
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "realized_pnl": 0.0,
        "peak_equity": INITIAL_BALANCE,
        "max_drawdown": 0.0,
        "last_trade_time": 0,
        "last_action": "HOLD",
        "last_reason": "",
        "trade_history": [],
    }


def _ensure_initialized():
    """Make sure all strategies are initialized."""
    global _multi_state
    if not _multi_state:
        for name in PROFILES:
            _multi_state[name] = _init_strategy(name)


# ---------------------------------------------------------------------------
# Per-Strategy Decision Engine
# ---------------------------------------------------------------------------

def _run_strategy_decision(
    name: str,
    profile: dict,
    indicators: dict,
    market_state: dict,
    price: float,
) -> dict:
    """Run decision logic for a single strategy.

    Returns dict with action, score, confidence, reasons.
    """
    state = _multi_state[name]
    mkt = market_state["state"]

    # Compute scores (same for all strategies — shared indicators)
    ema_score = _score_ema(indicators["ema_short"], indicators["ema_long"])
    rsi_score = _score_rsi(indicators["rsi"])
    trend_score = _score_trend(indicators["slope"], indicators["momentum"])
    accel_score = _score_acceleration(indicators.get("acceleration", 0))

    total_score = round(
        ema_score * W_EMA + rsi_score * W_RSI
        + trend_score * W_TREND + accel_score * W_MOMENTUM, 2
    )

    # Confidence from score distance
    buy_t = profile["buy_threshold"]
    sell_t = profile["sell_threshold"]
    mid = (buy_t + sell_t) / 2
    confidence = round(min(abs(total_score - mid) / 50, 0.95), 2)

    reasons = []

    # Market state filter
    if mkt == "SLEEPING" and name != "EXPERIMENTAL":
        return {
            "action": "HOLD", "score": total_score, "confidence": confidence,
            "reasons": ["Market SLEEPING — waiting"],
        }

    # Determine action
    btc = state["btc_holdings"]
    cash = state["balance"]

    if total_score >= buy_t and cash > 1.0:
        action = "BUY"
        reasons.append(f"Score {total_score:.0f} >= buy threshold {buy_t}")
    elif total_score <= sell_t and btc > 0:
        action = "SELL"
        reasons.append(f"Score {total_score:.0f} <= sell threshold {sell_t}")
    else:
        action = "HOLD"
        reasons.append(f"Score {total_score:.0f} in neutral zone ({sell_t}–{buy_t})")

    # Confidence filter
    if action != "HOLD" and confidence < profile["min_confidence"]:
        reasons.append(f"Confidence {confidence:.0%} < min {profile['min_confidence']:.0%}")
        action = "HOLD"

    # Cooldown
    since_last = time.time() - state["last_trade_time"]
    if action != "HOLD" and since_last < profile["cooldown"]:
        remaining = int(profile["cooldown"] - since_last)
        reasons.append(f"Cooldown: {remaining}s left")
        action = "HOLD"

    # Max 1 position
    if action == "BUY" and btc > 0.0001:
        reasons.append("Already holding — max 1 position")
        action = "HOLD"

    return {
        "action": action,
        "score": total_score,
        "confidence": confidence,
        "reasons": reasons,
    }


# ---------------------------------------------------------------------------
# Trade Execution
# ---------------------------------------------------------------------------

def _execute_strategy_trade(name: str, decision: dict, price: float) -> dict:
    """Execute a paper trade for a specific strategy."""
    state = _multi_state[name]
    profile = PROFILES[name]
    action = decision["action"]

    result = {"action": "HOLD", "pnl": 0.0, "qty": 0.0}

    if action == "BUY" and state["balance"] > 1.0:
        spend = state["balance"] * profile["position_pct"]
        qty = spend / price
        state["balance"] -= spend
        state["btc_holdings"] += qty
        state["entry_price"] = price
        state["total_trades"] += 1
        state["last_trade_time"] = time.time()
        result = {"action": "BUY", "pnl": 0.0, "qty": qty}

    elif action == "SELL" and state["btc_holdings"] > 0:
        qty = state["btc_holdings"]
        revenue = qty * price
        pnl = (price - state["entry_price"]) * qty
        state["balance"] += revenue
        state["btc_holdings"] = 0.0
        state["realized_pnl"] += pnl
        state["total_trades"] += 1
        state["last_trade_time"] = time.time()
        if pnl > 0:
            state["wins"] += 1
        elif pnl < 0:
            state["losses"] += 1
        result = {"action": "SELL", "pnl": pnl, "qty": qty}

    # Track equity + drawdown
    equity = state["balance"] + state["btc_holdings"] * price
    if equity > state["peak_equity"]:
        state["peak_equity"] = equity
    dd = (state["peak_equity"] - equity) / state["peak_equity"] * 100 if state["peak_equity"] > 0 else 0
    if dd > state["max_drawdown"]:
        state["max_drawdown"] = dd

    state["last_action"] = action
    state["last_reason"] = ". ".join(decision["reasons"][:2])

    # Log trade
    if action != "HOLD":
        state["trade_history"].append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "price": round(price, 2),
            "qty": round(result["qty"], 8),
            "pnl": round(result["pnl"], 6),
            "score": decision["score"],
            "confidence": decision["confidence"],
            "reasons": decision["reasons"],
        })
        # Keep last 50
        if len(state["trade_history"]) > 50:
            state["trade_history"] = state["trade_history"][-50:]

    return result


# ---------------------------------------------------------------------------
# Main Cycle + Leaderboard
# ---------------------------------------------------------------------------

def run_multi_cycle(price: float = 0, indicators: dict = None) -> dict:
    """Run one cycle for all strategies.

    Uses shared price and indicators from the main auto_trader.
    """
    global _cycle_count, _last_market_state, _leaderboard

    _ensure_initialized()

    if price <= 0:
        price = get_live_price()
    if price <= 0:
        return {"error": "No price data"}

    if indicators is None:
        indicators = compute_indicators(trader_state["price_history"])

    # Market state
    prev = _last_market_state.get("state", "SLEEPING")
    mkt = detect_market_state(indicators, prev)
    _last_market_state = mkt

    # Run each strategy
    results = {}
    for name, profile in PROFILES.items():
        decision = _run_strategy_decision(name, profile, indicators, mkt, price)
        trade_result = _execute_strategy_trade(name, decision, price)
        results[name] = {
            "decision": decision,
            "trade": trade_result,
        }

    _cycle_count += 1

    # Update leaderboard
    _leaderboard = _compute_leaderboard(price)

    return {
        "cycle": _cycle_count,
        "price": price,
        "market_state": mkt,
        "results": results,
        "leaderboard": _leaderboard,
    }


def _compute_leaderboard(price: float) -> list[dict]:
    """Compute and sort the strategy leaderboard."""
    board = []
    for name, state in _multi_state.items():
        equity = state["balance"] + state["btc_holdings"] * price
        total_return = ((equity - INITIAL_BALANCE) / INITIAL_BALANCE) * 100
        total_trades = state["total_trades"]
        wins = state["wins"]
        losses = state["losses"]
        win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
        avg_profit = state["realized_pnl"] / total_trades if total_trades > 0 else 0

        board.append({
            "strategy": name,
            "label": PROFILES[name]["label"],
            "color": PROFILES[name]["color"],
            "equity": round(equity, 4),
            "total_return": round(total_return, 2),
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 1),
            "avg_profit": round(avg_profit, 6),
            "max_drawdown": round(state["max_drawdown"], 2),
            "last_action": state["last_action"],
            "last_reason": state["last_reason"],
            "position_open": state["btc_holdings"] > 0.0001,
        })

    board.sort(key=lambda x: x["total_return"], reverse=True)

    # Add rank
    for i, entry in enumerate(board):
        entry["rank"] = i + 1

    return board


def get_leaderboard() -> dict:
    """Get current leaderboard + strategy details for the API."""
    _ensure_initialized()
    return {
        "cycle": _cycle_count,
        "leaderboard": _leaderboard,
        "market_state": _last_market_state,
        "strategies": {
            name: {
                "profile": {k: v for k, v in PROFILES[name].items() if k != "color"},
                "equity": round(s["balance"] + s["btc_holdings"] * trader_state.get("last_price", 0), 4),
                "balance": round(s["balance"], 4),
                "btc_holdings": round(s["btc_holdings"], 8),
                "total_trades": s["total_trades"],
                "realized_pnl": round(s["realized_pnl"], 6),
                "last_action": s["last_action"],
                "last_reason": s["last_reason"],
                "recent_trades": s["trade_history"][-5:][::-1],
            }
            for name, s in _multi_state.items()
        },
    }
