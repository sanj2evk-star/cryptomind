"""
api.py - FastAPI REST interface for the multi-user paper trading system.

Endpoints:
    POST /register     → create new user account
    POST /login        → authenticate and get JWT token
    GET  /status       → current portfolio (user-scoped)
    GET  /trades       → recent trades (user-scoped)
    GET  /decision     → last trading decision (user-scoped)
    GET  /performance  → today's metrics (user-scoped)
    GET  /equity       → equity curve data (user-scoped)
    GET  /strategies   → saved strategies (user-scoped)

All data endpoints return data isolated to the authenticated user.

Run with:
    uvicorn app.api:app --reload --port 8000
"""

from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path
from datetime import date, datetime, timezone

from fastapi import FastAPI, Query, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

# Ensure app/ is importable
APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from config import DATA_DIR, SYMBOLS, INITIAL_BALANCE
from auth import authenticate, require_auth, get_user_id
from user_manager import create_user, get_user_file, ensure_admin
from data_fetcher import fetch_current_price
from seed_data import seed_user
import auto_trader

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="CryptoMind API",
    description="v7 — Memory + Reflection + Self-Evolving Core + Mind Evolution",
    version="7.3.0",
)

# CORS: allow the frontend origin. Extra origins can be added via CORS_ORIGINS env var.
_extra_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
_allowed_origins = list(set([
    "http://localhost:3000",
    "http://localhost:3700",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3700",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
] + _extra_origins))

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type", "*"],
)


@app.get("/health")
def health():
    """Health check — no auth required. Used by Render health checks and frontend."""
    trader_state = auto_trader.get_state()
    return {
        "status": "ok",
        "trader_running": trader_state.get("running", False),
        "cycles": trader_state.get("cycle_count", 0),
        "last_price": trader_state.get("last_price", 0),
    }


@app.on_event("startup")
def startup():
    """Boot CryptoMind v7 — persistence, sessions, trading.

    1. Initialize v7 persistence layer (DB, sessions, migration)
    2. Ensure admin user exists
    3. Start autonomous trading loop
    """
    from datetime import datetime, timezone
    boot_time = datetime.now(timezone.utc).isoformat()
    print(f"[api] ===== CryptoMind v7 starting at {boot_time} =====")

    # v7: Initialize persistence layer FIRST
    try:
        import session_manager
        v7_result = session_manager.initialize()
        print(f"[api] v7 session: {v7_result.get('action', '?')} "
              f"(session #{v7_result.get('session_id', '?')})")
        if v7_result.get("migrated_trades"):
            print(f"[api] Migrated {v7_result['migrated_trades']} historical trades to SQLite")
    except Exception as e:
        print(f"[api] v7 init error (non-fatal): {e}")

    ensure_admin()
    result = seed_user("admin")
    if result.get("seeded"):
        print(f"[api] Seeded admin with demo data: {result['trades']} trades, {result['equity_points']} equity points")
    else:
        print(f"[api] Admin data already exists — resuming")

    # Auto-start the trading loop (safe to call after sleep — restarts cleanly)
    auto_result = auto_trader.start("admin")
    print(f"[api] Auto-trader: {auto_result['status']} (every {auto_result.get('interval', 30)}s)")
    print(f"[api] CryptoMind v7 ready. Memory + Reflection active.")


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str


@app.post("/register", status_code=201)
def register(req: RegisterRequest):
    """Create a new user account with an isolated portfolio."""
    if len(req.username.strip()) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters.")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")

    ok = create_user(req.username, req.password, req.display_name)
    if not ok:
        raise HTTPException(status_code=409, detail="Username already exists.")

    return {"message": f"User '{req.username}' created.", "user_id": req.username.strip().lower()}


@app.post("/login", response_model=LoginResponse)
def login(req: LoginRequest):
    """Authenticate and receive a JWT access token."""
    token = authenticate(req.username, req.password)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    return LoginResponse(access_token=token, user_id=req.username.strip().lower())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_user_csv(user_id: str, filename: str, limit: int = 0) -> list[dict]:
    """Load a CSV from a user's data directory.

    Args:
        user_id: Authenticated user.
        filename: CSV file name.
        limit: Max rows (0 = all), taken from end.

    Returns:
        List of row dicts.
    """
    path = get_user_file(user_id, filename)
    if not path.exists():
        return []
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    if limit > 0:
        rows = rows[-limit:]
    return rows


def _load_user_json(user_id: str, filename: str, default=None):
    """Load a JSON file from a user's data directory.

    Args:
        user_id: Authenticated user.
        filename: JSON file name.
        default: Default value if file missing.

    Returns:
        Parsed JSON data.
    """
    path = get_user_file(user_id, filename)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default if default is not None else {}


def _safe_float(val, default: float = 0.0) -> float:
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Protected endpoints (user-scoped)
# ---------------------------------------------------------------------------

