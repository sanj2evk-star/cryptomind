"""
db.py — CryptoMind v7 Persistence Layer.

SQLite-backed database for persistent state, trade history, experience memory,
behavior profiles, and daily reviews.  Structured so Postgres can be swapped
in later with minimal friction (all queries go through helper functions).

Tables:
    1) system_state        — singleton brain state
    2) version_sessions    — one row per app-version run
    3) trade_ledger        — append-only executed trades
    4) cycle_snapshots     — periodic brain snapshots
    5) strategy_state      — per-strategy persistent state
    6) experience_memory   — condensed lessons learned
    7) daily_reviews       — end-of-day reflections
    8) adaptation_events   — every behavior adaptation
    9) behavior_profile    — learned personality parameters
   10) news_events         — scaffolded for v8 news/context brain
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager

from config import DATA_DIR

# ---------------------------------------------------------------------------
# Database location
# ---------------------------------------------------------------------------

DB_PATH = DATA_DIR / "cryptomind.db"

# Thread-local connections (SQLite is not thread-safe by default)
_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    """Get or create a thread-local SQLite connection."""
    if not hasattr(_local, "conn") or _local.conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(str(DB_PATH), timeout=10)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


@contextmanager
def get_db():
    """Context manager yielding a SQLite connection with auto-commit."""
    conn = _get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def dict_from_row(row) -> dict | None:
    """Convert a sqlite3.Row to a plain dict."""
    if row is None:
        return None
    return dict(row)


def rows_to_dicts(rows) -> list[dict]:
    """Convert a list of sqlite3.Row to list of dicts."""
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Schema — all 10 tables
# ---------------------------------------------------------------------------

_SCHEMA = """
-- 1) system_state: singleton brain state
CREATE TABLE IF NOT EXISTS system_state (
    id                      INTEGER PRIMARY KEY CHECK (id = 1),
    current_session_id      INTEGER,
    current_version         TEXT NOT NULL DEFAULT '7.0.0',
    system_age_cycles       INTEGER NOT NULL DEFAULT 0,
    system_age_hours        REAL NOT NULL DEFAULT 0.0,
    total_lifetime_cycles   INTEGER NOT NULL DEFAULT 0,
    total_lifetime_trades   INTEGER NOT NULL DEFAULT 0,
    last_cycle_number       INTEGER NOT NULL DEFAULT 0,
    current_regime          TEXT NOT NULL DEFAULT 'SLEEPING',
    current_dominant_strategy TEXT NOT NULL DEFAULT 'HUNTER',
    current_market_quality  INTEGER NOT NULL DEFAULT 0,
    last_adaptation_at      TEXT,
    last_daily_review_at    TEXT,
    started_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL
);

-- 2) version_sessions: one row per app-version run
CREATE TABLE IF NOT EXISTS version_sessions (
    session_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    app_version             TEXT NOT NULL,
    started_at              TEXT NOT NULL,
    closed_at               TEXT,
    is_active               INTEGER NOT NULL DEFAULT 1,
    start_equity            REAL NOT NULL DEFAULT 100.0,
    end_equity              REAL,
    total_cycles            INTEGER NOT NULL DEFAULT 0,
    total_trades            INTEGER NOT NULL DEFAULT 0,
    total_buys              INTEGER NOT NULL DEFAULT 0,
    total_sells             INTEGER NOT NULL DEFAULT 0,
    realized_pnl            REAL NOT NULL DEFAULT 0.0,
    unrealized_pnl_at_close REAL,
    notes                   TEXT
);

-- 3) trade_ledger: append-only executed trades
CREATE TABLE IF NOT EXISTS trade_ledger (
    trade_id                INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id              INTEGER NOT NULL,
    timestamp               TEXT NOT NULL,
    action                  TEXT NOT NULL,
    price                   REAL NOT NULL,
    qty                     REAL NOT NULL DEFAULT 0.0,
    dollar_size             REAL NOT NULL DEFAULT 0.0,
    pnl                     REAL NOT NULL DEFAULT 0.0,
    strategy                TEXT NOT NULL DEFAULT '',
    regime                  TEXT NOT NULL DEFAULT '',
    entry_type              TEXT NOT NULL DEFAULT 'full',
    score                   REAL NOT NULL DEFAULT 0.0,
    confidence              REAL NOT NULL DEFAULT 0.0,
    reason                  TEXT NOT NULL DEFAULT '',
    hold_zone_adj           REAL NOT NULL DEFAULT 0.0,
    exposure_pct_after      REAL NOT NULL DEFAULT 0.0,
    market_quality_score    INTEGER NOT NULL DEFAULT 0,
    news_context_id         INTEGER,
    version_tag             TEXT NOT NULL DEFAULT '7.0.0',
    FOREIGN KEY (session_id) REFERENCES version_sessions(session_id)
);

