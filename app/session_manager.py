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

APP_VERSION = "7.7.2"

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
        # Identity + portfolio persist: do NOT reset global state or finances
        old_version = active["app_version"]
        old_session = active["session_id"]

        # Snapshot financial state BEFORE closing
        _preserve_portfolio_on_upgrade(old_session, old_version, APP_VERSION)

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

        # Continuity: increment lifetime identity session count
        db.increment_identity_counters(sessions=1)
        db.upsert_lifetime_identity(last_version=APP_VERSION)

        print(f"[session] Upgraded v{old_version} → v{APP_VERSION}. "
              f"Closed session #{old_session}, opened #{_current_session_id}. "
              f"Identity + portfolio preserved.")

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

    # 4a. Self-heal lifetime portfolio (EVERY startup, not just first boot)
    _heal_lifetime_portfolio(system)

    # 4b. Self-heal lifetime identity (EVERY startup, not just first boot)
    _heal_lifetime_identity(system)

    # 4c. v7.7.0: Rehydrate lifetime summaries from all historical sources
    try:
        import lifetime_rehydration_engine
        rh = lifetime_rehydration_engine.force_rehydrate()
        print(f"[session] Rehydration: {rh.get('rehydration_status', '?')} "
              f"(sources: {rh.get('sources_used', [])})")
    except Exception as e:
        print(f"[session] Rehydration error (non-fatal): {e}")

    # 5. Create default behavior profile if none exists
    profile = db.get_active_profile(_current_session_id)
    if not profile:
        db.upsert_behavior_profile(_current_session_id)
        print(f"[session] Created default behavior profile")

    # 6. v7.1: Create default behavior state if none exists
    bstate = db.get_behavior_state(_current_session_id)
    if not bstate:
        db.upsert_behavior_state(_current_session_id, cycle_number=0)
        print(f"[session] Created default behavior state (v7.1)")

    # 7. v7.7.1: Identity rehydration — restore behavior/confidence/skills from history
    #    Runs AFTER default profile/state creation so it can overwrite defaults
    try:
        import identity_rehydration_engine
        ident = identity_rehydration_engine.force_rehydrate_identity()
        print(f"[session] Identity: {ident.get('rehydration_status', '?')} "
              f"maturity={ident.get('maturity_level', {}).get('level', '?')} "
              f"continuity={ident.get('continuity_score', 0):.0f} "
              f"depth={ident.get('identity_depth', 0):.0f}")
    except Exception as e:
        print(f"[session] Identity rehydration error (non-fatal): {e}")

    return summary


def _heal_lifetime_portfolio(system: dict | None) -> None:
    """Self-heal lifetime portfolio on EVERY startup.

    Recovers from amnesia:
    - If lifetime_portfolio is missing → recreate from capital_ledger or trade_ledger
    - If lifetime_portfolio exists but has stale zeros while trade_ledger has data → rebuild
    - NEVER overwrites a populated portfolio with zeros
    """
    lt_portfolio = db.get_lifetime_portfolio()

    if lt_portfolio:
        # Portfolio exists — check for stale zeros
        lt_trades = lt_portfolio.get("total_trades", 0) or 0
        actual_trades = _count_lifetime_trades()

        if lt_trades == 0 and actual_trades > 0:
            # Portfolio has 0 trades but trade_ledger has data → rebuild
            _rebuild_portfolio_from_trades(actual_trades)
            print(f"[session] HEALED: lifetime_portfolio had 0 trades but trade_ledger has {actual_trades}. Rebuilt.")
        else:
            # Portfolio looks healthy
            db.upsert_lifetime_identity(last_version=APP_VERSION)
        return

    # Portfolio missing — try to recover
    # 1. Check capital_ledger for prior funding
    existing_funding = [e for e in db.get_capital_events(limit=100)
                        if e.get("event_type") == "initial_funding"]
    if existing_funding:
        last_funding = existing_funding[0]
        balance = last_funding.get("balance_after") or last_funding.get("amount", 100)
        db.upsert_lifetime_portfolio(cash=balance, total_equity=balance, peak_equity=balance)
        print(f"[session] HEALED: lifetime_portfolio re-created from capital_ledger: ${balance}")
        # Rebuild trade stats if available
        actual_trades = _count_lifetime_trades()
        if actual_trades > 0:
            _rebuild_portfolio_from_trades(actual_trades)
        return

    # 2. Check if trade_ledger has history we can rebuild from
    actual_trades = _count_lifetime_trades()
    if actual_trades > 0:
        from config import INITIAL_BALANCE
        db.upsert_lifetime_portfolio(cash=INITIAL_BALANCE, total_equity=INITIAL_BALANCE,
                                      peak_equity=INITIAL_BALANCE)
        _rebuild_portfolio_from_trades(actual_trades)
        print(f"[session] HEALED: lifetime_portfolio rebuilt from {actual_trades} trades in trade_ledger")
        return

    # 3. True first boot — seed from INITIAL_BALANCE
    from config import INITIAL_BALANCE
    db.upsert_lifetime_portfolio(cash=INITIAL_BALANCE, total_equity=INITIAL_BALANCE,
                                  peak_equity=INITIAL_BALANCE)
    db.insert_capital_event(
        event_type="initial_funding", amount=INITIAL_BALANCE,
        balance_after=INITIAL_BALANCE, reason="System initial funding",
        session_id=_current_session_id, version=APP_VERSION,
    )
    print(f"[session] Lifetime portfolio initialized: ${INITIAL_BALANCE}")


