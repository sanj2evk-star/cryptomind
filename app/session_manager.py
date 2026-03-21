"""
session_manager.py — CryptoMind v7 Session & System State Manager.

Handles:
- Version-scoped session creation and closure
- System age tracking (cycles, hours, lifetime)
- Startup detection (new version vs resume vs cold start)
- CSV → SQLite migration on first v7 boot
- System state persistence across restarts
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import db
from config import DATA_DIR

# ---------------------------------------------------------------------------
# App version — single source of truth
# ---------------------------------------------------------------------------

APP_VERSION = "7.0.0"

# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

_current_session_id: int | None = None
_boot_time: float = 0.0
_boot_cycle: int = 0


def get_session_id() -> int | None:
    """Get the current active session ID."""
    return _current_session_id


def get_version() -> str:
    return APP_VERSION


# ---------------------------------------------------------------------------
# Startup — called once from api.py startup
# ---------------------------------------------------------------------------

def initialize() -> dict:
    """Initialize the v7 persistence layer.

    1. Create DB tables if needed
    2. Detect version: new install, version upgrade, or resume
    3. Close prior sessions if version changed
    4. Create new session or resume existing
    5. Migrate CSV trades on first v7 boot
    6. Initialize system state
    7. Create default behavior profile

    Returns summary dict for logging.
    """
    global _current_session_id, _boot_time, _boot_cycle

    _boot_time = time.time()
    summary = {"version": APP_VERSION, "action": "unknown"}

    # 1. Init DB
    db.init_db()

    # 2. Check for existing active session
    active = db.get_active_session()
    system = db.get_system_state()

    if active and active["app_version"] == APP_VERSION:
        # RESUME — same version, session already open
        _current_session_id = active["session_id"]
        _boot_cycle = system.get("last_cycle_number", 0) if system else 0
        summary["action"] = "resumed"
        summary["session_id"] = _current_session_id
        summary["resumed_cycles"] = _boot_cycle
        print(f"[session] Resumed v{APP_VERSION} session #{_current_session_id} "
              f"at cycle {_boot_cycle}")

    elif active and active["app_version"] != APP_VERSION:
        # VERSION UPGRADE — close old session, start new one
        old_version = active["app_version"]
        old_session = active["session_id"]
        db.close_session(
            old_session,
            notes=f"Auto-closed: upgrade from v{old_version} to v{APP_VERSION}"
        )
        _current_session_id = db.create_session(APP_VERSION)
        _boot_cycle = 0
        summary["action"] = "upgraded"
        summary["from_version"] = old_version
        summary["closed_session"] = old_session
        summary["session_id"] = _current_session_id
        print(f"[session] Upgraded v{old_version} → v{APP_VERSION}. "
              f"Closed session #{old_session}, opened #{_current_session_id}")

    else:
        # NEW INSTALL or first v7 boot
        # Close any stale active sessions
        closed = db.close_all_active_sessions()
        if closed:
            print(f"[session] Closed {closed} stale session(s)")

        _current_session_id = db.create_session(APP_VERSION)
        _boot_cycle = 0
        summary["action"] = "new_session"
        summary["session_id"] = _current_session_id

        # Migrate CSV trades if they exist
        csv_path = _find_csv_trades()
        if csv_path:
            # Create a pre-v7 archive session for historical trades
            archive_id = db.create_session("pre-v7", start_equity=100.0)
            db.close_session(archive_id, notes="Archived trades from CSV (pre-v7)")
            count = db.migrate_csv_trades(csv_path, archive_id, version_tag="pre-v7")
            summary["migrated_trades"] = count
            print(f"[session] Migrated {count} historical trades from CSV → SQLite")

        print(f"[session] New v{APP_VERSION} session #{_current_session_id}")

    # 3. Initialize / update system state
    if not system:
        db.upsert_system_state(
            current_session_id=_current_session_id,
            current_version=APP_VERSION,
            system_age_cycles=0,
            system_age_hours=0.0,
            total_lifetime_cycles=0,
            total_lifetime_trades=0,
            last_cycle_number=0,
        )
    else:
        db.upsert_system_state(
            current_session_id=_current_session_id,
            current_version=APP_VERSION,
        )

    # 4. Create default behavior profile if none exists
    profile = db.get_active_profile(_current_session_id)
    if not profile:
        db.upsert_behavior_profile(_current_session_id)
        print(f"[session] Created default behavior profile")

    return summary


def _find_csv_trades() -> Path | None:
    """Find the auto_trades.csv file for migration."""
    candidates = [
        DATA_DIR / "admin" / "auto_trades.csv",
        DATA_DIR / "auto_trades.csv",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


# ---------------------------------------------------------------------------
# Cycle hooks — called from auto_trader every cycle
# ---------------------------------------------------------------------------

def on_cycle_complete(cycle_number: int, indicators: dict, decision: dict,
                      portfolio: dict, price: float, regime: str,
                      dominant_strategy: str, market_quality: int,
                      blocked_reason: str = "") -> None:
    """Called after each trading cycle completes.

    Updates system state, session stats, and records cycle snapshot.
    """
    global _boot_cycle

    if not _current_session_id:
        return

    now = datetime.now(timezone.utc).isoformat()
    elapsed_hours = (time.time() - _boot_time) / 3600

    # Update system state
    db.increment_system_counters(cycles=1)
    db.upsert_system_state(
        last_cycle_number=cycle_number,
        current_regime=regime,
        current_dominant_strategy=dominant_strategy,
        current_market_quality=market_quality,
        system_age_hours=round(elapsed_hours, 2),
    )

    # Update session cycle count
    db.update_session_stats(_current_session_id, total_cycles=cycle_number - _boot_cycle)

    # Record cycle snapshot (every cycle — SQLite handles it fine)
    equity = portfolio.get("cash", 0) + portfolio.get("btc_holdings", 0) * price
    action = decision.get("action", "HOLD")
    score = decision.get("score", 0)
    confidence = decision.get("confidence", 0)

    db.insert_cycle_snapshot(
        session_id=_current_session_id,
        cycle_number=cycle_number,
        price=round(price, 2),
        rsi=round(indicators.get("rsi", 0), 2),
        ema_short=round(indicators.get("ema_short", 0), 2),
        ema_long=round(indicators.get("ema_long", 0), 2),
        accel=round(indicators.get("acceleration", 0), 2),
        volatility=round(indicators.get("volatility", 0), 6),
        trend=indicators.get("trend", ""),
        regime=regime,
        decision_action=action,
        decision_score=round(score, 2),
        decision_confidence=round(confidence, 3),
        exposure_pct=round(portfolio.get("btc_holdings", 0) * price / max(equity, 1) * 100, 1),
        holdings_btc=round(portfolio.get("btc_holdings", 0), 8),
        cash=round(portfolio.get("cash", 0), 4),
        equity=round(equity, 4),
        dominant_strategy=dominant_strategy,
        market_quality_score=market_quality,
        blocked_trade_reason=blocked_reason,
        short_summary=_make_cycle_summary(action, score, regime, price),
    )


def on_trade_executed(action: str, price: float, qty: float, dollar_size: float,
                      pnl: float, strategy: str, regime: str, entry_type: str,
                      score: float, confidence: float, reason: str,
                      hold_zone_adj: float = 0, exposure_pct: float = 0,
                      market_quality: int = 0) -> int | None:
    """Called when a trade is committed to the real portfolio.

    Logs to trade_ledger and updates session stats.
    Returns trade_id.
    """
    if not _current_session_id:
        return None

    trade_id = db.insert_trade(
        session_id=_current_session_id,
        action=action,
        price=round(price, 2),
        qty=round(qty, 8),
        dollar_size=round(dollar_size, 4),
        pnl=round(pnl, 6),
        strategy=strategy,
        regime=regime,
        entry_type=entry_type,
        score=round(score, 2),
        confidence=round(confidence, 3),
        reason=reason,
        hold_zone_adj=round(hold_zone_adj, 2),
        exposure_pct_after=round(exposure_pct, 2),
        market_quality_score=market_quality,
        version_tag=APP_VERSION,
    )

    # Update session trade counts
    session = db.get_active_session(APP_VERSION)
    if session:
        updates = {"total_trades": session["total_trades"] + 1}
        if action == "BUY":
            updates["total_buys"] = session["total_buys"] + 1
        elif action == "SELL":
            updates["total_sells"] = session["total_sells"] + 1
            updates["realized_pnl"] = round(session["realized_pnl"] + pnl, 6)
        db.update_session_stats(_current_session_id, **updates)

    # Update lifetime trade count
    db.increment_system_counters(trades=1)

    return trade_id


# ---------------------------------------------------------------------------
# System Age API
# ---------------------------------------------------------------------------

def get_system_age() -> dict:
    """Get system age metrics for UI display."""
    system = db.get_system_state()
    if not system:
        return {
            "system_age_cycles": 0,
            "system_age_hours": 0,
            "total_lifetime_cycles": 0,
            "total_lifetime_trades": 0,
            "current_session_version": APP_VERSION,
            "current_session_id": _current_session_id,
            "current_session_cycles": 0,
            "current_session_hours": round((time.time() - _boot_time) / 3600, 2),
        }

    session = db.get_active_session(APP_VERSION)
    session_cycles = session["total_cycles"] if session else 0

    return {
        "system_age_cycles": system["total_lifetime_cycles"],
        "system_age_hours": round(system["system_age_hours"], 2),
        "total_lifetime_cycles": system["total_lifetime_cycles"],
        "total_lifetime_trades": system["total_lifetime_trades"],
        "current_session_version": APP_VERSION,
        "current_session_id": _current_session_id,
        "current_session_cycles": session_cycles,
        "current_session_hours": round((time.time() - _boot_time) / 3600, 2),
        "current_regime": system.get("current_regime", "SLEEPING"),
        "current_dominant_strategy": system.get("current_dominant_strategy", "HUNTER"),
        "current_market_quality": system.get("current_market_quality", 0),
        "last_adaptation_at": system.get("last_adaptation_at"),
        "last_daily_review_at": system.get("last_daily_review_at"),
    }


def get_session_archive() -> list[dict]:
    """Get all sessions for the archive view."""
    return db.get_all_sessions()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_cycle_summary(action: str, score: float, regime: str, price: float) -> str:
    """Generate a short one-line summary for a cycle."""
    if action == "BUY":
        return f"BUY at ${price:,.0f} (score {score:.0f}, {regime})"
    elif action == "SELL":
        return f"SELL at ${price:,.0f} (score {score:.0f}, {regime})"
    else:
        return f"HOLD (score {score:.0f}, {regime})"
