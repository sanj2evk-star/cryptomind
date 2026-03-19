"""
multi_strategy.py — Multi-Strategy Trading Lab with dynamic control.

Runs 9 strategy profiles in parallel: 5 originals + 4 micro-traders.
Tracks performance, dynamically allocates capital, auto-switches the
primary strategy, kills underperformers, and revives them.

Strategies are regime-aware — some only trade in specific market states.

NO real money. Simulation only.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from auto_trader import (
    get_live_price,
    compute_indicators,
    detect_market_state,
    _score_ema, _score_rsi, _score_trend, _score_acceleration,
    W_EMA, W_RSI, W_TREND, W_MOMENTUM,
    _state as trader_state,
)

# ---------------------------------------------------------------------------
# Strategy Profiles
# ---------------------------------------------------------------------------

PROFILES = {
    # --- Original 5 ---
    "MONK":         {"label": "The Monk",       "desc": "Patient. High conviction only.",         "buy_threshold": 70, "sell_threshold": 30, "min_confidence": 0.25, "position_pct": 0.20, "cooldown": 120, "color": "#8b5cf6", "regimes": ["WAKING_UP", "ACTIVE", "BREAKOUT"]},
    "HUNTER":       {"label": "The Hunter",     "desc": "Balanced. Waits, then strikes.",         "buy_threshold": 60, "sell_threshold": 40, "min_confidence": 0.20, "position_pct": 0.40, "cooldown": 90,  "color": "#3b82f6", "regimes": ["WAKING_UP", "ACTIVE", "BREAKOUT"]},
    "AGGRESSIVE":   {"label": "The Aggressor",  "desc": "Fast and bold. Big positions.",          "buy_threshold": 55, "sell_threshold": 45, "min_confidence": 0.10, "position_pct": 0.60, "cooldown": 60,  "color": "#ef4444", "regimes": ["ACTIVE", "BREAKOUT"]},
    "DEFENSIVE":    {"label": "The Guardian",   "desc": "Ultra-safe. Tiny positions.",            "buy_threshold": 75, "sell_threshold": 25, "min_confidence": 0.30, "position_pct": 0.15, "cooldown": 180, "color": "#22c55e", "regimes": ["WAKING_UP", "ACTIVE", "BREAKOUT"]},
    "EXPERIMENTAL": {"label": "The Wildcard",   "desc": "Trades on anything. High frequency.",    "buy_threshold": 50, "sell_threshold": 50, "min_confidence": 0.05, "position_pct": 0.10, "cooldown": 30,  "color": "#eab308", "regimes": ["SLEEPING", "WAKING_UP", "ACTIVE", "BREAKOUT"]},

    # --- New Micro-Traders ---
    "SCALPER":      {"label": "Scalper",        "desc": "Micro moves. Trades frequently.",        "buy_threshold": 55, "sell_threshold": 45, "min_confidence": 0.05, "position_pct": 0.08, "cooldown": 20,  "color": "#f97316", "regimes": ["SLEEPING", "WAKING_UP", "ACTIVE", "BREAKOUT"], "max_trades_per_min": 2},
    "INTUITIVE":    {"label": "Intuitive",      "desc": "Blended signals. Trades sideways.",      "buy_threshold": 58, "sell_threshold": 42, "min_confidence": 0.10, "position_pct": 0.15, "cooldown": 45,  "color": "#06b6d4", "regimes": ["SLEEPING", "WAKING_UP", "ACTIVE"]},
    "MEAN_REVERTER":{"label": "Mean Reverter",  "desc": "RSI mean reversion. Buys dips.",        "buy_threshold": 50, "sell_threshold": 50, "min_confidence": 0.05, "position_pct": 0.12, "cooldown": 60,  "color": "#a855f7", "regimes": ["SLEEPING", "WAKING_UP"], "use_rsi_logic": True},
    "BREAKOUT_SNIPER":{"label": "Breakout Sniper","desc": "Quick entries on volatility spikes.",  "buy_threshold": 52, "sell_threshold": 48, "min_confidence": 0.08, "position_pct": 0.25, "cooldown": 30,  "color": "#f43f5e", "regimes": ["BREAKOUT", "ACTIVE"], "use_breakout_logic": True},
}

INITIAL_BALANCE = 100.0
REALLOC_INTERVAL = 60       # cycles between capital reallocation (~30 min at 30s)
MIN_ALLOC_PCT = 0.03        # 3% minimum (more strategies now)
MAX_ALLOC_PCT = 0.35        # 35% maximum
SWITCH_COOLDOWN = 60        # cycles between primary strategy switches
SWITCH_MARGIN = 2.0         # must outperform by 2% to switch
MIN_TRADES_FOR_SWITCH = 5
KILL_DRAWDOWN = 10.0
KILL_CONSEC_LOSSES = 5
KILL_MIN_WINRATE_TRADES = 10
KILL_MIN_WINRATE = 30.0
REVIVE_COOLDOWN = 120

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_strategies: dict[str, dict] = {}
_leaderboard: list[dict] = []
_cycle_count = 0
_last_market_state = {"state": "SLEEPING", "confidence_score": 0, "reason": ""}
_primary_strategy = "HUNTER"
_last_switch_cycle = 0
_last_realloc_cycle = 0
_allocations: dict[str, float] = {}
_event_log: list[dict] = []


def _log_event(event: str, **kwargs):
    """Log an adaptive engine event."""
    entry = {"timestamp": datetime.now(timezone.utc).isoformat(), "event": event, **kwargs}
    _event_log.append(entry)
    if len(_event_log) > 200:
        _event_log[:] = _event_log[-200:]
    print(f"[adaptive] {event}: {kwargs}")


def _init_strategy(name: str) -> dict:
    return {
        "name": name,
        "status": "ACTIVE",           # ACTIVE, PAUSED, INACTIVE (killed), LEADING
        "balance": INITIAL_BALANCE,
        "btc_holdings": 0.0,
        "entry_price": 0.0,
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "consecutive_losses": 0,
        "realized_pnl": 0.0,
        "peak_equity": INITIAL_BALANCE,
        "max_drawdown": 0.0,
        "last_trade_time": 0,
        "last_action": "HOLD",
        "last_reason": "",
        "trade_history": [],
        "last_10_pnl": [],
        "killed_at_cycle": 0,
        "trades_this_minute": 0,
        "minute_marker": 0,
        "allocation_pct": 1.0 / len(PROFILES),
        "_prev_market": "SLEEPING",
    }


def _ensure_initialized():
    global _strategies, _allocations
    if not _strategies:
        for name in PROFILES:
            _strategies[name] = _init_strategy(name)
        _allocations = {n: 1.0 / len(PROFILES) for n in PROFILES}


# ---------------------------------------------------------------------------
# External Controls (API-driven)
# ---------------------------------------------------------------------------

def pause_strategy(name: str) -> dict:
    """Pause a strategy — stops trading but keeps observing."""
    _ensure_initialized()
    if name not in _strategies:
        return {"error": f"Unknown strategy: {name}"}
    s = _strategies[name]
    if s["status"] == "INACTIVE":
        return {"error": f"{name} is KILLED, cannot pause. Revive first."}
    old = s["status"]
    s["status"] = "PAUSED"
    _log_event("strategy_paused", strategy=name, previous=old)
    _redistribute_allocation()
    return {"ok": True, "strategy": name, "status": "PAUSED"}


def resume_strategy(name: str) -> dict:
    """Resume a paused or killed strategy."""
    _ensure_initialized()
    if name not in _strategies:
        return {"error": f"Unknown strategy: {name}"}
    s = _strategies[name]
    if s["status"] in ("ACTIVE", "LEADING"):
        return {"error": f"{name} is already {s['status']}"}
    old = s["status"]
    s["status"] = "ACTIVE"
    s["consecutive_losses"] = 0
    _log_event("strategy_resumed", strategy=name, previous=old)
    _redistribute_allocation()
    return {"ok": True, "strategy": name, "status": "ACTIVE"}


def kill_strategy(name: str) -> dict:
    """Kill a strategy completely."""
    _ensure_initialized()
    if name not in _strategies:
        return {"error": f"Unknown strategy: {name}"}
    s = _strategies[name]
    old = s["status"]
    s["status"] = "INACTIVE"
    s["killed_at_cycle"] = _cycle_count
    _log_event("strategy_killed", strategy=name, reason=f"Manually killed (was {old})")
    _redistribute_allocation()
    if name == _primary_strategy:
        _force_switch_primary()
    return {"ok": True, "strategy": name, "status": "INACTIVE"}


def _redistribute_allocation():
    """Redistribute capital among active strategies only."""
    global _allocations
    active = [n for n in PROFILES if _strategies[n]["status"] not in ("INACTIVE", "PAUSED")]
    if not active:
        _allocations = {n: 0.0 for n in PROFILES}
        return
    share = 1.0 / len(active)
    _allocations = {n: (share if n in active else 0.0) for n in PROFILES}


def _force_switch_primary():
    """Force switch primary to best active strategy."""
    global _primary_strategy
    price = trader_state.get("last_price", 0)
    best_name = None
    best_return = -999
    for name, s in _strategies.items():
        if s["status"] in ("INACTIVE", "PAUSED"):
            continue
        p = _get_performance(name, max(price, 1))
        if p["total_return"] > best_return:
            best_return = p["total_return"]
            best_name = name
    if best_name:
        _primary_strategy = best_name
        _strategies[best_name]["status"] = "LEADING"


# ---------------------------------------------------------------------------
# Performance Tracking
# ---------------------------------------------------------------------------

def _get_performance(name: str, price: float) -> dict:
    s = _strategies[name]
    equity = s["balance"] + s["btc_holdings"] * price
    total_return = ((equity - INITIAL_BALANCE) / INITIAL_BALANCE) * 100
    trades = s["total_trades"]
    wins = s["wins"]
    losses = s["losses"]
    win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
    avg_profit = s["realized_pnl"] / trades if trades > 0 else 0

    return {
        "equity": equity,
        "total_return": total_return,
        "win_rate": win_rate,
        "trade_count": trades,
        "avg_profit": avg_profit,
        "drawdown": s["max_drawdown"],
        "last_10_return": sum(s["last_10_pnl"][-10:]),
        "consecutive_losses": s["consecutive_losses"],
    }


# ---------------------------------------------------------------------------
# Capital Allocation
# ---------------------------------------------------------------------------

def _reallocate_capital(price: float):
    global _allocations, _last_realloc_cycle
    _last_realloc_cycle = _cycle_count

    scores = {}
    for name in PROFILES:
        if _strategies[name]["status"] in ("INACTIVE", "PAUSED"):
            scores[name] = 0.0
            continue
        p = _get_performance(name, price)
        score = (
            0.4 * p["total_return"]
            + 0.3 * p["win_rate"]
            + 0.2 * (p["avg_profit"] * 10000)
            - 0.3 * p["drawdown"]
        )
        scores[name] = max(score, 0.01)

    total = sum(scores.values())
    if total <= 0:
        _redistribute_allocation()
        return

    for name in PROFILES:
        raw = scores[name] / total
        _allocations[name] = max(MIN_ALLOC_PCT if scores[name] > 0 else 0, min(MAX_ALLOC_PCT, raw))

    alloc_sum = sum(_allocations.values())
    if alloc_sum > 0:
        _allocations = {n: v / alloc_sum for n, v in _allocations.items()}

    _log_event("reallocation", allocations={n: round(v * 100, 1) for n, v in _allocations.items()})


# ---------------------------------------------------------------------------
# Auto-Switch Primary Strategy
# ---------------------------------------------------------------------------

def _check_auto_switch(price: float):
    global _primary_strategy, _last_switch_cycle

    if _cycle_count - _last_switch_cycle < SWITCH_COOLDOWN:
        return

    current_perf = _get_performance(_primary_strategy, price)
    best_name = _primary_strategy
    best_return = current_perf["total_return"]

    for name in PROFILES:
        if name == _primary_strategy:
            continue
        s = _strategies[name]
        if s["status"] in ("INACTIVE", "PAUSED"):
            continue
        p = _get_performance(name, price)
        if (p["trade_count"] >= MIN_TRADES_FOR_SWITCH
                and p["total_return"] > best_return + SWITCH_MARGIN
                and p["drawdown"] < KILL_DRAWDOWN):
            best_name = name
            best_return = p["total_return"]

    if best_name != _primary_strategy:
        old = _primary_strategy
        _strategies[old]["status"] = "ACTIVE"
        _primary_strategy = best_name
        _strategies[best_name]["status"] = "LEADING"
        _last_switch_cycle = _cycle_count
        _log_event("strategy_switch", **{"from": old, "to": best_name,
                   "reason": f"Higher return ({best_return:.2f}% vs {current_perf['total_return']:.2f}%)"})


# ---------------------------------------------------------------------------
# Kill / Revive System
# ---------------------------------------------------------------------------

def _check_kill_revive(price: float):
    for name, s in _strategies.items():
        p = _get_performance(name, price)

        # --- KILL checks (only active strategies) ---
        if s["status"] in ("ACTIVE", "LEADING"):
            killed = False
            reason = ""

            if p["drawdown"] > KILL_DRAWDOWN:
                killed = True
                reason = f"Drawdown {p['drawdown']:.1f}% > {KILL_DRAWDOWN}%"
            elif p["consecutive_losses"] >= KILL_CONSEC_LOSSES:
                killed = True
                reason = f"{p['consecutive_losses']} consecutive losses"
            elif p["trade_count"] >= KILL_MIN_WINRATE_TRADES and p["win_rate"] < KILL_MIN_WINRATE:
                killed = True
                reason = f"Win rate {p['win_rate']:.0f}% < {KILL_MIN_WINRATE}%"

            if killed:
                s["status"] = "INACTIVE"
                s["killed_at_cycle"] = _cycle_count
                _log_event("strategy_killed", strategy=name, reason=reason)
                if name == _primary_strategy:
                    _force_switch_primary()

        # --- REVIVE checks (only auto-killed, not manually paused) ---
        elif s["status"] == "INACTIVE" and s.get("killed_at_cycle", 0) > 0:
            cycles_since = _cycle_count - s["killed_at_cycle"]
            mkt = _last_market_state.get("state", "SLEEPING")

            if cycles_since >= REVIVE_COOLDOWN:
                s["status"] = "ACTIVE"
                s["consecutive_losses"] = 0
                _log_event("strategy_revived", strategy=name, reason=f"Cooldown passed ({cycles_since} cycles)")
            elif mkt in ("BREAKOUT", "ACTIVE") and s.get("_prev_market") == "SLEEPING":
                s["status"] = "ACTIVE"
                s["consecutive_losses"] = 0
                _log_event("strategy_revived", strategy=name, reason=f"Market changed to {mkt}")

        s["_prev_market"] = _last_market_state.get("state", "SLEEPING")


# ---------------------------------------------------------------------------
# Per-Strategy Decision + Execution
# ---------------------------------------------------------------------------

def _run_strategy(name: str, indicators: dict, market_state: dict, price: float) -> dict:
    """Run decision + execution for one strategy."""
    s = _strategies[name]
    profile = PROFILES[name]
    mkt = market_state["state"]

    # Skip killed strategies completely
    if s["status"] == "INACTIVE":
        s["last_action"] = "HOLD"
        s["last_reason"] = "KILLED"
        return {"action": "HOLD", "pnl": 0.0}

    # Paused — observe but don't trade
    if s["status"] == "PAUSED":
        s["last_action"] = "HOLD"
        s["last_reason"] = "PAUSED — observing"
        return {"action": "HOLD", "pnl": 0.0}

    # Regime filter — check if this strategy trades in current regime
    allowed_regimes = profile.get("regimes", ["WAKING_UP", "ACTIVE", "BREAKOUT"])
    if mkt not in allowed_regimes:
        s["last_action"] = "HOLD"
        s["last_reason"] = f"Regime {mkt} — not active"
        return {"action": "HOLD", "pnl": 0.0}

    # Compute scores
    ema_score = _score_ema(indicators["ema_short"], indicators["ema_long"])
    rsi_score = _score_rsi(indicators["rsi"])
    trend_score = _score_trend(indicators["slope"], indicators["momentum"])
    accel_score = _score_acceleration(indicators.get("acceleration", 0))
    total_score = round(ema_score * W_EMA + rsi_score * W_RSI + trend_score * W_TREND + accel_score * W_MOMENTUM, 2)

    buy_t = profile["buy_threshold"]
    sell_t = profile["sell_threshold"]
    confidence = round(min(abs(total_score - (buy_t + sell_t) / 2) / 50, 0.95), 2)
    reasons = []

    btc = s["btc_holdings"]
    cash = s["balance"]
    action = "HOLD"

    # --- Special logic: Mean Reverter (RSI-based) ---
    if profile.get("use_rsi_logic"):
        rsi = indicators.get("rsi", 50)
        if rsi < 40 and cash > 1.0 and btc < 0.0001:
            action = "BUY"
            reasons.append(f"RSI {rsi:.0f} < 40 — oversold")
        elif rsi > 60 and btc > 0:
            action = "SELL"
            reasons.append(f"RSI {rsi:.0f} > 60 — overbought")

    # --- Special logic: Breakout Sniper ---
    elif profile.get("use_breakout_logic"):
        vol = indicators.get("volatility", 0)
        accel = indicators.get("acceleration", 0)
        if vol > 0.001 and accel > 15 and cash > 1.0 and btc < 0.0001:
            action = "BUY"
            reasons.append(f"Breakout: vol={vol:.4f} accel={accel:.1f}")
        elif btc > 0 and (accel < -10 or total_score < sell_t):
            action = "SELL"
            reasons.append(f"Exit breakout: accel={accel:.1f}")

    # --- Standard scoring logic ---
    else:
        if total_score >= buy_t and cash > 1.0 and btc < 0.0001:
            action = "BUY"
            reasons.append(f"Score {total_score:.0f} >= {buy_t}")
        elif total_score <= sell_t and btc > 0:
            action = "SELL"
            reasons.append(f"Score {total_score:.0f} <= {sell_t}")

    # Confidence filter
    if action != "HOLD" and confidence < profile["min_confidence"]:
        action = "HOLD"
        reasons.append(f"Low confidence ({confidence:.0%})")

    # Cooldown
    since = time.time() - s["last_trade_time"]
    if action != "HOLD" and since < profile["cooldown"]:
        action = "HOLD"
        reasons.append(f"Cooldown ({int(profile['cooldown'] - since)}s)")

    # Rate limit (max trades per minute)
    max_tpm = profile.get("max_trades_per_min", 5)
    current_minute = int(time.time() / 60)
    if current_minute != s["minute_marker"]:
        s["minute_marker"] = current_minute
        s["trades_this_minute"] = 0
    if action != "HOLD" and s["trades_this_minute"] >= max_tpm:
        action = "HOLD"
        reasons.append(f"Rate limit ({max_tpm}/min)")

    # Anti flip-flop: prevent buy→sell or sell→buy within 2 cycles
    if action != "HOLD" and s["last_action"] != "HOLD" and action != s["last_action"] and since < profile["cooldown"] * 1.5:
        action = "HOLD"
        reasons.append("Anti flip-flop")

    # Execute
    pnl = 0.0
    if action == "BUY":
        alloc = _allocations.get(name, 0.1)
        spend = cash * profile["position_pct"] * max(alloc * len(PROFILES), 0.5)
        spend = min(spend, cash * 0.95)  # never use all cash
        qty = spend / price
        s["balance"] -= spend
        s["btc_holdings"] += qty
        s["entry_price"] = price
        s["total_trades"] += 1
        s["last_trade_time"] = time.time()
        s["trades_this_minute"] += 1
        reasons.append(f"Bought {qty:.6f} BTC @ ${price:,.2f}")

    elif action == "SELL" and btc > 0:
        revenue = btc * price
        pnl = (price - s["entry_price"]) * btc
        s["balance"] += revenue
        s["btc_holdings"] = 0.0
        s["realized_pnl"] += pnl
        s["total_trades"] += 1
        s["last_trade_time"] = time.time()
        s["trades_this_minute"] += 1
        s["last_10_pnl"].append(pnl)
        if len(s["last_10_pnl"]) > 10:
            s["last_10_pnl"] = s["last_10_pnl"][-10:]
        if pnl > 0:
            s["wins"] += 1
            s["consecutive_losses"] = 0
        else:
            s["losses"] += 1
            s["consecutive_losses"] += 1
        reasons.append(f"Sold. PnL: ${pnl:.6f}")

    # Equity tracking
    equity = s["balance"] + s["btc_holdings"] * price
    if equity > s["peak_equity"]:
        s["peak_equity"] = equity
    dd = (s["peak_equity"] - equity) / s["peak_equity"] * 100 if s["peak_equity"] > 0 else 0
    if dd > s["max_drawdown"]:
        s["max_drawdown"] = dd

    s["last_action"] = action
    s["last_reason"] = ". ".join(reasons[:3]) if reasons else "Neutral"

    # Trade log with full context
    if action != "HOLD":
        s["trade_history"].append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action, "price": round(price, 2),
            "pnl": round(pnl, 6), "score": total_score,
            "confidence": confidence, "market_state": mkt,
            "strategy": name,
            "indicators": {
                "rsi": round(indicators.get("rsi", 0), 1),
                "trend": indicators.get("trend", "unknown"),
                "volatility": round(indicators.get("volatility", 0), 5),
            },
            "reasons": reasons,
        })
        if len(s["trade_history"]) > 100:
            s["trade_history"] = s["trade_history"][-100:]

    return {"action": action, "pnl": pnl}


# ---------------------------------------------------------------------------
# Main Cycle
# ---------------------------------------------------------------------------

def run_multi_cycle(price: float = 0, indicators: dict = None) -> dict:
    global _cycle_count, _last_market_state, _leaderboard

    _ensure_initialized()

    if price <= 0:
        price = get_live_price()
    if price <= 0:
        return {"error": "No price data"}

    if indicators is None:
        indicators = compute_indicators(trader_state["price_history"])

    prev = _last_market_state.get("state", "SLEEPING")
    mkt = detect_market_state(indicators, prev)
    _last_market_state = mkt

    # Run all strategies
    for name in PROFILES:
        _run_strategy(name, indicators, mkt, price)

    _cycle_count += 1

    # Periodic capital reallocation
    if _cycle_count - _last_realloc_cycle >= REALLOC_INTERVAL:
        _reallocate_capital(price)

    # Auto-switch + kill/revive
    _check_auto_switch(price)
    _check_kill_revive(price)

    # Mark primary as LEADING (skip paused/killed)
    for name, s in _strategies.items():
        if s["status"] in ("ACTIVE", "LEADING"):
            s["status"] = "LEADING" if name == _primary_strategy else "ACTIVE"

    _leaderboard = _compute_leaderboard(price)

    return {"cycle": _cycle_count, "price": price, "market_state": mkt, "leaderboard": _leaderboard}


def _compute_leaderboard(price: float) -> list[dict]:
    board = []
    for name, s in _strategies.items():
        p = _get_performance(name, price)
        board.append({
            "strategy": name,
            "label": PROFILES[name]["label"],
            "color": PROFILES[name]["color"],
            "desc": PROFILES[name]["desc"],
            "status": s["status"],
            "equity": round(p["equity"], 4),
            "total_return": round(p["total_return"], 2),
            "total_trades": p["trade_count"],
            "wins": s["wins"],
            "losses": s["losses"],
            "win_rate": round(p["win_rate"], 1),
            "avg_profit": round(p["avg_profit"], 6),
            "max_drawdown": round(p["drawdown"], 2),
            "last_action": s["last_action"],
            "last_reason": s["last_reason"],
            "position_open": s["btc_holdings"] > 0.0001,
            "allocation_pct": round(_allocations.get(name, 0) * 100, 1),
            "consecutive_losses": s["consecutive_losses"],
            "regimes": PROFILES[name].get("regimes", []),
        })
    board.sort(key=lambda x: x["total_return"], reverse=True)
    for i, entry in enumerate(board):
        entry["rank"] = i + 1
    return board


def get_event_log() -> list:
    """Return full event log (newest first)."""
    _ensure_initialized()
    return _event_log[::-1]


def get_leaderboard() -> dict:
    _ensure_initialized()
    price = trader_state.get("last_price", 0)
    return {
        "cycle": _cycle_count,
        "primary_strategy": _primary_strategy,
        "leaderboard": _leaderboard,
        "market_state": _last_market_state,
        "allocations": {n: round(v * 100, 1) for n, v in _allocations.items()},
        "event_log": _event_log[-30:][::-1],
        "strategies": {
            name: {
                "profile": {k: v for k, v in PROFILES[name].items() if k not in ("color",)},
                "status": s["status"],
                "equity": round(s["balance"] + s["btc_holdings"] * price, 4),
                "balance": round(s["balance"], 4),
                "btc_holdings": round(s["btc_holdings"], 8),
                "total_trades": s["total_trades"],
                "realized_pnl": round(s["realized_pnl"], 6),
                "allocation_pct": round(_allocations.get(name, 0) * 100, 1),
                "last_action": s["last_action"],
                "last_reason": s["last_reason"],
                "consecutive_losses": s["consecutive_losses"],
                "recent_trades": s["trade_history"][-5:][::-1],
            }
            for name, s in _strategies.items()
        },
    }