-- 4) cycle_snapshots: periodic brain snapshots
CREATE TABLE IF NOT EXISTS cycle_snapshots (
    snapshot_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id              INTEGER NOT NULL,
    cycle_number            INTEGER NOT NULL,
    timestamp               TEXT NOT NULL,
    price                   REAL NOT NULL,
    rsi                     REAL,
    ema_short               REAL,
    ema_long                REAL,
    accel                   REAL,
    volatility              REAL,
    trend                   TEXT,
    regime                  TEXT,
    decision_action         TEXT,
    decision_score          REAL,
    decision_confidence     REAL,
    exposure_pct            REAL,
    holdings_btc            REAL,
    cash                    REAL,
    equity                  REAL,
    dominant_strategy       TEXT,
    market_quality_score    INTEGER,
    blocked_trade_reason    TEXT,
    short_summary           TEXT,
    FOREIGN KEY (session_id) REFERENCES version_sessions(session_id)
);

-- 5) strategy_state: per-strategy persistent state
CREATE TABLE IF NOT EXISTS strategy_state (
    strategy_name           TEXT NOT NULL,
    session_id              INTEGER NOT NULL,
    trades                  INTEGER NOT NULL DEFAULT 0,
    wins                    INTEGER NOT NULL DEFAULT 0,
    losses                  INTEGER NOT NULL DEFAULT 0,
    return_pct              REAL NOT NULL DEFAULT 0.0,
    pnl                     REAL NOT NULL DEFAULT 0.0,
    trust_score             REAL NOT NULL DEFAULT 0.5,
    alloc_pct               REAL NOT NULL DEFAULT 0.0,
    status                  TEXT NOT NULL DEFAULT 'ACTIVE',
    cooldown_remaining      INTEGER NOT NULL DEFAULT 0,
    probation_state         TEXT,
    last_entry_at           TEXT,
    last_exit_at            TEXT,
    consecutive_losses      INTEGER NOT NULL DEFAULT 0,
    drawdown_pct            REAL NOT NULL DEFAULT 0.0,
    last_reason             TEXT,
    PRIMARY KEY (strategy_name, session_id),
    FOREIGN KEY (session_id) REFERENCES version_sessions(session_id)
);

-- 6) experience_memory: condensed lessons learned
CREATE TABLE IF NOT EXISTS experience_memory (
    memory_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id              INTEGER NOT NULL,
    timestamp               TEXT NOT NULL,
    memory_type             TEXT NOT NULL,
    regime                  TEXT,
    strategy                TEXT,
    pattern_signature       TEXT,
    lesson_text             TEXT NOT NULL,
    confidence_weight       REAL NOT NULL DEFAULT 0.5,
    times_observed          INTEGER NOT NULL DEFAULT 1,
    average_outcome         REAL NOT NULL DEFAULT 0.0,
    active_flag             INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (session_id) REFERENCES version_sessions(session_id)
);

-- 7) daily_reviews: end-of-day reflections
CREATE TABLE IF NOT EXISTS daily_reviews (
    review_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id              INTEGER NOT NULL,
    review_date             TEXT NOT NULL,
    generated_at            TEXT NOT NULL,
    trades_count            INTEGER NOT NULL DEFAULT 0,
    winning_trades          INTEGER NOT NULL DEFAULT 0,
    losing_trades           INTEGER NOT NULL DEFAULT 0,
    net_pnl                 REAL NOT NULL DEFAULT 0.0,
    best_strategy           TEXT,
    worst_strategy          TEXT,
    best_pattern            TEXT,
    failed_pattern          TEXT,
    what_worked             TEXT,
    what_failed             TEXT,
    behavior_observation    TEXT,
    market_observation      TEXT,
    next_day_bias           TEXT,
    confidence              REAL NOT NULL DEFAULT 0.5,
    FOREIGN KEY (session_id) REFERENCES version_sessions(session_id)
);