@app.get("/status")
def get_status(user_id: str = Depends(get_user_id)):
    """Current portfolio state with live prices for the authenticated user."""
    portfolio = _load_user_json(user_id, "portfolio.json", {
        "cash": INITIAL_BALANCE, "positions": {}, "realized_pnl": 0.0,
    })

    prices = {}
    for symbol, pos in portfolio.get("positions", {}).items():
        if pos.get("position_open"):
            try:
                prices[symbol] = fetch_current_price(symbol)
            except Exception:
                prices[symbol] = pos.get("entry_price", 0.0)

    unrealized = sum(
        (prices.get(s, p["entry_price"]) - p["entry_price"]) * p["position_size"]
        for s, p in portfolio.get("positions", {}).items()
        if p.get("position_open")
    )
    pos_value = sum(
        p["position_size"] * prices.get(s, p["entry_price"])
        for s, p in portfolio.get("positions", {}).items()
        if p.get("position_open")
    )
    total_equity = portfolio.get("cash", 0) + pos_value

    open_positions = {
        symbol: {
            "size": pos["position_size"],
            "entry_price": pos["entry_price"],
            "current_price": prices.get(symbol, 0.0),
            "unrealized_pnl": round(
                (prices.get(symbol, pos["entry_price"]) - pos["entry_price"]) * pos["position_size"], 4
            ),
        }
        for symbol, pos in portfolio.get("positions", {}).items()
        if pos.get("position_open")
    }

    return {
        "user_id": user_id,
        "cash": round(portfolio.get("cash", 0), 4),
        "total_equity": round(total_equity, 4),
        "realized_pnl": round(portfolio.get("realized_pnl", 0), 4),
        "unrealized_pnl": round(unrealized, 4),
        "total_trades": portfolio.get("total_trades", 0),
        "trades_today": portfolio.get("trades_today", 0),
        "open_positions": open_positions,
        "consecutive_losses": portfolio.get("consecutive_losses", 0),
        "circuit_breaker_until": portfolio.get("circuit_breaker_until", ""),
        "peak_equity": portfolio.get("peak_equity", INITIAL_BALANCE),
    }


@app.get("/trades")
def get_trades(limit: int = Query(default=20, ge=1, le=100), user_id: str = Depends(get_user_id)):
    """Recent trades for the authenticated user, most recent first."""
    rows = _load_user_csv(user_id, "trades.csv", limit=limit)
    rows.reverse()
    return {"user_id": user_id, "count": len(rows), "trades": rows}


@app.get("/decision")
def get_last_decision(user_id: str = Depends(get_user_id)):
    """Last trading decision for the authenticated user."""
    rows = _load_user_csv(user_id, "decisions.csv", limit=1)
    if not rows:
        return {"user_id": user_id, "decision": None}
    return {"user_id": user_id, "decision": rows[0]}


@app.get("/performance")
def get_performance(user_id: str = Depends(get_user_id)):
    """Today's performance metrics for the authenticated user."""
    all_trades = _load_user_csv(user_id, "trades.csv")
    today = date.today().isoformat()
    trades = [t for t in all_trades if t.get("timestamp", "").startswith(today)]

    executed = [t for t in trades if t.get("action") in ("BUY", "SELL")]
    pnl_values = [_safe_float(t.get("pnl")) for t in executed]

    total = len(executed)
    wins = sum(1 for p in pnl_values if p > 0)
    losses = sum(1 for p in pnl_values if p < 0)
    total_pnl = sum(pnl_values)
    win_rate = (wins / total * 100) if total > 0 else 0.0

    peak = cum = max_dd = 0.0
    for p in pnl_values:
        cum += p
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd

    return {
        "user_id": user_id,
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 2),
        "total_pnl": round(total_pnl, 4),
        "max_drawdown": round(max_dd, 4),
    }


@app.get("/equity")
def get_equity(limit: int = Query(default=100, ge=1, le=1000), user_id: str = Depends(get_user_id)):
    """Equity curve data for the authenticated user."""
    rows = _load_user_csv(user_id, "equity.csv", limit=limit)
    return {"user_id": user_id, "count": len(rows), "equity": rows}


@app.get("/strategies")
def get_strategies(user_id: str = Depends(get_user_id)):
    """Saved strategies for the authenticated user."""
    strategies = _load_user_json(user_id, "strategies.json", [])
    summaries = []
    for s in strategies:
        summaries.append({
            "name": s.get("name", "?"),
            "parameters": s.get("parameters", {}),
            "fitness": s.get("fitness", 0),
            "live_score": s.get("live_score", 0),
            "metrics": s.get("metrics", {}),
        })
    return {"user_id": user_id, "count": len(summaries), "strategies": summaries}


@app.post("/seed")
def seed_demo_data(user_id: str = Depends(get_user_id)):
    """Populate the user's account with demo data.

    Only works if the user has no existing trades.
    """
    result = seed_user(user_id)
    if not result.get("seeded"):
        raise HTTPException(status_code=409, detail=result.get("reason", "Already seeded."))
    return {"user_id": user_id, **result}


