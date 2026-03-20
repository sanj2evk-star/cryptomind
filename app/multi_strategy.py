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
# State — SINGLE GLOBAL PORTFOLIO
# ---------------------------------------------------------------------------

# The ONE source of truth
_portfolio = {
    "total_cash": INITIAL_BALANCE,
    "total_btc": 0.0,
}

_strategies: dict[str, dict] = {}
_leaderboard: list[dict] = []
_cycle_count = 0
_probe_this_cycle = -1  # track: only 1 probe entry per cycle
_last_market_state = {"state": "SLEEPING", "confidence_score": 0, "reason": ""}
_primary_strategy = "HUNTER"
_last_switch_cycle = 0
_last_realloc_cycle = 0
_allocations: dict[str, float] = {}
_event_log: list[dict] = []
_last_any_trade_cycle = 0  # track: last cycle ANY strategy traded (anti-paralysis)
_prev_volatility = 0.0  # track: previous cycle volatility for "expanding" check
_cycle_trades: list[dict] = []  # trades executed THIS cycle (for split-brain fix)


def _log_event(event: str, **kwargs):
    """Log an adaptive engine event."""
    entry = {"timestamp": datetime.now(timezone.utc).isoformat(), "event": event, **kwargs}
    _event_log.append(entry)
    if len(_event_log) > 200:
        _event_log[:] = _event_log[-200:]
    print(f"[adaptive] {event}: {kwargs}")


def _init_strategy(name: str) -> dict:
    """Strategy tracks its OWN performance, but draws from global portfolio."""
    return {
        "name": name,
        "status": "ACTIVE",           # ACTIVE, PAUSED, INACTIVE (killed), LEADING
        # Virtual tracking (no separate balance — uses global pool)
        "btc_holdings": 0.0,          # BTC this strategy is holding
        "entry_price": 0.0,
        "cash_used": 0.0,             # how much cash this strategy has locked in trades
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "consecutive_losses": 0,
        "realized_pnl": 0.0,          # cumulative P&L from closed trades
        "peak_virtual_equity": 0.0,   # for drawdown calc
        "max_drawdown": 0.0,
        "last_trade_time": 0,
        "last_action": "HOLD",
        "last_reason": "",
        "trade_history": [],
        "last_10_pnl": [],
        "killed_at_cycle": 0,
        "trades_this_minute": 0,
        "minute_marker": 0,
        "entry_condition_met": False,
        "_prev_market": "SLEEPING",
    }


def _get_global_equity(price: float) -> float:
    """Total portfolio value = cash + all BTC positions."""
    btc_value = sum(s["btc_holdings"] * price for s in _strategies.values())
    return _portfolio["total_cash"] + btc_value


def _get_strategy_virtual_equity(name: str, price: float) -> float:
    """Virtual equity for a strategy = allocated capital + unrealized + realized PnL."""
    s = _strategies[name]
    alloc_pct = _allocations.get(name, 0)
    base_alloc = INITIAL_BALANCE * alloc_pct  # what it was given
    unrealized = (price - s["entry_price"]) * s["btc_holdings"] if s["btc_holdings"] > 0 else 0
    return base_alloc + s["realized_pnl"] + unrealized