def _heal_lifetime_identity(system: dict | None) -> None:
    """Self-heal lifetime identity on EVERY startup.

    Recovers from amnesia:
    - If lifetime_identity is missing → recreate from system_state + version_sessions
    - If lifetime_identity has stale zeros while real data exists → rebuild
    - NEVER overwrites populated identity with lower values
    """
    identity = db.get_lifetime_identity()

    # Gather ground-truth counts from actual data
    all_sessions = db.get_all_sessions() or []
    real_sessions = [s for s in all_sessions if s.get("app_version", "") != "pre-v7"]
    actual_sessions = max(1, len(real_sessions))
    actual_cycles = (system.get("total_lifetime_cycles", 0) or 0) if system else 0
    actual_trades = _count_lifetime_trades()

    # Also count from trade_ledger directly if system_state is stale
    if actual_trades > 0 and actual_cycles == 0:
        # System says 0 cycles but we have trades — estimate from snapshots
        try:
            from db import get_db
            with get_db() as conn:
                row = conn.execute("SELECT MAX(cycle_number) as m FROM cycle_snapshots").fetchone()
                if row and row["m"]:
                    actual_cycles = row["m"]
        except Exception:
            pass

    if identity:
        # Identity exists — check for stale zeros and heal
        id_cycles = identity.get("total_cycles", 0) or 0
        id_trades = identity.get("total_trades", 0) or 0
        id_sessions = identity.get("total_sessions", 0) or 0

        healed = False
        updates = {"last_version": APP_VERSION}

        # NEVER reduce — only increase
        if actual_cycles > id_cycles:
            updates["total_cycles"] = actual_cycles
            healed = True
        if actual_trades > id_trades:
            updates["total_trades"] = actual_trades
            healed = True
        if actual_sessions > id_sessions:
            updates["total_sessions"] = actual_sessions
            healed = True

        db.upsert_lifetime_identity(**updates)
        if healed:
            print(f"[session] HEALED: lifetime_identity updated — "
                  f"cycles: {id_cycles}→{updates.get('total_cycles', id_cycles)}, "
                  f"trades: {id_trades}→{updates.get('total_trades', id_trades)}, "
                  f"sessions: {id_sessions}→{updates.get('total_sessions', id_sessions)}")
        return

    # Identity missing — create from ground truth
    db.upsert_lifetime_identity(
        total_cycles=actual_cycles,
        total_trades=actual_trades,
        total_sessions=actual_sessions,
        last_version=APP_VERSION,
    )
    print(f"[session] HEALED: lifetime_identity created — "
          f"{actual_cycles} cycles, {actual_trades} trades, {actual_sessions} sessions")


def _count_lifetime_trades() -> int:
    """Count total trades across ALL sessions from trade_ledger."""
    try:
        from db import get_db
        with get_db() as conn:
            row = conn.execute("SELECT COUNT(*) as c FROM trade_ledger").fetchone()
            return row["c"] if row else 0
    except Exception:
        return 0