-- 8) adaptation_events: every behavior adaptation
CREATE TABLE IF NOT EXISTS adaptation_events (
    adaptation_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id              INTEGER NOT NULL,
    timestamp               TEXT NOT NULL,
    trigger_type            TEXT NOT NULL,
    old_behavior            TEXT,
    new_behavior            TEXT,
    reason                  TEXT NOT NULL,
    expected_effect         TEXT,
    validation_status       TEXT NOT NULL DEFAULT 'pending',
    validation_notes        TEXT,
    FOREIGN KEY (session_id) REFERENCES version_sessions(session_id)
);

-- 9) behavior_profile: learned personality parameters
CREATE TABLE IF NOT EXISTS behavior_profile (
    profile_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id              INTEGER NOT NULL,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL,
    aggressiveness          REAL NOT NULL DEFAULT 0.5,
    patience                REAL NOT NULL DEFAULT 0.5,
    probe_bias              REAL NOT NULL DEFAULT 0.5,
    trend_follow_bias       REAL NOT NULL DEFAULT 0.5,
    mean_revert_bias        REAL NOT NULL DEFAULT 0.5,
    conviction_threshold    REAL NOT NULL DEFAULT 0.5,
    overtrade_penalty       REAL NOT NULL DEFAULT 0.5,
    hold_extension_bias     REAL NOT NULL DEFAULT 0.5,
    exit_tightness          REAL NOT NULL DEFAULT 0.5,
    noise_tolerance         REAL NOT NULL DEFAULT 0.5,
    notes                   TEXT,
    FOREIGN KEY (session_id) REFERENCES version_sessions(session_id)
);