def _ensure_initialized():
    global _strategies, _allocations
    if not _strategies:
        for name in PROFILES:
            _strategies[name] = _init_strategy(name)
        n = len(PROFILES)
        _allocations = {name: 1.0 / n for name in PROFILES}
        # Set initial peak equity
        for name in PROFILES:
            _strategies[name]["peak_virtual_equity"] = INITIAL_BALANCE / n


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
    alloc_pct = _allocations.get(name, 1.0 / len(PROFILES))
    allocated_capital = round(INITIAL_BALANCE * alloc_pct, 4)
    virtual_equity = _get_strategy_virtual_equity(name, price)
    base = INITIAL_BALANCE * alloc_pct
    total_return = ((virtual_equity - base) / base * 100) if base > 0 else 0

    trades = s["total_trades"]
    wins = s["wins"]
    losses = s["losses"]
    win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
    avg_profit = s["realized_pnl"] / trades if trades > 0 else 0

    return {
        "allocated_capital": allocated_capital,
        "virtual_equity": round(virtual_equity, 4),
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
            last_revive = s.get("last_revive_cycle", 0)
            revive_cooldown_met = (_cycle_count - last_revive) > 60  # min 60 cycles between revives
            mkt = _last_market_state.get("state", "SLEEPING")
            prev_mkt = s.get("_prev_market", "SLEEPING")
            profile = PROFILES.get(name, {})

            revive = False
            reason = ""

            # A. Market regime changed + strategy fits new regime
            if revive_cooldown_met and mkt != prev_mkt:
                regime_fit = profile.get("regimes", [])
                if mkt in regime_fit:
                    revive = True
                    reason = f"Market → {mkt} (strategy fits this regime)"

            # B. Volatility shift matches strategy type
            if not revive and revive_cooldown_met:
                vol = _last_market_state.get("volatility", 0)
                if name in ("BREAKOUT_SNIPER", "AGGRESSIVE") and mkt in ("BREAKOUT", "ACTIVE"):
                    revive = True
                    reason = f"Volatility rising, {mkt} detected"
                elif name in ("MEAN_REVERTER", "MONK", "DEFENSIVE") and mkt == "SLEEPING":
                    revive = True
                    reason = f"Low volatility SLEEPING market suits {name}"

            # C. Cooling period passed
            if not revive and cycles_since >= REVIVE_COOLDOWN and revive_cooldown_met:
                revive = True
                reason = f"Cooldown passed ({cycles_since} cycles)"

            # D. Portfolio imbalance — too few active strategies
            if not revive and revive_cooldown_met:
                active_count = sum(1 for n, st in _strategies.items() if st["status"] in ("ACTIVE", "LEADING"))
                if active_count < 3:
                    revive = True
                    reason = f"Only {active_count} active strategies — rebalancing"

            if revive:
                s["status"] = "ACTIVE"
                s["consecutive_losses"] = 0
                s["last_revive_cycle"] = _cycle_count
                # Start with small allocation (5%)
                _allocations[name] = 0.05
                _log_event("strategy_revived", strategy=name, reason=reason)
                # Also log to adaptive learner
                try:
                    import adaptive_learner
                    adaptive_learner._log_adaptation({
                        "type": "auto_revive", "strategy": name, "reason": reason,
                        "regime": mkt, "cycles_inactive": cycles_since,
                    })
                except Exception:
                    pass

        s["_prev_market"] = _last_market_state.get("state", "SLEEPING")


# ---------------------------------------------------------------------------
# Per-Strategy Decision + Execution
# ---------------------------------------------------------------------------

def _run_strategy(name: str, indicators: dict, market_state: dict, price: float) -> dict:
    """Run decision + execution for one strategy."""
    global _probe_this_cycle, _last_any_trade_cycle
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
    # (SLEEPING blocked strategies can still fire the SLEEPING probe below)
    allowed_regimes = profile.get("regimes", ["WAKING_UP", "ACTIVE", "BREAKOUT"])
    regime_blocked = mkt not in allowed_regimes
    if regime_blocked and mkt != "SLEEPING":
        # Non-SLEEPING regime mismatch → hard block
        s["last_action"] = "HOLD"
        s["last_reason"] = f"Regime {mkt} — not active"
        return {"action": "HOLD", "pnl": 0.0}

    # Compute raw indicator values
    ema_short = indicators["ema_short"]
    ema_long = indicators["ema_long"]
    rsi = indicators.get("rsi", 50)
    slope = indicators.get("slope", 0)
    momentum = indicators.get("momentum", 0)
    accel = indicators.get("acceleration", 0)
    vol = indicators.get("volatility", 0)

    # Global score (for dashboard display + conservative strategies)
    ema_score = _score_ema(ema_short, ema_long)
    rsi_score = _score_rsi(rsi)
    trend_score = _score_trend(slope, momentum)
    accel_score = _score_acceleration(accel)
    total_score = round(ema_score * W_EMA + rsi_score * W_RSI + trend_score * W_TREND + accel_score * W_MOMENTUM, 2)

    # ── Dynamic Hold Zone: narrow thresholds when market regime improves ──
    base_buy_t = profile["buy_threshold"]
    base_sell_t = profile["sell_threshold"]
    regime = mkt.get("state", "SLEEPING") if isinstance(mkt, dict) else str(mkt)
    hold_zone_adj = {"SLEEPING": 0, "WAKING_UP": -3, "ACTIVE": -5, "BREAKOUT": -7}.get(regime, 0)
    buy_t = base_buy_t + hold_zone_adj        # lower buy threshold in active markets
    sell_t = base_sell_t - hold_zone_adj       # raise sell threshold in active markets
    confidence = round(min(abs(total_score - (buy_t + sell_t) / 2) / 50, 0.95), 2)
    reasons = []
    entry_met = False  # track if native entry condition was met
    is_probe = False   # probe entry flag

    btc = s["btc_holdings"]
    global_cash = _portfolio["total_cash"]
    alloc_pct = _allocations.get(name, 1.0 / len(PROFILES))
    available_cash = global_cash * alloc_pct
    action = "HOLD"

    # ══════════════════════════════════════════════════════════
    # STRATEGY-NATIVE ENTRY LOGIC (each strategy decides independently)
    # Skip if strategy is regime-blocked (SLEEPING probe handled separately below)
    # ══════════════════════════════════════════════════════════

    if regime_blocked:
        pass  # skip native entry — only SLEEPING probe can fire below
    elif name == "SCALPER":
        # Scalper: micro movements — EMA spread expansion OR momentum flip
        ema_spread = abs(ema_short - ema_long) / ema_long * 100 if ema_long > 0 else 0
        mom_positive = momentum > 0 and accel > 2
        mom_negative = momentum < 0 and accel < -2
        if btc < 0.0001 and available_cash > 0.3:
            if ema_spread > 0.01 and mom_positive:
                action = "BUY"
                entry_met = True
                reasons.append(f"Scalp: spread={ema_spread:.3f}% mom={momentum:.1f} accel={accel:.1f}")
            elif rsi < 35:
                action = "BUY"
                entry_met = True
                reasons.append(f"Scalp dip: RSI={rsi:.0f}")
        elif btc > 0:
            if mom_negative or rsi > 65 or (ema_short < ema_long and accel < 0):
                action = "SELL"
                entry_met = True
                reasons.append(f"Scalp exit: mom={momentum:.1f} RSI={rsi:.0f}")

    elif name == "MEAN_REVERTER":
        # Mean Reverter: RSI snapback — trade oversold/overbought
        if btc < 0.0001 and available_cash > 0.3:
            if rsi < 38:
                action = "BUY"
                entry_met = True
                reasons.append(f"Mean revert BUY: RSI={rsi:.0f} oversold")
            elif rsi < 45 and slope > 0 and momentum > 0:
                action = "BUY"
                entry_met = True
                reasons.append(f"Mean revert early: RSI={rsi:.0f} turning up")
        elif btc > 0:
            if rsi > 58:
                action = "SELL"
                entry_met = True
                reasons.append(f"Mean revert SELL: RSI={rsi:.0f} overbought")
            elif rsi > 52 and slope < 0:
                action = "SELL"
                entry_met = True
                reasons.append(f"Mean revert exit: RSI={rsi:.0f} fading")

    elif name == "INTUITIVE":
        # Intuitive: partial signal agreement — 2 of 3 signals aligning
        signals_bullish = 0
        signals_bearish = 0
        if ema_short > ema_long: signals_bullish += 1
        else: signals_bearish += 1
        if rsi < 45: signals_bullish += 1
        elif rsi > 55: signals_bearish += 1
        if momentum > 0 and accel > 0: signals_bullish += 1
        elif momentum < 0 and accel < 0: signals_bearish += 1
        if vol > 0.0002: signals_bullish += 0.5; signals_bearish += 0.5  # volatility = opportunity

        if btc < 0.0001 and available_cash > 0.3 and signals_bullish >= 2:
            action = "BUY"
            entry_met = True
            reasons.append(f"Intuitive: {signals_bullish:.0f} bullish signals (EMA/RSI/mom)")
        elif btc > 0 and signals_bearish >= 2:
            action = "SELL"
            entry_met = True
            reasons.append(f"Intuitive exit: {signals_bearish:.0f} bearish signals")

    elif name == "BREAKOUT_SNIPER":
        # Breakout Sniper: volatility expansion + acceleration spike
        vol_expanding = vol > 0.0005
        accel_spike = abs(accel) > 8
        price_displacement = abs(ema_short - ema_long) / ema_long * 100 > 0.02 if ema_long > 0 else False
        if btc < 0.0001 and available_cash > 0.3:
            if vol_expanding and accel_spike and accel > 0:
                action = "BUY"
                entry_met = True
                reasons.append(f"Breakout BUY: vol={vol:.4f} accel={accel:.1f}")
            elif price_displacement and accel > 5 and momentum > 0:
                action = "BUY"
                entry_met = True
                reasons.append(f"Displacement BUY: accel={accel:.1f} mom={momentum:.1f}")
        elif btc > 0:
            if accel < -5 or (momentum < 0 and rsi > 55):
                action = "SELL"
                entry_met = True
                reasons.append(f"Breakout exit: accel={accel:.1f}")

    elif name == "EXPERIMENTAL":
        # Wildcard: trades on anything — very low bar
        if btc < 0.0001 and available_cash > 0.3:
            if total_score > 52 or (rsi < 40 and momentum > 0) or (accel > 5 and ema_short > ema_long):
                action = "BUY"
                entry_met = True
                reasons.append(f"Wildcard: score={total_score:.0f} RSI={rsi:.0f} accel={accel:.1f}")
        elif btc > 0:
            if total_score < 48 or rsi > 60 or (accel < -3 and momentum < 0):
                action = "SELL"
                entry_met = True
                reasons.append(f"Wildcard exit: score={total_score:.0f} RSI={rsi:.0f}")

    else:
        # MONK, HUNTER, AGGRESSIVE, DEFENSIVE — use global score (conservative)
        if total_score >= buy_t and available_cash > 0.5 and btc < 0.0001:
            action = "BUY"
            entry_met = True
            reasons.append(f"Score {total_score:.0f} >= {buy_t}")
        elif total_score <= sell_t and btc > 0:
            action = "SELL"
            entry_met = True
            reasons.append(f"Score {total_score:.0f} <= {sell_t}")

    # ══════════════════════════════════════════════════════════
    # BREAK-HOLD / PROBE ENTRY (only for experimental strategies still in HOLD)
    # ══════════════════════════════════════════════════════════
    probe_eligible = name in ("INTUITIVE", "EXPERIMENTAL", "SCALPER", "MEAN_REVERTER")
    if action == "HOLD" and probe_eligible and btc < 0.0001 and available_cash > 0.3:
        # Count improving signals
        improving = 0
        break_reasons = []
        if vol > 0.0001 and regime in ("WAKING_UP", "ACTIVE", "BREAKOUT"):
            improving += 1
            break_reasons.append("vol rising")
        if abs(ema_short - ema_long) / max(ema_long, 1) * 100 > 0.003:
            improving += 0.7
            break_reasons.append("EMA expanding")
        if accel > 1.5:
            improving += 0.7
            break_reasons.append(f"accel={accel:.1f}")
        if (rsi < 45 and momentum > 0) or (rsi > 55 and momentum < 0):
            improving += 0.7
            break_reasons.append(f"RSI={rsi:.0f} turning")
        if regime != "SLEEPING":
            improving += 0.5
            break_reasons.append(f"regime={regime}")

        # Early momentum trigger: price above EMA + accel improving + RSI >50
        if ema_short > ema_long and accel > 0.5 and 50 < rsi < 65:
            improving += 0.8
            break_reasons.append("early momentum")

        # Track consecutive improving cycles per strategy
        prev_score = s.get("_prev_score", total_score)
        if total_score > prev_score + 0.3:
            improving += 0.5
            break_reasons.append("score improving")
        s["_prev_score"] = total_score

        # First-move rule: regime just transitioned from SLEEPING
        prev_regime = s.get("_prev_regime", "SLEEPING")
        if prev_regime == "SLEEPING" and regime in ("WAKING_UP", "ACTIVE", "BREAKOUT"):
            if not s.get("_first_move_used", False):
                improving += 1.0
                break_reasons.append(f"first move: {prev_regime}→{regime}")
                s["_first_move_used"] = True
        if regime == "SLEEPING":
            s["_first_move_used"] = False  # reset when market goes back to sleep
        s["_prev_regime"] = regime

        # Safety: don't probe if recent regime performance is poor
        regime_safe = True
        try:
            import adaptive_learner
            rp = adaptive_learner._regime_performance.get(name, {}).get(regime, {})
            if rp.get("trades", 0) >= 3 and rp.get("wins", 0) / rp.get("trades", 1) < 0.25:
                regime_safe = False
        except Exception:
            pass

        # Limit: only 1 strategy can probe per cycle (prevent all triggering at once)
        cycle_key = _cycle_count

        # Probe entry: need 2.0+ improving signals + regime safe
        if improving >= 2.0 and regime_safe and confidence > 0.02 and _probe_this_cycle != cycle_key:
            action = "BUY"
            is_probe = True
            entry_met = True
            _probe_this_cycle = cycle_key  # mark: one probe per cycle
            reasons.append(f"Probe BUY: {' + '.join(break_reasons[:3])}")

    # ══════════════════════════════════════════════════════════
    # TREND PROBE — unified early trend detection module
    # Strict conditions: price>EMA, RSI 52-68, confirmed higher lows,
    # structure break, vol LOW+expanding, accel>=0.  3% probe only.
    # Only 1 trend_probe per direction per cycle.
    # ══════════════════════════════════════════════════════════
    if (action == "HOLD" and btc < 0.0001 and available_cash > 0.3
            and _probe_this_cycle != _cycle_count and not regime_blocked):
        # --- Conditions ---
        price_above_ema = ema_short > ema_long
        rsi_in_range = 52 <= rsi <= 68
        accel_ok = accel >= 0  # strict: must not be negative at all

        # Guard: skip if price extended far from EMA (>1.2% above)
        ema_dist_pct = (price - ema_long) / ema_long * 100 if ema_long > 0 else 0
        not_extended = 0 < ema_dist_pct < 1.2

        # Higher lows: compare local minimums of consecutive 2-candle windows
        ph = trader_state.get("price_history", [])
        recent = ph[-5:] if len(ph) >= 5 else ph
        higher_lows = False
        if len(recent) >= 4:
            # Compare mins of overlapping pairs: [0,1], [1,2], [2,3]
            pair_mins = [min(recent[i], recent[i + 1]) for i in range(len(recent) - 1)]
            higher_lows = all(pair_mins[i] >= pair_mins[i - 1] for i in range(1, len(pair_mins)))

        # Minor structure break: current price > highest of last 3-5 candles (excl. current)
        structure_break = False
        if len(ph) >= 4:
            lookback = ph[-5:-1] if len(ph) >= 5 else ph[:-1]
            structure_break = price > max(lookback)

        # Volatility: LOW but expanding (current vol > previous cycle's vol)
        vol_low_expanding = vol < 0.0015 and vol > _prev_volatility and _prev_volatility > 0

        # Guard: don't stack if already trend_probed this direction in this regime
        already_probed = s.get("_trend_probe_regime", "") == regime

        # --- All conditions must pass ---
        tp_pass = (price_above_ema and rsi_in_range and higher_lows
                   and structure_break and vol_low_expanding
                   and accel_ok and not_extended and not already_probed)

        if tp_pass:
            action = "BUY"
            is_probe = True
            entry_met = True
            _probe_this_cycle = _cycle_count
            s["_trend_probe_regime"] = regime
            reasons.append(
                f"trend_probe: EMA+, RSI={rsi:.0f}, higher lows confirmed, "
                f"structure break, vol={vol:.5f} expanding, accel={accel:.1f}"
            )
            print(f"[trend_probe] TRIGGERED for {name}: "
                  f"price={price:.0f} EMA_dist={ema_dist_pct:.2f}% RSI={rsi:.0f} "
                  f"accel={accel:.1f} vol={vol:.5f} prev_vol={_prev_volatility:.5f} "
                  f"regime={regime} | higher_lows=True structure_break=True")

    # Reset trend_probe stacking guard on regime change or clear breakout
    prev_regime_tp = s.get("_prev_regime_tp", regime)
    if prev_regime_tp != regime:
        s["_trend_probe_regime"] = ""  # allow new trend_probe after regime shift
    s["_prev_regime_tp"] = regime

    # ══════════════════════════════════════════════════════════
    # ANTI-PARALYSIS FALLBACK — exploratory trend_probe after long idle
    # If no strategy has traded for 60+ cycles (~30 min) and conditions
    # are constructive, allow ONE exploratory 3% probe to avoid total freeze.
    # ══════════════════════════════════════════════════════════
    idle_cycles = _cycle_count - _last_any_trade_cycle
    if (action == "HOLD" and btc < 0.0001 and available_cash > 0.3
            and _probe_this_cycle != _cycle_count and not regime_blocked
            and idle_cycles >= 60):
        # Relaxed but still valid conditions
        ap_price_above = ema_short > ema_long
        ap_rsi_ok = 55 <= rsi <= 68
        ap_vol_low = vol < 0.002
        ap_accel_ok = accel >= 0
        ap_ema_dist = (price - ema_long) / ema_long * 100 if ema_long > 0 else 0
        ap_not_extended = 0 < ap_ema_dist < 1.5
        # Don't stack: only 1 anti-paralysis probe per strategy per idle window
        ap_already = s.get("_anti_paralysis_cycle", 0) > _last_any_trade_cycle

        if (ap_price_above and ap_rsi_ok and ap_vol_low
                and ap_accel_ok and ap_not_extended and not ap_already):
            action = "BUY"
            is_probe = True
            entry_met = True
            _probe_this_cycle = _cycle_count
            s["_anti_paralysis_cycle"] = _cycle_count
            reasons.append(
                f"trend_probe (exploratory): {idle_cycles} idle cycles, "
                f"EMA+, RSI={rsi:.0f}, vol low, accel={accel:.1f}"
            )
            print(f"[trend_probe] ANTI-PARALYSIS for {name}: "
                  f"idle={idle_cycles} cycles, price={price:.0f} RSI={rsi:.0f} "
                  f"accel={accel:.1f} vol={vol:.5f} regime={regime}")

    # ══════════════════════════════════════════════════════════
    # SLEEPING REGIME PROBE — price breaks local high + accel + RSI confirm
    # Allows ANY strategy to probe in SLEEPING if price breaks recent high
    # ══════════════════════════════════════════════════════════
    if (action == "HOLD" and regime == "SLEEPING" and btc < 0.0001
            and available_cash > 0.3 and _probe_this_cycle != _cycle_count):
        ph = trader_state.get("price_history", [])
        window = ph[-20:] if len(ph) >= 20 else ph
        if len(window) >= 5:
            local_high = max(window[:-1])
            current_price = window[-1]
            if current_price > local_high and accel > 0 and rsi > 55:
                action = "BUY"
                is_probe = True
                entry_met = True
                _probe_this_cycle = _cycle_count
                reasons.append(
                    f"SLEEPING probe: price {current_price:.0f} > local high {local_high:.0f}, "
                    f"accel={accel:.1f}, RSI={rsi:.0f}"
                )

    # Log why NOT trading (for debugging)
    if action == "HOLD" and not entry_met:
        hold_reason = []
        if btc > 0:
            hold_reason.append("holding position")
        else:
            hold_reason.append(f"score={total_score:.0f}")
            hold_reason.append(f"RSI={rsi:.0f}")
            hold_reason.append(f"accel={accel:.1f}")
        reasons.append("No entry: " + ", ".join(hold_reason))

    # Confidence filter — only for conservative strategies (probes bypass this)
    if action != "HOLD" and not is_probe and name in ("MONK", "DEFENSIVE") and confidence < profile["min_confidence"]:
        action = "HOLD"
        reasons.append(f"Low confidence ({confidence:.0%})")

    # Store entry condition status
    s["entry_condition_met"] = entry_met

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

    # Anti flip-flop
    if action != "HOLD" and s["last_action"] != "HOLD" and action != s["last_action"] and since < profile["cooldown"] * 1.5:
        action = "HOLD"
        reasons.append("Anti flip-flop")

    # ── Execute against GLOBAL portfolio ──
    pnl = 0.0
    if action == "BUY":
        # Probe entries use smaller position (trend_probe=3%, other probes=5%)
        last_reason = reasons[-1] if reasons else ""
        if is_probe and ("trend_probe" in last_reason or "exploratory" in last_reason):
            pos_pct = 0.03
        elif is_probe:
            pos_pct = 0.05
        else:
            pos_pct = profile["position_pct"]
        spend = available_cash * pos_pct
        spend = min(spend, _portfolio["total_cash"] * 0.3)  # cap at 30% of total cash per trade
        spend = min(spend, _portfolio["total_cash"] - 1.0)  # keep $1 reserve
        if spend < 0.1:
            action = "HOLD"
            reasons.append("Insufficient allocated capital")
        else:
            qty = spend / price
            _portfolio["total_cash"] -= spend
            s["btc_holdings"] += qty
            s["entry_price"] = price
            s["cash_used"] = spend
            s["total_trades"] += 1
            s["last_trade_time"] = time.time()
            s["trades_this_minute"] += 1
            reasons.append(f"Bought {qty:.6f} BTC (${spend:.2f}) @ ${price:,.2f}")

    elif action == "SELL" and btc > 0:
        revenue = btc * price
        pnl = (price - s["entry_price"]) * btc
        _portfolio["total_cash"] += revenue
        s["btc_holdings"] = 0.0
        s["cash_used"] = 0.0
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

    # Virtual equity tracking for drawdown
    v_eq = _get_strategy_virtual_equity(name, price)
    if v_eq > s["peak_virtual_equity"]:
        s["peak_virtual_equity"] = v_eq
    dd = (s["peak_virtual_equity"] - v_eq) / s["peak_virtual_equity"] * 100 if s["peak_virtual_equity"] > 0 else 0
    if dd > s["max_drawdown"]:
        s["max_drawdown"] = dd

    s["last_action"] = action
    s["last_reason"] = ". ".join(reasons[:3]) if reasons else "Neutral"

    # Record trade result for adaptive learner
    if action == "SELL" and pnl != 0:
        try:
            import adaptive_learner
            result = "win" if pnl > 0 else ("loss" if pnl < 0 else "flat")
            regime = mkt.get("state", "SLEEPING") if isinstance(mkt, dict) else str(mkt)
            adaptive_learner.record_trade_result(name, regime, result, pnl)
        except Exception:
            pass

    # Determine entry type label
    if is_probe:
        probe_reasons = " ".join(reasons)
        if "trend_probe" in probe_reasons or "exploratory" in probe_reasons:
            entry_type = "trend_probe"
        elif "SLEEPING probe" in probe_reasons:
            entry_type = "sleeping_probe"
        else:
            entry_type = "probe"
    else:
        entry_type = "full"

    # Trade log with full context + export to _cycle_trades for dashboard sync
    if action != "HOLD":
        _last_any_trade_cycle = _cycle_count  # anti-paralysis tracker

        trade_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action, "price": round(price, 2),
            "pnl": round(pnl, 6), "score": total_score,
            "confidence": confidence, "market_state": mkt,
            "strategy": name,
            "entry_type": entry_type,
            "hold_zone_adj": hold_zone_adj,
            "indicators": {
                "rsi": round(indicators.get("rsi", 0), 1),
                "trend": indicators.get("trend", "unknown"),
                "volatility": round(indicators.get("volatility", 0), 5),
            },
            "reasons": reasons,
        }
        s["trade_history"].append(trade_record)
        if len(s["trade_history"]) > 100:
            s["trade_history"] = s["trade_history"][-100:]

        # Export for split-brain fix: dashboard/auto_trader can read this
        _cycle_trades.append(trade_record)

    return {"action": action, "pnl": pnl}