def _rebuild_portfolio_from_trades(total_trades: int) -> None:
    """Rebuild lifetime_portfolio trade stats from actual trade_ledger data."""
    try:
        from db import get_db
        with get_db() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN action='BUY' THEN 1 ELSE 0 END) as buys,
                    SUM(CASE WHEN action='SELL' THEN 1 ELSE 0 END) as sells,
                    SUM(CASE WHEN action='SELL' AND pnl > 0 THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN action='SELL' AND pnl < 0 THEN 1 ELSE 0 END) as losses,
                    COALESCE(SUM(CASE WHEN action='SELL' THEN pnl ELSE 0 END), 0) as realized_pnl
                FROM trade_ledger
            """).fetchone()
            if row:
                db.upsert_lifetime_portfolio(
                    total_trades=row["total"] or 0,
                    total_wins=row["wins"] or 0,
                    total_losses=row["losses"] or 0,
                    realized_pnl=round(row["realized_pnl"] or 0, 6),
                )
    except Exception as e:
        print(f"[session] Portfolio rebuild warning: {e}")


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

    # Update system state + lifetime identity
    db.increment_system_counters(cycles=1)
    db.increment_identity_counters(cycles=1)
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

    # v7.4.1: Sync lifetime portfolio every 10 cycles
    if cycle_number > 0 and cycle_number % 10 == 0:
        sync_portfolio_snapshot(portfolio, price)

    # v7.3: Take evolution snapshot every 100 cycles
    if cycle_number > 0 and cycle_number % 100 == 0:
        try:
            import mind_evolution
            mind_evolution.take_evolution_snapshot(_current_session_id, cycle_number)
        except Exception as e:
            print(f"[session] Evolution snapshot error: {e}")


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
    db.increment_identity_counters(trades=1)

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
# Lifetime financial continuity
# ---------------------------------------------------------------------------

def _preserve_portfolio_on_upgrade(old_session_id: int, old_version: str, new_version: str):
    """Snapshot portfolio state into lifetime_portfolio before version upgrade.
    Ensures cash, holdings, PnL, counters all persist."""
    try:
        # Capture current financial state for the upgrade log
        lt_portfolio = db.get_lifetime_portfolio()
        balance_snapshot = lt_portfolio.get("total_equity") if lt_portfolio else None
        cash_snapshot = lt_portfolio.get("cash", 0) if lt_portfolio else 0

        # Log the version transition with actual financial snapshot
        db.insert_capital_event(
            event_type="version_upgrade",
            amount=0,
            balance_after=balance_snapshot,
            reason=f"Upgrade from v{old_version} to v{new_version}",
            session_id=old_session_id,
            version=new_version,
            notes=f"Session #{old_session_id} closed. Cash: ${cash_snapshot:.2f}, Equity: ${balance_snapshot:.2f}" if balance_snapshot else f"Session #{old_session_id} closed, portfolio preserved",
        )
    except Exception as e:
        print(f"[session] Portfolio preservation warning: {e}")


def sync_portfolio_snapshot(portfolio: dict, price: float):
    """Sync lifetime_portfolio from auto_trader state. Called every cycle."""
    try:
        cash = float(portfolio.get("cash", 0))
        btc = float(portfolio.get("btc_holdings", 0))
        avg_entry = float(portfolio.get("avg_entry_price", 0))
        rpnl = float(portfolio.get("realized_pnl", 0))
        total_t = int(portfolio.get("total_trades", 0))
        wins = int(portfolio.get("wins", 0))
        losses = int(portfolio.get("losses", 0))
        holds = int(portfolio.get("hold_count", 0))
        blocked = int(portfolio.get("blocked_trades", 0))
        db.sync_lifetime_portfolio(
            cash=cash, btc_holdings=btc, avg_entry=avg_entry,
            price=price, realized_pnl=rpnl,
            total_trades=total_t, wins=wins, losses=losses,
            holds=holds, blocked=blocked,
        )
    except Exception:
        pass  # non-critical


_last_refill_ts: float = 0.0
_REFILL_COOLDOWN: float = 10.0  # seconds — prevents accidental double-submit


def record_refill(amount: float, reason: str = "Manual refill") -> dict:
    """Record a capital refill — adds cash, does NOT reset stats.
    Has 10-second cooldown to prevent accidental duplicate refills."""
    global _last_refill_ts

    if not _current_session_id:
        return {"error": "No active session"}

    if amount <= 0:
        return {"error": "Amount must be positive"}

    # Idempotency: reject if same refill within cooldown window
    now = time.time()
    if (now - _last_refill_ts) < _REFILL_COOLDOWN:
        return {"error": "Refill too soon — please wait 10 seconds between refills",
                "cooldown_remaining": round(_REFILL_COOLDOWN - (now - _last_refill_ts), 1)}

    portfolio = db.get_lifetime_portfolio()
    old_cash = portfolio.get("cash", 0) if portfolio else 0
    new_cash = old_cash + amount

    db.insert_capital_event(
        event_type="refill",
        amount=amount,
        balance_after=round(new_cash, 4),
        reason=reason,
        session_id=_current_session_id,
        version=APP_VERSION,
    )
    db.upsert_lifetime_portfolio(
        cash=round(new_cash, 4),
        total_refills=(portfolio.get("total_refills", 0) or 0) + 1,
        total_refill_amount=round((portfolio.get("total_refill_amount", 0) or 0) + amount, 4),
    )

    _last_refill_ts = now
    return {"old_cash": round(old_cash, 4), "added": amount, "new_cash": round(new_cash, 4)}


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


# ---------------------------------------------------------------------------
# Continuity Diagnostic (v7.6.2)
# ---------------------------------------------------------------------------

def get_continuity_audit() -> dict:
    """Full continuity health audit — DB path, table counts, warnings.

    Returns a diagnostic dict for debugging amnesia issues.
    """
    import os

    db_path = str(db.DB_PATH)
    db_exists = os.path.exists(db_path)
    db_size = os.path.getsize(db_path) if db_exists else 0
    db_modified = ""
    if db_exists:
        from datetime import datetime as _dt
        db_modified = _dt.fromtimestamp(os.path.getmtime(db_path)).isoformat()

    # Table counts
    table_counts = {}
    critical_tables = [
        "system_state", "version_sessions", "trade_ledger", "cycle_snapshots",
        "strategy_state", "behavior_profile", "experience_memory",
        "experience_outcomes", "missed_opportunities", "daily_reviews",
        "daily_bias", "regime_profiles", "behavior_states",
        "adaptation_events", "adaptation_journal", "evolution_snapshots",
        "milestones", "news_events", "news_event_analysis",
        "mind_feed_events", "mind_journal_entries", "action_reflections",
        "news_truth_reviews", "replay_markers", "personality_snapshots",
        "session_intents", "lifetime_mind_stats", "lifetime_identity",
        "lifetime_portfolio", "capital_ledger", "crowd_sentiment_events",
        "signal_events", "mind_state_snapshots",
    ]
    try:
        from db import get_db
        with get_db() as conn:
            for table in critical_tables:
                try:
                    row = conn.execute(f"SELECT COUNT(*) as c FROM [{table}]").fetchone()
                    table_counts[table] = row["c"] if row else 0
                except Exception:
                    table_counts[table] = -1  # table doesn't exist
    except Exception:
        pass

    # Current state
    system = db.get_system_state() or {}
    identity = db.get_lifetime_identity() or {}
    lt_portfolio = db.get_lifetime_portfolio() or {}
    all_sessions = db.get_all_sessions() or []

    # Ground truth from trade_ledger
    actual_trades = _count_lifetime_trades()

    # Warnings
    warnings = []

    # Check: DB path anomalies
    if not db_exists:
        warnings.append("DB file does not exist at expected path!")

    # Check: lifetime tables empty but history exists
    if table_counts.get("lifetime_identity", 0) == 0:
        warnings.append("lifetime_identity is EMPTY — identity not persisting across versions")
    if table_counts.get("lifetime_portfolio", 0) == 0:
        warnings.append("lifetime_portfolio is EMPTY — financial state not persisting")
    if table_counts.get("capital_ledger", 0) == 0:
        warnings.append("capital_ledger is EMPTY — no funding events recorded")

    # Check: trade_ledger vs system_state disagreement
    sys_trades = system.get("total_lifetime_trades", 0) or 0
    id_trades = identity.get("total_trades", 0) or 0
    if actual_trades > 0 and sys_trades == 0:
        warnings.append(f"trade_ledger has {actual_trades} trades but system_state says 0")
    if actual_trades > 0 and id_trades == 0:
        warnings.append(f"trade_ledger has {actual_trades} trades but lifetime_identity says 0")

    # Check: stale session version
    active = db.get_active_session()
    if active and active.get("app_version") != APP_VERSION:
        warnings.append(f"Active session version ({active.get('app_version')}) != current ({APP_VERSION}) — upgrade pending")

    # Check: cycle_snapshots vs system_state
    sys_cycles = system.get("total_lifetime_cycles", 0) or 0
    cs_count = table_counts.get("cycle_snapshots", 0)
    if cs_count > 0 and sys_cycles == 0:
        warnings.append(f"cycle_snapshots has {cs_count} rows but system_state says 0 lifetime cycles")

    # Check: multiple DB files
    db_dir = os.path.dirname(db_path)
    db_files = [f for f in os.listdir(db_dir) if f.endswith(".db")] if os.path.isdir(db_dir) else []
    if len(db_files) > 1:
        warnings.append(f"Multiple DB files in data dir: {db_files}")

    # Continuity health score
    critical_issues = sum(1 for w in warnings if "EMPTY" in w or "does not exist" in w)
    data_issues = sum(1 for w in warnings if "says 0" in w)
    if critical_issues > 0:
        health = "broken"
    elif data_issues > 0:
        health = "warning"
    elif len(warnings) > 0:
        health = "degraded"
    else:
        health = "good"

    # Rehydration status (v7.7.0)
    rh_status = "unknown"
    rh_sources = []
    rh_at = None
    try:
        import lifetime_rehydration_engine
        rh = lifetime_rehydration_engine.get_rehydration_summary()
        rh_status = rh.get("rehydration_status", "unknown")
        rh_sources = rh.get("sources_used", [])
        rh_at = rh.get("rehydrated_at")
    except Exception:
        pass

    # Identity rehydration (v7.7.1)
    id_rh_status = "unknown"
    id_rh_depth = 0.0
    id_rh_maturity = "unknown"
    id_rh_confidence = 0
    id_rh_continuity = 0.0
    try:
        import identity_rehydration_engine
        ident = identity_rehydration_engine.get_identity()
        id_rh_status = ident.get("rehydration_status", "unknown")
        id_rh_depth = ident.get("identity_depth", 0.0)
        id_rh_maturity = ident.get("maturity_level", {}).get("level", "unknown")
        id_rh_confidence = ident.get("confidence_state", {}).get("score", 0)
        id_rh_continuity = ident.get("continuity_score", 0.0)
    except Exception:
        pass

    # Capital summary (v7.7.0)
    cap_summary = db.get_capital_summary() or {}
    refill_count = cap_summary.get("total_events", 0) or 0

    # Last version transition
    last_transition = None
    for s in reversed(all_sessions):
        if s.get("notes") and "upgrade" in (s.get("notes") or "").lower():
            last_transition = s.get("notes")
            break

    return {
        "db_path": db_path,
        "db_exists": db_exists,
        "db_size_bytes": db_size,
        "db_size_kb": round(db_size / 1024, 1),
        "db_last_modified": db_modified,
        "table_counts": table_counts,
        "current_version": APP_VERSION,
        "current_session_id": _current_session_id,
        "active_session_version": active.get("app_version") if active else None,
        "lifetime_sessions": len(all_sessions),
        "lifetime_trades": actual_trades,
        "lifetime_cycles": sys_cycles,
        "identity_trades": id_trades,
        "identity_cycles": identity.get("total_cycles", 0) or 0,
        "identity_sessions": identity.get("total_sessions", 0) or 0,
        "portfolio_equity": lt_portfolio.get("total_equity", 0) or 0,
        "portfolio_cash": lt_portfolio.get("cash", 0) or 0,
        "portfolio_refills": lt_portfolio.get("total_refills", 0) or 0,
        "continuity_health": health,
        "warnings": warnings,
        "warning_count": len(warnings),
        # v7.7.0 rehydration fields
        "rehydration_status": rh_status,
        "rehydration_sources": rh_sources,
        "rehydrated_at": rh_at,
        "capital_events_count": refill_count,
        "last_version_transition": last_transition,
        # v7.7.1 identity rehydration fields
        "identity_rehydration_status": id_rh_status,
        "identity_depth": id_rh_depth,
        "identity_maturity": id_rh_maturity,
        "identity_confidence": id_rh_confidence,
        "identity_continuity": id_rh_continuity,
    }