# ---------------------------------------------------------------------------
# Auto-trader endpoints
# ---------------------------------------------------------------------------

@app.get("/ping")
def ping():
    """Lightweight keep-alive endpoint. No auth, minimal payload."""
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()[:19]}


@app.get("/live")
def get_live_state():
    """Get the autonomous trader's current state. No auth required."""
    return auto_trader.get_state()


@app.get("/ai-performance")
def get_ai_performance():
    """AI confidence vs reality metrics. No auth required."""
    try:
        import confidence_tracker
        return {
            "metrics": confidence_tracker.get_metrics(),
            "recent": confidence_tracker.get_recent_evaluated(limit=10),
        }
    except Exception as e:
        return {"metrics": {}, "recent": [], "error": str(e)}


@app.get("/price-history")
def get_price_history():
    """Return raw price history from auto-trader memory. No auth, ultra-lightweight."""
    import time as _time
    prices = auto_trader._state.get("price_history", [])
    now = int(_time.time())
    # Build simple time-value pairs (30s interval between readings)
    points = []
    for i, p in enumerate(prices):
        t = now - (len(prices) - i) * 30
        points.append({"time": t, "value": round(p, 2)})
    return {"count": len(points), "prices": points}


@app.get("/journal")
def get_public_journal(limit: int = Query(default=20, ge=1, le=100)):
    """Public journal endpoint — latest N entries, newest first. No auth required."""
    entries = auto_trader.get_journal("admin", limit=limit)
    return {"count": len(entries), "entries": entries}


@app.get("/prediction")
def get_prediction():
    """Next move prediction."""
    try:
        import multi_strategy
        return multi_strategy.get_next_move_prediction()
    except Exception as e:
        return {"action": "HOLD", "probability": 0, "reason": str(e)}


@app.get("/debug/state")
def debug_state():
    """Real-time debug snapshot of the trading engine internals."""
    state = auto_trader._state
    indicators = state.get("indicators", {})
    last_dec = state.get("last_decision") or {}
    portfolio = auto_trader.load_auto_portfolio("admin")
    mkt = state.get("market_state", {})

    # Multi-strategy state
    try:
        import multi_strategy
        ms_trades = multi_strategy.get_cycle_trades()
        ms_idle = multi_strategy._cycle_count - multi_strategy._last_any_trade_cycle
        ms_prev_vol = multi_strategy._prev_volatility
        ms_exposure = multi_strategy._current_exposure_pct
        ms_exposure_cap = multi_strategy._exposure_cap_active
        ms_blocked = multi_strategy._blocked_trade_reason
        ms_quality = multi_strategy._market_quality_score
        ms_perf = dict(multi_strategy._strategy_performance)
        ms_reentry = {
            "consecutive_buys": multi_strategy._consecutive_buys,
            "last_sell_cycle": multi_strategy._last_sell_cycle,
            "last_buy_cycle": multi_strategy._last_buy_cycle,
            "last_committed_score": multi_strategy._last_committed_score,
            "last_committed_regime": multi_strategy._last_committed_regime,
        }
        ms_probe_count = multi_strategy._probe_trades_count
        ms_hold_cycles = multi_strategy._consecutive_hold_cycles
        ms_strategy_status = {
            n: s["status"] for n, s in multi_strategy._strategies.items()
        } if multi_strategy._strategies else {}
        # Count blocked reasons
        reason_freq = {}
        for r in multi_strategy._blocked_reason_log[-50:]:
            reason_freq[r] = reason_freq.get(r, 0) + 1
        ms_blocked_freq = reason_freq
    except Exception:
        ms_trades, ms_idle, ms_prev_vol = [], 0, 0
        ms_exposure, ms_exposure_cap, ms_blocked, ms_quality = 0, "", "", 0
        ms_perf, ms_reentry = {}, {}
        ms_probe_count, ms_hold_cycles = 0, 0
        ms_strategy_status, ms_blocked_freq = {}, {}

    return {
        "price": state.get("last_price", 0),
        "rsi": indicators.get("rsi", 0),
        "ema": {
            "short": indicators.get("ema_short", 0),
            "long": indicators.get("ema_long", 0),
        },
        "accel": indicators.get("acceleration", 0),
        "regime": mkt.get("state", "SLEEPING"),
        "regime_score": mkt.get("confidence_score", 0),
        "decision": {
            "action": last_dec.get("action", "HOLD"),
            "score": last_dec.get("score", 0),
            "confidence": last_dec.get("confidence", 0),
            "reasoning": last_dec.get("reasoning", ""),
        },
        "last_trade": {
            "time": state.get("last_update", ""),
            "cycle": state.get("cycle_count", 0),
        },
        "positions": {
            "cash": portfolio.get("cash", 0),
            "btc_holdings": portfolio.get("btc_holdings", 0),
            "avg_entry_price": portfolio.get("avg_entry_price", 0),
            "total_trades": portfolio.get("total_trades", 0),
            "realized_pnl": portfolio.get("realized_pnl", 0),
        },
        "indicators_full": indicators,
        "multi_strategy": {
            "cycle_trades": ms_trades,
            "idle_cycles": ms_idle,
            "prev_volatility": ms_prev_vol,
        },
        "proposed_trades_this_cycle": state.get("proposed_trades", []),
        "committed_trade_this_cycle": state.get("committed_trade"),
        "portfolio_after_trade": {
            "cash": portfolio.get("cash", 0),
            "btc_holdings": portfolio.get("btc_holdings", 0),
            "total_trades": portfolio.get("total_trades", 0),
        },
        # ── NEW: Portfolio Brain & Calibration Debug ──
        "total_exposure_pct": round(ms_exposure, 2),
        "exposure_cap_active": ms_exposure_cap,
        "blocked_trade_reason": ms_blocked,
        "market_quality_score": ms_quality,
        "strategy_performance_summary": ms_perf,
        "reentry_state": ms_reentry,
        # ── v5.1: Probe & Hold Loop Debug ──
        "probe_trades_count": ms_probe_count,
        "consecutive_hold_cycles": ms_hold_cycles,
        "strategy_status": ms_strategy_status,
        "last_blocked_reason_frequency": ms_blocked_freq,
    }