# ---------------------------------------------------------------------------
# Main Cycle
# ---------------------------------------------------------------------------

def run_multi_cycle(price: float = 0, indicators: dict = None) -> dict:
    global _cycle_count, _last_market_state, _leaderboard, _prev_volatility, _cycle_trades

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

    # Clear cycle trades before running strategies
    _cycle_trades = []

    # Run all strategies
    for name in PROFILES:
        _run_strategy(name, indicators, mkt, price)

    # Update prev_volatility AFTER strategies run (so next cycle sees this cycle's vol)
    _prev_volatility = indicators.get("volatility", 0)

    _cycle_count += 1

    # Periodic capital reallocation
    if _cycle_count - _last_realloc_cycle >= REALLOC_INTERVAL:
        _reallocate_capital(price)

    # Adaptive learning pass
    try:
        import adaptive_learner
        learn_result = adaptive_learner.run_learning_pass(
            _strategies, _allocations, {n: PROFILES[n] for n in PROFILES}, mkt.get("state", "SLEEPING")
        )
        if not learn_result.get("skipped"):
            # Apply allocation adjustments
            for name, delta in learn_result.get("allocation_adjustments", {}).items():
                if name in _allocations:
                    _allocations[name] = max(0.05, min(0.30, _allocations[name] + delta))
            # Apply threshold adjustments
            for name, adjs in learn_result.get("threshold_adjustments", {}).items():
                if name in PROFILES:
                    for field, delta in adjs.items():
                        if field in PROFILES[name]:
                            PROFILES[name][field] += delta
    except Exception:
        pass

    # Auto-switch + kill/revive
    _check_auto_switch(price)
    _check_kill_revive(price)

    # Mark primary as LEADING (skip paused/killed)
    for name, s in _strategies.items():
        if s["status"] in ("ACTIVE", "LEADING"):
            s["status"] = "LEADING" if name == _primary_strategy else "ACTIVE"

    _leaderboard = _compute_leaderboard(price)

    return {
        "cycle": _cycle_count, "price": price, "market_state": mkt,
        "leaderboard": _leaderboard, "cycle_trades": list(_cycle_trades),
    }


