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
    title="BTC Paper Trader API",
    description="Multi-user REST API for the paper trading system.",
    version="2.0.0",
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
    """Ensure default admin user exists and start trading on every wake-up.

    Render free tier sleeps after 15 min of inactivity. On wake, this
    runs again — the auto-trader restarts cleanly from where it left off.
    """
    from datetime import datetime, timezone
    boot_time = datetime.now(timezone.utc).isoformat()
    print(f"[api] ===== CryptoMind starting at {boot_time} =====")

    ensure_admin()
    result = seed_user("admin")
    if result.get("seeded"):
        print(f"[api] Seeded admin with demo data: {result['trades']} trades, {result['equity_points']} equity points")
    else:
        print(f"[api] Admin data already exists — resuming")

    # Auto-start the trading loop (safe to call after sleep — restarts cleanly)
    auto_result = auto_trader.start("admin")
    print(f"[api] Auto-trader: {auto_result['status']} (every {auto_result.get('interval', 30)}s)")
    print(f"[api] Dashboard ready. Trading loop active.")


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
def get_auto_trades(limit: int = Query(default=20, ge=1, le=100), user_id: str = Depends(get_user_id)):
    """Get recent auto-trades."""
    rows = _load_user_csv(user_id, "auto_trades.csv", limit=limit)
    rows.reverse()
    return {"count": len(rows), "trades": rows}


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
    _index_bytes = _index_html.read_bytes()

    # Known SPA routes that collide with API endpoints
    _SPA_PATHS = {"/", "/trades", "/performance", "/journal", "/leaderboard"}

    class SPAMiddleware(BaseHTTPMiddleware):
        """Serve index.html for browser navigation to SPA routes.

        Only intercepts GET requests that:
        1. Match a known SPA path
        2. Accept text/html (browser navigation, not API calls)

        API calls (fetch with Accept: application/json) pass through normally.
        """
        async def dispatch(self, request, call_next):
            if (
                request.method == "GET"
                and request.url.path in _SPA_PATHS
                and "text/html" in request.headers.get("accept", "")
            ):
                return StarletteResponse(
                    content=_index_bytes,
                    media_type="text/html",
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