-- 10) news_events: scaffolded for v8 news/context brain
CREATE TABLE IF NOT EXISTS news_events (
    news_id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp               TEXT NOT NULL,
    headline                TEXT NOT NULL,
    source                  TEXT,
    event_type              TEXT,
    impact_bias             TEXT,
    impact_strength         REAL,
    confidence              REAL,
    half_life               REAL,
    market_scope            TEXT,
    volatility_warning      INTEGER NOT NULL DEFAULT 0,
    system_verdict          TEXT,
    actual_outcome          TEXT,
    learning_status         TEXT NOT NULL DEFAULT 'pending'
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_trade_ledger_session ON trade_ledger(session_id);
CREATE INDEX IF NOT EXISTS idx_trade_ledger_timestamp ON trade_ledger(timestamp);
CREATE INDEX IF NOT EXISTS idx_trade_ledger_action ON trade_ledger(action);
CREATE INDEX IF NOT EXISTS idx_trade_ledger_strategy ON trade_ledger(strategy);
CREATE INDEX IF NOT EXISTS idx_cycle_snapshots_session ON cycle_snapshots(session_id);
CREATE INDEX IF NOT EXISTS idx_cycle_snapshots_cycle ON cycle_snapshots(cycle_number);
CREATE INDEX IF NOT EXISTS idx_experience_memory_type ON experience_memory(memory_type);
CREATE INDEX IF NOT EXISTS idx_experience_memory_active ON experience_memory(active_flag);
CREATE INDEX IF NOT EXISTS idx_daily_reviews_date ON daily_reviews(review_date);
CREATE INDEX IF NOT EXISTS idx_adaptation_events_session ON adaptation_events(session_id);
"""


def init_db():
    """Create all tables if they don't exist. Safe to call multiple times."""
    with get_db() as conn:
        conn.executescript(_SCHEMA)
    print(f"[db] Initialized database at {DB_PATH}")


# ---------------------------------------------------------------------------
# system_state helpers
# ---------------------------------------------------------------------------

def get_system_state() -> dict | None:
    """Get the singleton system state row."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM system_state WHERE id = 1").fetchone()
        return dict_from_row(row)


def upsert_system_state(**kwargs) -> None:
    """Update system state. Creates row if not exists."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        existing = conn.execute("SELECT id FROM system_state WHERE id = 1").fetchone()
        if existing:
            sets = ", ".join(f"{k} = ?" for k in kwargs)
            vals = list(kwargs.values())
            conn.execute(f"UPDATE system_state SET {sets}, updated_at = ? WHERE id = 1",
                         vals + [now])
        else:
            kwargs.setdefault("started_at", now)
            kwargs["updated_at"] = now
            kwargs["id"] = 1
            cols = ", ".join(kwargs.keys())
            placeholders = ", ".join("?" for _ in kwargs)
            conn.execute(f"INSERT INTO system_state ({cols}) VALUES ({placeholders})",
                         list(kwargs.values()))


def increment_system_counters(cycles: int = 0, trades: int = 0) -> None:
    """Atomically increment lifetime counters."""
    with get_db() as conn:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("""
            UPDATE system_state SET
                system_age_cycles = system_age_cycles + ?,
                total_lifetime_cycles = total_lifetime_cycles + ?,
                total_lifetime_trades = total_lifetime_trades + ?,
                updated_at = ?
            WHERE id = 1
        """, (cycles, cycles, trades, now))


# ---------------------------------------------------------------------------
# version_sessions helpers
# ---------------------------------------------------------------------------

def get_active_session(version: str = None) -> dict | None:
    """Get the active session, optionally filtered by version."""
    with get_db() as conn:
        if version:
            row = conn.execute(
                "SELECT * FROM version_sessions WHERE is_active = 1 AND app_version = ?",
                (version,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM version_sessions WHERE is_active = 1 ORDER BY session_id DESC LIMIT 1"
            ).fetchone()
        return dict_from_row(row)


def create_session(version: str, start_equity: float = 100.0) -> int:
    """Create a new version session. Returns session_id."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO version_sessions (app_version, started_at, is_active, start_equity) VALUES (?, ?, 1, ?)",
            (version, now, start_equity)
        )
        return cursor.lastrowid


def close_session(session_id: int, end_equity: float = None,
                  unrealized_pnl: float = None, notes: str = None) -> None:
    """Close a version session."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute("""
            UPDATE version_sessions SET
                is_active = 0, closed_at = ?,
                end_equity = COALESCE(?, end_equity),
                unrealized_pnl_at_close = COALESCE(?, unrealized_pnl_at_close),
                notes = COALESCE(?, notes)
            WHERE session_id = ?
        """, (now, end_equity, unrealized_pnl, notes, session_id))


def close_all_active_sessions() -> int:
    """Close all active sessions. Returns count closed."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        cursor = conn.execute(
            "UPDATE version_sessions SET is_active = 0, closed_at = ? WHERE is_active = 1",
            (now,)
        )
        return cursor.rowcount


def get_all_sessions() -> list[dict]:
    """Get all sessions ordered by start time."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM version_sessions ORDER BY started_at DESC"
        ).fetchall()
        return rows_to_dicts(rows)


def update_session_stats(session_id: int, **kwargs) -> None:
    """Update session stats (cycles, trades, pnl, etc.)."""
    with get_db() as conn:
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values())
        conn.execute(f"UPDATE version_sessions SET {sets} WHERE session_id = ?",
                     vals + [session_id])


# ---------------------------------------------------------------------------
# trade_ledger helpers
# ---------------------------------------------------------------------------

def insert_trade(session_id: int, **trade_data) -> int:
    """Insert a trade into the append-only ledger. Returns trade_id."""
    trade_data["session_id"] = session_id
    trade_data.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    with get_db() as conn:
        cols = ", ".join(trade_data.keys())
        placeholders = ", ".join("?" for _ in trade_data)
        cursor = conn.execute(
            f"INSERT INTO trade_ledger ({cols}) VALUES ({placeholders})",
            list(trade_data.values())
        )
        return cursor.lastrowid


def get_trades(session_id: int = None, limit: int = 50, offset: int = 0,
               action: str = None, strategy: str = None, regime: str = None,
               entry_type: str = None) -> tuple[list[dict], int]:
    """Get trades with optional filters. Returns (trades, total_count)."""
    with get_db() as conn:
        where_parts = []
        params = []
        if session_id:
            where_parts.append("session_id = ?")
            params.append(session_id)
        if action:
            where_parts.append("action = ?")
            params.append(action.upper())
        if strategy:
            where_parts.append("strategy LIKE ?")
            params.append(f"%{strategy}%")
        if regime:
            where_parts.append("regime LIKE ?")
            params.append(f"%{regime}%")
        if entry_type:
            where_parts.append("entry_type LIKE ?")
            params.append(f"%{entry_type}%")

        where = " WHERE " + " AND ".join(where_parts) if where_parts else ""

        # Total count
        total = conn.execute(f"SELECT COUNT(*) FROM trade_ledger{where}", params).fetchone()[0]

        # Paginated results (newest first)
        rows = conn.execute(
            f"SELECT * FROM trade_ledger{where} ORDER BY trade_id DESC LIMIT ? OFFSET ?",
            params + [limit, offset]
        ).fetchall()

        return rows_to_dicts(rows), total


def get_trade_summary(session_id: int = None) -> dict:
    """Get trade summary stats for a session or all time."""
    with get_db() as conn:
        where = "WHERE session_id = ?" if session_id else ""
        params = [session_id] if session_id else []

        row = conn.execute(f"""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN action = 'BUY' THEN 1 ELSE 0 END) as buys,
                SUM(CASE WHEN action = 'SELL' THEN 1 ELSE 0 END) as sells,
                SUM(CASE WHEN action = 'SELL' AND pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN action = 'SELL' AND pnl < 0 THEN 1 ELSE 0 END) as losses,
                SUM(pnl) as net_pnl,
                MAX(pnl) as best_trade,
                MIN(CASE WHEN action = 'SELL' THEN pnl END) as worst_trade
            FROM trade_ledger {where}
        """, params).fetchone()

        result = dict_from_row(row) if row else {}
        total_decided = (result.get("wins") or 0) + (result.get("losses") or 0)
        result["win_rate"] = round((result.get("wins") or 0) / total_decided * 100, 1) if total_decided > 0 else 0
        return result


# ---------------------------------------------------------------------------
# cycle_snapshots helpers
# ---------------------------------------------------------------------------

def insert_cycle_snapshot(session_id: int, **snapshot_data) -> int:
    """Insert a cycle snapshot."""
    snapshot_data["session_id"] = session_id
    snapshot_data.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    with get_db() as conn:
        cols = ", ".join(snapshot_data.keys())
        placeholders = ", ".join("?" for _ in snapshot_data)
        cursor = conn.execute(
            f"INSERT INTO cycle_snapshots ({cols}) VALUES ({placeholders})",
            list(snapshot_data.values())
        )
        return cursor.lastrowid


def get_recent_snapshots(session_id: int, limit: int = 50) -> list[dict]:
    """Get recent cycle snapshots."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM cycle_snapshots WHERE session_id = ? ORDER BY snapshot_id DESC LIMIT ?",
            (session_id, limit)
        ).fetchall()
        return rows_to_dicts(rows)