@app.get("/revival-watch")
def get_revival_watch():
    """Killed strategies under revival watch."""
    try:
        import multi_strategy
        return {"watch": multi_strategy.get_revival_watch()}
    except Exception as e:
        return {"watch": [], "error": str(e)}


@app.get("/adaptive")
def get_adaptive_status():
    """Adaptive learning system status."""
    try:
        import adaptive_learner
        return adaptive_learner.get_status()
    except Exception as e:
        return {"enabled": False, "error": str(e)}


@app.post("/adaptive/toggle")
def toggle_adaptive(enabled: bool = True):
    """Enable or disable adaptive learning."""
    try:
        import adaptive_learner
        adaptive_learner.set_enabled(enabled)
        return {"enabled": enabled}
    except Exception as e:
        return {"error": str(e)}


@app.post("/adaptive/reset")
def reset_adaptive():
    """Reset all adaptive learning state."""
    try:
        import adaptive_learner
        adaptive_learner.reset_all()
        return {"status": "reset"}
    except Exception as e:
        return {"error": str(e)}


@app.get("/leaderboard")
def get_leaderboard():
    """Multi-strategy leaderboard. No auth required."""
    try:
        import multi_strategy
        return multi_strategy.get_leaderboard()
    except Exception as e:
        return {"error": str(e), "leaderboard": [], "strategies": {}}


@app.get("/candles")
def get_candles(interval: str = Query(default="5m")):
    """BTC/USDT candle data for charting. No auth required."""
    valid = ("1m", "5m", "15m", "1h", "6h", "12h", "1d", "1w", "1M", "3M", "6M")
    if interval not in valid:
        interval = "5m"
    try:
        import candle_fetcher
        return candle_fetcher.fetch_candles(interval=interval, with_ema=True)
    except Exception as e:
        return {"candles": [], "ema9": [], "ema21": [], "source": "error", "interval": interval, "count": 0, "error": str(e)}


@app.post("/strategy/{name}/pause")
def pause_strategy(name: str):
    """Pause a strategy — stops trading, keeps observing."""
    try:
        import multi_strategy
        return multi_strategy.pause_strategy(name.upper())
    except Exception as e:
        return {"error": str(e)}


@app.post("/strategy/{name}/resume")
def resume_strategy(name: str):
    """Resume a paused or killed strategy."""
    try:
        import multi_strategy
        return multi_strategy.resume_strategy(name.upper())
    except Exception as e:
        return {"error": str(e)}


@app.post("/strategy/{name}/kill")
def kill_strategy(name: str):
    """Kill a strategy completely."""
    try:
        import multi_strategy
        return multi_strategy.kill_strategy(name.upper())
    except Exception as e:
        return {"error": str(e)}


@app.get("/strategy-events")
def get_strategy_events(limit: int = Query(default=50, ge=1, le=200)):
    """Strategy engine events (switches, kills, revivals, reallocations)."""
    try:
        import multi_strategy
        events = multi_strategy.get_event_log()
        return {"count": len(events[-limit:]), "events": events[-limit:]}
    except Exception as e:
        return {"count": 0, "events": [], "error": str(e)}


@app.get("/strategy-allocations")
def get_strategy_allocations():
    """Current capital allocation per strategy."""
    try:
        import multi_strategy
        lb = multi_strategy.get_leaderboard()
        allocations = {
            name: {
                "allocation_pct": s.get("allocation_pct", 20),
                "equity": s.get("equity", 100),
                "status": s.get("status", "ACTIVE"),
            }
            for name, s in lb.get("strategies", {}).items()
        }
        return {"allocations": allocations, "total_strategies": len(allocations)}
    except Exception as e:
        return {"allocations": {}, "error": str(e)}


@app.get("/insight")
def get_session_insight():
    """Current session insight — trader-style summary. No auth required."""
    return auto_trader.get_session_insight()