def get_cycle_trades() -> list[dict]:
    """Return trades executed in the most recent cycle (for dashboard sync)."""
    return list(_cycle_trades)


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
            "equity": round(p["virtual_equity"], 4),
            "allocated_capital": round(p["allocated_capital"], 2),
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
            "entry_condition_met": s.get("entry_condition_met", False),
            "regimes": PROFILES[name].get("regimes", []),
        })
    board.sort(key=lambda x: x["total_return"], reverse=True)
    for i, entry in enumerate(board):
        entry["rank"] = i + 1
    return board


def get_next_move_prediction() -> dict:
    """Predict what the system is most likely to do next based on current state.
    Aggregates signals across active strategies weighted by allocation."""
    _ensure_initialized()

    buy_weight = 0
    sell_weight = 0
    hold_weight = 0
    reasons = []
    mkt = _last_market_state.get("state", "SLEEPING")

    for name, s in _strategies.items():
        if s["status"] not in ("ACTIVE", "LEADING"):
            continue
        alloc = _allocations.get(name, 0)
        action = s["last_action"]
        entry_met = s.get("entry_condition_met", False)

        if action == "BUY" or (entry_met and s["btc_holdings"] < 0.0001):
            buy_weight += alloc
        elif action == "SELL" or (entry_met and s["btc_holdings"] > 0.0001):
            sell_weight += alloc
        else:
            hold_weight += alloc

    total = buy_weight + sell_weight + hold_weight
    if total <= 0:
        return {"action": "HOLD", "probability": 75, "reason": "No active strategies"}

    buy_pct = buy_weight / total * 100
    sell_pct = sell_weight / total * 100
    hold_pct = hold_weight / total * 100

    # ── Inject signal-based lean so HOLD never hits 100% ──
    # Even when all strategies say HOLD, market indicators create a slight lean
    indicators = compute_indicators(trader_state.get("price_history", []))
    rsi = indicators.get("rsi", 50)
    slope = indicators.get("slope", 0)
    accel = indicators.get("acceleration", 0)

    # Signal lean: slight buy/sell bias based on indicators (max ±15%)
    signal_lean = 0
    if rsi < 40: signal_lean += 5
    elif rsi > 60: signal_lean -= 5
    if slope > 0: signal_lean += 3
    elif slope < 0: signal_lean -= 3
    if accel > 3: signal_lean += 4
    elif accel < -3: signal_lean -= 4
    # Regime boost
    if mkt in ("WAKING_UP", "ACTIVE"): signal_lean += 3
    elif mkt == "BREAKOUT": signal_lean += 5

    # Trend probe bias: if a trend_probe fired recently, boost buy signal
    if _cycle_trades:
        for ct in _cycle_trades:
            if ct.get("entry_type") in ("trend_probe",) and ct.get("action") == "BUY":
                signal_lean += 8  # +8 bias for active trend_probe
                reasons.append("trend_probe active — partial BUY bias")
                break

    if signal_lean > 0:
        buy_pct += min(signal_lean, 15)
        hold_pct -= min(signal_lean, 15)
    elif signal_lean < 0:
        sell_pct += min(abs(signal_lean), 15)
        hold_pct -= min(abs(signal_lean), 15)

    # Cap HOLD at 85% — never show 100%
    if hold_pct > 85:
        excess = hold_pct - 85
        hold_pct = 85
        # Distribute excess proportionally or to the leaning side
        if signal_lean > 0:
            buy_pct += excess
        elif signal_lean < 0:
            sell_pct += excess
        else:
            buy_pct += excess * 0.5
            sell_pct += excess * 0.5

    buy_pct = round(max(0, min(100, buy_pct)))
    sell_pct = round(max(0, min(100, sell_pct)))
    hold_pct = round(max(0, min(100, hold_pct)))

    # Normalize to 100%
    norm = buy_pct + sell_pct + hold_pct
    if norm > 0 and norm != 100:
        buy_pct = round(buy_pct / norm * 100)
        sell_pct = round(sell_pct / norm * 100)
        hold_pct = 100 - buy_pct - sell_pct

    if buy_pct >= sell_pct and buy_pct >= hold_pct:
        action, prob = "BUY", buy_pct
    elif sell_pct >= buy_pct and sell_pct >= hold_pct:
        action, prob = "SELL", sell_pct
    else:
        action, prob = "HOLD", hold_pct

    # Build reason from market state
    if mkt == "SLEEPING":
        reasons.append("low volatility, no confirmed edge")
    elif mkt == "WAKING_UP":
        reasons.append("volatility rising, watching for confirmation")
    elif mkt == "ACTIVE":
        reasons.append("strong signals, directional move underway")
    elif mkt == "BREAKOUT":
        reasons.append("volatility spike, breakout in progress")

    if action == "HOLD" and hold_pct > 70:
        reasons.append("strategies aligned on caution")
    elif action == "BUY" and buy_pct > 60:
        reasons.append("multiple strategies leaning bullish")
    elif action == "SELL" and sell_pct > 60:
        reasons.append("multiple strategies leaning bearish")

    return {
        "action": action,
        "probability": prob,
        "reason": " — ".join(reasons) if reasons else "mixed signals",
        "breakdown": {"buy": buy_pct, "sell": sell_pct, "hold": hold_pct},
    }