# ---------------------------------------------------------------------------
# strategy_state helpers
# ---------------------------------------------------------------------------

def upsert_strategy_state(strategy_name: str, session_id: int, **kwargs) -> None:
    """Update or insert strategy state."""
    with get_db() as conn:
        existing = conn.execute(
            "SELECT strategy_name FROM strategy_state WHERE strategy_name = ? AND session_id = ?",
            (strategy_name, session_id)
        ).fetchone()
        if existing:
            sets = ", ".join(f"{k} = ?" for k in kwargs)
            vals = list(kwargs.values())
            conn.execute(
                f"UPDATE strategy_state SET {sets} WHERE strategy_name = ? AND session_id = ?",
                vals + [strategy_name, session_id]
            )
        else:
            kwargs["strategy_name"] = strategy_name
            kwargs["session_id"] = session_id
            cols = ", ".join(kwargs.keys())
            placeholders = ", ".join("?" for _ in kwargs)
            conn.execute(
                f"INSERT INTO strategy_state ({cols}) VALUES ({placeholders})",
                list(kwargs.values())
            )


def get_strategy_states(session_id: int) -> list[dict]:
    """Get all strategy states for a session."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM strategy_state WHERE session_id = ?", (session_id,)
        ).fetchall()
        return rows_to_dicts(rows)


# ---------------------------------------------------------------------------
# experience_memory helpers
# ---------------------------------------------------------------------------

def insert_memory(session_id: int, memory_type: str, lesson_text: str,
                  regime: str = None, strategy: str = None,
                  pattern_signature: str = None, confidence_weight: float = 0.5,
                  average_outcome: float = 0.0) -> int:
    """Insert a new experience memory. Returns memory_id."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        # Check if similar memory exists (same type + pattern + strategy)
        existing = conn.execute(
            """SELECT memory_id, times_observed, average_outcome FROM experience_memory
               WHERE memory_type = ? AND pattern_signature = ? AND strategy = ?
               AND active_flag = 1""",
            (memory_type, pattern_signature or "", strategy or "")
        ).fetchone()

        if existing:
            # Reinforce existing memory
            new_count = existing["times_observed"] + 1
            new_avg = (existing["average_outcome"] * existing["times_observed"] + average_outcome) / new_count
            conn.execute(
                """UPDATE experience_memory SET
                    times_observed = ?, average_outcome = ?, timestamp = ?,
                    confidence_weight = MIN(1.0, confidence_weight + 0.05)
                   WHERE memory_id = ?""",
                (new_count, round(new_avg, 6), now, existing["memory_id"])
            )
            return existing["memory_id"]
        else:
            cursor = conn.execute(
                """INSERT INTO experience_memory
                   (session_id, timestamp, memory_type, regime, strategy,
                    pattern_signature, lesson_text, confidence_weight,
                    times_observed, average_outcome, active_flag)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 1)""",
                (session_id, now, memory_type, regime, strategy,
                 pattern_signature, lesson_text, confidence_weight, average_outcome)
            )
            return cursor.lastrowid