@app.post("/auto/start")
def start_auto_trader(user_id: str = Depends(get_user_id)):
    """Start the autonomous trading loop."""
    return auto_trader.start(user_id)


@app.post("/auto/stop")
def stop_auto_trader(user_id: str = Depends(get_user_id)):
    """Stop the autonomous trading loop."""
    return auto_trader.stop()


@app.get("/auto/trades")
def get_auto_trades(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    action: str = Query(default=""),
    strategy: str = Query(default=""),
    regime: str = Query(default=""),
    entry_type: str = Query(default=""),
    user_id: str = Depends(get_user_id),
):
    """Get auto-trades with pagination and filters.

    v6: Single source of truth for ALL trade history.
    Supports filtering by action, strategy, regime, entry_type.
    Returns newest first. offset=0 is most recent.
    """
    all_rows = _load_user_csv(user_id, "auto_trades.csv")
    # Filter out HOLD rows (only keep BUY/SELL unless specifically asked)
    if action:
        all_rows = [r for r in all_rows if r.get("action", "").upper() == action.upper()]
    else:
        all_rows = [r for r in all_rows if r.get("action", "HOLD") in ("BUY", "SELL")]

    if strategy:
        all_rows = [r for r in all_rows if strategy.lower() in r.get("strategy", "").lower()]
    if regime:
        all_rows = [r for r in all_rows if regime.upper() in r.get("regime", "").upper()]
    if entry_type:
        all_rows = [r for r in all_rows if entry_type.lower() in r.get("entry_type", "").lower()]

    total = len(all_rows)
    all_rows.reverse()  # newest first
    page = all_rows[offset:offset + limit]

    return {
        "count": len(page),
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": (offset + limit) < total,
        "trades": page,
    }


@app.get("/auto/trades/summary")
def get_trades_summary(user_id: str = Depends(get_user_id)):
    """Session summary for the trades page. Single-request overview."""
    all_rows = _load_user_csv(user_id, "auto_trades.csv")
    executed = [r for r in all_rows if r.get("action") in ("BUY", "SELL")]

    buys = [r for r in executed if r.get("action") == "BUY"]
    sells = [r for r in executed if r.get("action") == "SELL"]
    pnls = [_safe_float(r.get("pnl")) for r in sells]
    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p < 0)
    net_pnl = sum(pnls)
    best = max(pnls) if pnls else 0
    worst = min(pnls) if pnls else 0

    # Strategy breakdown
    strat_counts = {}
    strat_pnl = {}
    for r in executed:
        s = r.get("strategy", "unknown")
        strat_counts[s] = strat_counts.get(s, 0) + 1
        strat_pnl[s] = strat_pnl.get(s, 0) + _safe_float(r.get("pnl"))

    # Regime breakdown
    regime_counts = {}
    for r in executed:
        reg = r.get("regime", "unknown")
        regime_counts[reg] = regime_counts.get(reg, 0) + 1

    # Entry type breakdown
    entry_counts = {}
    for r in executed:
        et = r.get("entry_type", "full")
        entry_counts[et] = entry_counts.get(et, 0) + 1

    # Current state
    state = auto_trader.get_state()
    insight = auto_trader.get_session_insight()

    return {
        "total_trades": len(executed),
        "buys": len(buys),
        "sells": len(sells),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / (wins + losses) * 100, 1) if (wins + losses) > 0 else 0,
        "net_pnl": round(net_pnl, 6),
        "best_trade": round(best, 6),
        "worst_trade": round(worst, 6),
        "regime": state.get("market_state", {}).get("state", "SLEEPING"),
        "regime_score": state.get("market_state", {}).get("confidence_score", 0),
        "insight": insight.get("insight", ""),
        "strategy_breakdown": strat_counts,
        "strategy_pnl": {k: round(v, 6) for k, v in strat_pnl.items()},
        "regime_breakdown": regime_counts,
        "entry_type_breakdown": entry_counts,
    }


@app.get("/auto/equity")
def get_auto_equity(limit: int = Query(default=100, ge=1, le=1000), user_id: str = Depends(get_user_id)):
    """Get auto-trader equity curve."""
    rows = _load_user_csv(user_id, "auto_equity.csv", limit=limit)
    return {"count": len(rows), "equity": rows}


@app.get("/auto/journal")
def get_journal(limit: int = Query(default=50, ge=1, le=200), user_id: str = Depends(get_user_id)):
    """Get trade journal entries (newest first)."""
    entries = auto_trader.get_journal(user_id, limit=limit)
    return {"count": len(entries), "entries": entries}


@app.get("/auto/journal/summary")
def get_journal_summary(user_id: str = Depends(get_user_id)):
    """Get journal summary stats for strategy analysis."""
    return auto_trader.get_journal_summary(user_id)


# ---------------------------------------------------------------------------
# v7: System Age, Sessions, Memory, Feedback, Reviews
# ---------------------------------------------------------------------------