def get_revival_watch() -> list:
    """Return killed strategies and what condition they're waiting for to revive."""
    _ensure_initialized()
    watch = []
    mkt = _last_market_state.get("state", "SLEEPING")

    for name, s in _strategies.items():
        if s["status"] != "INACTIVE":
            continue

        cycles_since = _cycle_count - s.get("killed_at_cycle", 0)
        profile = PROFILES.get(name, {})
        regimes = profile.get("regimes", [])
        cooldown_left = max(0, REVIVE_COOLDOWN - cycles_since)

        # Determine what this strategy is waiting for
        triggers = []
        if cooldown_left > 0:
            triggers.append(f"cooldown: {cooldown_left} cycles remaining")
        if regimes and mkt not in regimes:
            needed = [r for r in regimes if r != mkt]
            triggers.append(f"waiting for {' or '.join(needed[:2])} regime")
        if name in ("BREAKOUT_SNIPER", "AGGRESSIVE"):
            triggers.append("waiting for volatility expansion")
        elif name in ("MEAN_REVERTER", "MONK", "DEFENSIVE"):
            triggers.append("waiting for calm/sideways market")
        elif name in ("SCALPER", "INTUITIVE"):
            triggers.append("waiting for signal clarity")

        watch.append({
            "strategy": name,
            "label": profile.get("label", name),
            "color": profile.get("color", "#666"),
            "cycles_inactive": cycles_since,
            "triggers": triggers[:2],  # max 2 reasons
        })

    return watch


def get_event_log() -> list:
    """Return full event log (newest first)."""
    _ensure_initialized()
    return _event_log[::-1]


def get_leaderboard() -> dict:
    _ensure_initialized()
    price = trader_state.get("last_price", 0)
    global_eq = _get_global_equity(price) if price > 0 else INITIAL_BALANCE
    return {
        "cycle": _cycle_count,
        "primary_strategy": _primary_strategy,
        "leaderboard": _leaderboard,
        "market_state": _last_market_state,
        "global_portfolio": {
            "total_equity": round(global_eq, 4),
            "cash": round(_portfolio["total_cash"], 4),
            "btc_in_positions": round(sum(s["btc_holdings"] for s in _strategies.values()), 8),
        },
        "allocations": {n: round(v * 100, 1) for n, v in _allocations.items()},
        "event_log": _event_log[-30:][::-1],
        "strategies": {
            name: {
                "profile": {k: v for k, v in PROFILES[name].items() if k not in ("color",)},
                "status": s["status"],
                "equity": round(_get_strategy_virtual_equity(name, max(price, 1)), 4),
                "allocated_capital": round(INITIAL_BALANCE * _allocations.get(name, 0), 2),
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