def get_active_memories(session_id: int = None, memory_type: str = None,
                        strategy: str = None, limit: int = 50) -> list[dict]:
    """Get active experience memories."""
    with get_db() as conn:
        where_parts = ["active_flag = 1"]
        params = []
        if session_id:
            where_parts.append("session_id = ?")
            params.append(session_id)
        if memory_type:
            where_parts.append("memory_type = ?")
            params.append(memory_type)
        if strategy:
            where_parts.append("strategy = ?")
            params.append(strategy)

        where = " WHERE " + " AND ".join(where_parts)
        rows = conn.execute(
            f"SELECT * FROM experience_memory{where} ORDER BY times_observed DESC, memory_id DESC LIMIT ?",
            params + [limit]
        ).fetchall()
        return rows_to_dicts(rows)


def get_memory_count() -> int:
    """Count of active memories."""
    with get_db() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM experience_memory WHERE active_flag = 1"
        ).fetchone()[0]


def get_memories_for_pattern(pattern_signature: str) -> list[dict]:
    """Get all memories matching a pattern."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM experience_memory WHERE pattern_signature = ? AND active_flag = 1",
            (pattern_signature,)
        ).fetchall()
        return rows_to_dicts(rows)


# ---------------------------------------------------------------------------
# daily_reviews helpers
# ---------------------------------------------------------------------------

def insert_daily_review(session_id: int, **review_data) -> int:
    """Insert a daily review. Returns review_id."""
    review_data["session_id"] = session_id
    review_data.setdefault("generated_at", datetime.now(timezone.utc).isoformat())
    with get_db() as conn:
        cols = ", ".join(review_data.keys())
        placeholders = ", ".join("?" for _ in review_data)
        cursor = conn.execute(
            f"INSERT INTO daily_reviews ({cols}) VALUES ({placeholders})",
            list(review_data.values())
        )
        return cursor.lastrowid


def get_daily_reviews(session_id: int = None, limit: int = 10) -> list[dict]:
    """Get daily reviews, newest first."""
    with get_db() as conn:
        if session_id:
            rows = conn.execute(
                "SELECT * FROM daily_reviews WHERE session_id = ? ORDER BY review_id DESC LIMIT ?",
                (session_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM daily_reviews ORDER BY review_id DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return rows_to_dicts(rows)


def get_latest_review() -> dict | None:
    """Get the most recent daily review."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM daily_reviews ORDER BY review_id DESC LIMIT 1"
        ).fetchone()
        return dict_from_row(row)


# ---------------------------------------------------------------------------
# adaptation_events helpers
# ---------------------------------------------------------------------------