@app.get("/v7/system-age")
def get_system_age():
    """System age and session info. The heartbeat of v7."""
    try:
        import session_manager
        return session_manager.get_system_age()
    except Exception as e:
        return {"error": str(e), "system_age_cycles": 0}


@app.get("/v7/sessions")
def get_sessions():
    """All version sessions (current + archived)."""
    try:
        import session_manager
        sessions = session_manager.get_session_archive()
        current = session_manager.get_session_id()
        return {"sessions": sessions, "current_session_id": current}
    except Exception as e:
        return {"sessions": [], "error": str(e)}


@app.get("/v7/memory")
def get_memory_status():
    """Experience memory summary."""
    try:
        import memory_engine
        return memory_engine.get_memory_summary()
    except Exception as e:
        return {"total_memories": 0, "error": str(e)}


@app.get("/v7/memories")
def get_memories(
    memory_type: str = Query(default=""),
    strategy: str = Query(default=""),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Get active experience memories with optional filters."""
    try:
        import db as v7db
        import session_manager
        kwargs = {"limit": limit}
        if memory_type:
            kwargs["memory_type"] = memory_type
        if strategy:
            kwargs["strategy"] = strategy
        memories = v7db.get_active_memories(**kwargs)
        return {"count": len(memories), "memories": memories}
    except Exception as e:
        return {"count": 0, "memories": [], "error": str(e)}


@app.get("/v7/feedback")
def get_feedback_status():
    """Feedback loop and adaptation status."""
    try:
        import feedback as feedback_engine
        return feedback_engine.get_feedback_status()
    except Exception as e:
        return {"error": str(e)}


@app.get("/v7/adaptations")
def get_adaptations(limit: int = Query(default=20, ge=1, le=100)):
    """Recent behavior adaptations."""
    try:
        import db as v7db
        import session_manager
        sid = session_manager.get_session_id()
        adaptations = v7db.get_recent_adaptations(session_id=sid, limit=limit)
        return {"count": len(adaptations), "adaptations": adaptations}
    except Exception as e:
        return {"count": 0, "adaptations": [], "error": str(e)}


@app.get("/v7/behavior-profile")
def get_behavior_profile():
    """Current learned behavior profile."""
    try:
        import db as v7db
        import session_manager
        sid = session_manager.get_session_id()
        profile = v7db.get_active_profile(sid) if sid else None
        return {"profile": profile or {}}
    except Exception as e:
        return {"profile": {}, "error": str(e)}


@app.get("/v7/daily-review")
def get_latest_review():
    """Latest daily review."""
    try:
        import daily_review
        review = daily_review.get_latest_review()
        return {"review": review}
    except Exception as e:
        return {"review": None, "error": str(e)}


@app.get("/v7/daily-reviews")
def get_review_history(limit: int = Query(default=10, ge=1, le=50)):
    """Daily review history."""
    try:
        import daily_review
        reviews = daily_review.get_review_history(limit=limit)
        return {"count": len(reviews), "reviews": reviews}
    except Exception as e:
        return {"count": 0, "reviews": [], "error": str(e)}


@app.post("/v7/daily-review/generate")
def generate_review_now():
    """Generate a daily review on demand."""
    try:
        import daily_review
        review = daily_review.generate_review()
        return review
    except Exception as e:
        return {"error": str(e)}


@app.get("/v7/strategy-patterns/{name}")
def get_strategy_patterns(name: str):
    """Analyze patterns for a specific strategy."""
    try:
        import memory_engine
        return memory_engine.analyze_strategy_patterns(name.upper())
    except Exception as e:
        return {"error": str(e)}


@app.get("/v7/trades")
def get_v7_trades(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session_id: int = Query(default=0),
    action: str = Query(default=""),
    strategy: str = Query(default=""),
    regime: str = Query(default=""),
    entry_type: str = Query(default=""),
):
    """Get trades from the SQLite trade ledger with filters."""
    try:
        import db as v7db
        import session_manager
        sid = session_id if session_id > 0 else None
        trades, total = v7db.get_trades(
            session_id=sid, limit=limit, offset=offset,
            action=action or None, strategy=strategy or None,
            regime=regime or None, entry_type=entry_type or None,
        )
        return {
            "count": len(trades), "total": total,
            "offset": offset, "limit": limit,
            "has_more": (offset + limit) < total,
            "trades": trades,
        }
    except Exception as e:
        return {"count": 0, "total": 0, "trades": [], "error": str(e)}


@app.get("/v7/trade-summary")
def get_v7_trade_summary(session_id: int = Query(default=0)):
    """Trade summary from SQLite ledger."""
    try:
        import db as v7db
        sid = session_id if session_id > 0 else None
        return v7db.get_trade_summary(session_id=sid)
    except Exception as e:
        return {"total": 0, "error": str(e)}


# ---------------------------------------------------------------------------
# Enhanced debug state with v7 fields
# ---------------------------------------------------------------------------

@app.get("/v7/debug")
def debug_v7():
    """Full v7 debug state."""
    try:
        import session_manager
        import memory_engine
        import feedback as feedback_engine
        import db as v7db

        sid = session_manager.get_session_id()
        system = v7db.get_system_state()
        profile = v7db.get_active_profile(sid) if sid else None
        recent_memories = v7db.get_active_memories(limit=5)
        recent_adaptations = v7db.get_recent_adaptations(limit=5)
        latest_review = v7db.get_latest_review()

        return {
            "current_session_id": sid,
            "current_version": session_manager.APP_VERSION,
            "session_age_cycles": system.get("system_age_cycles", 0) if system else 0,
            "system_age_cycles": system.get("total_lifetime_cycles", 0) if system else 0,
            "total_lifetime_trades": system.get("total_lifetime_trades", 0) if system else 0,
            "active_behavior_profile": {
                k: round(profile.get(k, 0.5), 3)
                for k in ("aggressiveness", "patience", "probe_bias",
                          "trend_follow_bias", "conviction_threshold",
                          "overtrade_penalty", "noise_tolerance")
            } if profile else {},
            "latest_memory_items": [
                {"type": m.get("memory_type"), "lesson": m.get("lesson_text", "")[:80],
                 "times": m.get("times_observed", 0)}
                for m in recent_memories
            ],
            "latest_adaptations": [
                {"trigger": a.get("trigger_type"), "change": a.get("new_behavior", ""),
                 "status": a.get("validation_status", "pending")}
                for a in recent_adaptations
            ],
            "pending_daily_review": latest_review.get("review_date", "none") if latest_review else "none",
            "current_feedback_state": feedback_engine.get_feedback_status(),
        }
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# v7.1 Intelligence Endpoints
# ---------------------------------------------------------------------------

@app.get("/v7/outcomes")
def get_outcomes():
    """Delayed outcome evaluation summary."""
    try:
        import outcome_engine
        return outcome_engine.get_outcome_summary()
    except Exception as e:
        return {"error": str(e)}


@app.get("/v7/missed-opportunities")
def get_missed_opportunities():
    """Missed opportunity summary by severity/strategy/regime."""
    try:
        import db as v7db
        return v7db.get_missed_opportunity_summary()
    except Exception as e:
        return {"error": str(e)}


@app.get("/v7/regime-intelligence")
def get_regime_intelligence():
    """Regime-strategy performance matrix."""
    try:
        import regime_intelligence
        return regime_intelligence.get_regime_intelligence_summary()
    except Exception as e:
        return {"error": str(e)}


@app.get("/v7/behavior-state")
def get_behavior_state():
    """Current market_reward_state and system_self_state."""
    try:
        import behavior_intelligence
        return behavior_intelligence.get_behavior_state_summary()
    except Exception as e:
        return {"error": str(e)}


@app.get("/v7/daily-bias")
def get_daily_bias():
    """Current active daily bias."""
    try:
        import daily_review
        bias = daily_review.get_active_bias_summary()
        return bias if bias else {"status": "no_active_bias"}
    except Exception as e:
        return {"error": str(e)}


@app.get("/v7/thinking-status")
def get_thinking_status():
    """Combined v7.1+ intelligence dashboard summary."""
    try:
        import outcome_engine
        import regime_intelligence
        import behavior_intelligence
        import daily_review
        import discipline_guard
        import db as v7db

        return {
            "version": "7.2.0",
            "outcomes": outcome_engine.get_outcome_summary(),
            "missed_opportunities": v7db.get_missed_opportunity_summary(),
            "regime_intelligence": regime_intelligence.get_regime_intelligence_summary(),
            "behavior_state": behavior_intelligence.get_behavior_state_summary(),
            "daily_bias": daily_review.get_active_bias_summary(),
            "discipline": discipline_guard.get_discipline_status(),
        }
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# v7.2 Discipline Guard Endpoints
# ---------------------------------------------------------------------------

@app.get("/v7/discipline")
def get_discipline():
    """Full discipline guard state — minimums, cooldowns, recent events."""
    try:
        import discipline_guard
        import auto_trader
        cycle = auto_trader._state.get("cycle_count", 0)
        return discipline_guard.get_discipline_status(current_cycle=cycle)
    except Exception as e:
        return {"error": str(e)}


@app.get("/v7/adaptation-journal")
def get_adaptation_journal(
    limit: int = Query(default=20, ge=1, le=100),
    status: str = Query(default=None),
):
    """Adaptation journal — full audit trail of every adaptation attempt."""
    try:
        import db as v7db
        import session_manager
        sid = session_manager.get_session_id()
        entries = v7db.get_adaptation_journal(
            session_id=sid, limit=limit, status_filter=status
        )
        return {"entries": entries, "total": len(entries)}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# v7.3: Mind Evolution Layer (read-only intelligence)
# ---------------------------------------------------------------------------


@app.get("/v7/mind")
def get_mind_state():
    """Full mind evolution state — score, level, skills, system age."""
    try:
        import mind_evolution
        return mind_evolution.get_full_mind_state()
    except Exception as e:
        return {"error": str(e), "evolution_score": 0}


@app.get("/v7/mind/history")
def get_mind_history(limit: int = Query(default=100, ge=1, le=500)):
    """Evolution score history for charting."""
    try:
        import mind_evolution
        history = mind_evolution.get_evolution_history(limit=limit)
        return {"history": history, "count": len(history)}
    except Exception as e:
        return {"error": str(e), "history": []}


@app.get("/v7/mind/skills")
def get_mind_skills():
    """Skill breakdown — 9 sub-scores with descriptions."""
    try:
        import mind_evolution
        skills = mind_evolution.compute_skill_breakdown()
        return {"skills": skills}
    except Exception as e:
        return {"error": str(e), "skills": []}


@app.get("/v7/mind/lessons")
def get_mind_lessons():
    """Recent learning feed — improvements, regressions, strengths, weaknesses."""
    try:
        import mind_evolution
        feed = mind_evolution.get_recent_learning()
        return {"feed": feed, "count": len(feed)}
    except Exception as e:
        return {"error": str(e), "feed": []}


@app.get("/v7/mind/timeline")
def get_mind_timeline():
    """Version/session timeline with milestones."""
    try:
        import mind_evolution
        import db as v7db
        timeline = mind_evolution.get_session_timeline()
        milestones = v7db.get_milestones(limit=50)
        return {"timeline": timeline, "milestones": milestones}
    except Exception as e:
        return {"error": str(e), "timeline": [], "milestones": []}


# ---------------------------------------------------------------------------
# Static frontend serving (production desktop app)
#
# Serves the built React frontend so the Electron app can load everything
# from http://localhost:8000 — no file://, no CORS issues.
#
# Problem: React SPA routes (/trades, /performance, /journal) collide with
# API endpoint names. Solution: middleware intercepts browser navigation
# requests (Accept: text/html) for known SPA routes and serves index.html
# BEFORE FastAPI routing runs. API calls (Accept: application/json) pass
# through to the normal endpoints.
# ---------------------------------------------------------------------------

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse
from config import PROJECT_ROOT

_frontend_candidates = [
    PROJECT_ROOT / "frontend" / "dist",   # dev: btc-paper-trader/frontend/dist/
    PROJECT_ROOT / "frontend",            # prod bundle: Resources/frontend/
]

_frontend_dir = None
for _candidate in _frontend_candidates:
    if (_candidate / "index.html").exists():
        _frontend_dir = _candidate
        break

if _frontend_dir:
    _index_html = _frontend_dir / "index.html"

    # Known SPA routes that collide with API endpoints
    _SPA_PATHS = {"/", "/trades", "/performance", "/journal", "/leaderboard", "/memory", "/mind"}

    class SPAMiddleware(BaseHTTPMiddleware):
        """Serve index.html for browser navigation to SPA routes.

        Only intercepts GET requests that:
        1. Match a known SPA path
        2. Accept text/html (browser navigation, not API calls)

        API calls (fetch with Accept: application/json) pass through normally.
        Always reads index.html fresh from disk to avoid stale cache issues.
        """
        async def dispatch(self, request, call_next):
            if (
                request.method == "GET"
                and request.url.path in _SPA_PATHS
                and "text/html" in request.headers.get("accept", "")
            ):
                # Always read fresh — never cache index.html bytes
                fresh_bytes = _index_html.read_bytes()
                return StarletteResponse(
                    content=fresh_bytes,
                    media_type="text/html",
                    headers={
                        "Cache-Control": "no-cache, no-store, must-revalidate",
                        "Pragma": "no-cache",
                        "Expires": "0",
                    },
                )
            return await call_next(request)

    app.add_middleware(SPAMiddleware)

    # Serve static assets (JS, CSS, images)
    if (_frontend_dir / "assets").exists():
        app.mount("/assets", StaticFiles(directory=str(_frontend_dir / "assets")), name="static-assets")

    # Serve PWA files from root
    _sw_path = _frontend_dir / "sw.js"
    _manifest_path = _frontend_dir / "manifest.json"

    if _sw_path.exists():
        @app.get("/sw.js")
        async def serve_sw():
            return FileResponse(str(_sw_path), media_type="application/javascript",
                                headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})

    if _manifest_path.exists():
        @app.get("/manifest.json")
        async def serve_manifest():
            return FileResponse(str(_manifest_path), media_type="application/manifest+json")

    # Serve PWA icons
    for icon_name in ["icon-192.png", "icon-512.png"]:
        _icon_path = _frontend_dir / icon_name
        if _icon_path.exists():
            def _make_icon_route(p):
                @app.get(f"/{p.name}")
                async def serve_icon(path=p):
                    return FileResponse(str(path), media_type="image/png")
            _make_icon_route(_icon_path)

    print(f"[api] Serving frontend from {_frontend_dir} (SPA routes: {_SPA_PATHS})")
else:
    print("[api] No built frontend found — static serving disabled (use Vite dev server)")