def insert_adaptation(session_id: int, trigger_type: str, reason: str,
                      old_behavior: str = None, new_behavior: str = None,
                      expected_effect: str = None) -> int:
    """Log an adaptation event. Returns adaptation_id."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO adaptation_events
               (session_id, timestamp, trigger_type, old_behavior, new_behavior,
                reason, expected_effect, validation_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')""",
            (session_id, now, trigger_type, old_behavior, new_behavior,
             reason, expected_effect)
        )
        return cursor.lastrowid


def get_recent_adaptations(session_id: int = None, limit: int = 20) -> list[dict]:
    """Get recent adaptation events."""
    with get_db() as conn:
        if session_id:
            rows = conn.execute(
                "SELECT * FROM adaptation_events WHERE session_id = ? ORDER BY adaptation_id DESC LIMIT ?",
                (session_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM adaptation_events ORDER BY adaptation_id DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return rows_to_dicts(rows)


def validate_adaptation(adaptation_id: int, status: str, notes: str = None) -> None:
    """Mark an adaptation as helpful/harmful/inconclusive."""
    with get_db() as conn:
        conn.execute(
            "UPDATE adaptation_events SET validation_status = ?, validation_notes = ? WHERE adaptation_id = ?",
            (status, notes, adaptation_id)
        )


# ---------------------------------------------------------------------------
# behavior_profile helpers
# ---------------------------------------------------------------------------

def get_active_profile(session_id: int) -> dict | None:
    """Get the latest behavior profile for a session."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM behavior_profile WHERE session_id = ? ORDER BY profile_id DESC LIMIT 1",
            (session_id,)
        ).fetchone()
        return dict_from_row(row)


def upsert_behavior_profile(session_id: int, **params) -> int:
    """Update or create behavior profile."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        existing = conn.execute(
            "SELECT profile_id FROM behavior_profile WHERE session_id = ? ORDER BY profile_id DESC LIMIT 1",
            (session_id,)
        ).fetchone()

        if existing:
            sets = ", ".join(f"{k} = ?" for k in params)
            vals = list(params.values())
            conn.execute(
                f"UPDATE behavior_profile SET {sets}, updated_at = ? WHERE profile_id = ?",
                vals + [now, existing["profile_id"]]
            )
            return existing["profile_id"]
        else:
            params["session_id"] = session_id
            params["created_at"] = now
            params["updated_at"] = now
            cols = ", ".join(params.keys())
            placeholders = ", ".join("?" for _ in params)
            cursor = conn.execute(
                f"INSERT INTO behavior_profile ({cols}) VALUES ({placeholders})",
                list(params.values())
            )
            return cursor.lastrowid


# ---------------------------------------------------------------------------
# Migration: CSV → SQLite
# ---------------------------------------------------------------------------

def migrate_csv_trades(csv_path: Path, session_id: int, version_tag: str = "pre-v7") -> int:
    """Migrate existing auto_trades.csv into trade_ledger. Returns count migrated."""
    import csv as csv_mod
    if not csv_path.exists():
        return 0

    with open(csv_path, newline="") as f:
        reader = csv_mod.DictReader(f)
        rows = list(reader)

    if not rows:
        return 0

    count = 0
    with get_db() as conn:
        for row in rows:
            action = row.get("action", "HOLD")
            if action not in ("BUY", "SELL"):
                continue
            try:
                conn.execute(
                    """INSERT INTO trade_ledger
                       (session_id, timestamp, action, price, qty, dollar_size, pnl,
                        strategy, regime, entry_type, score, confidence, reason,
                        version_tag)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        session_id,
                        row.get("timestamp", ""),
                        action,
                        float(row.get("price", 0)),
                        float(row.get("quantity", 0)),
                        float(row.get("dollar_size", 0)),
                        float(row.get("pnl", 0)),
                        row.get("strategy", ""),
                        row.get("regime", ""),
                        row.get("entry_type", "full"),
                        float(row.get("score", 0)),
                        float(row.get("confidence", 0)),
                        row.get("reason", ""),
                        version_tag,
                    )
                )
                count += 1
            except Exception as e:
                print(f"[db] Skip CSV row: {e}")
                continue

    print(f"[db] Migrated {count} trades from CSV to SQLite")
    return count
