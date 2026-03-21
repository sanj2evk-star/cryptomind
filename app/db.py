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
    version_tag             TEXT NOT NULL DEFAULT '7.1.0',
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

-- 8b) adaptation_journal: v7.2 full audit trail (extends adaptation_events)
CREATE TABLE IF NOT EXISTS adaptation_journal (
    journal_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id              INTEGER NOT NULL,
    timestamp               TEXT NOT NULL,
    category                TEXT NOT NULL DEFAULT '',
    target                  TEXT NOT NULL DEFAULT '',
    old_value               REAL NOT NULL DEFAULT 0.0,
    new_value               REAL NOT NULL DEFAULT 0.0,
    delta                   REAL NOT NULL DEFAULT 0.0,
    evidence_count          INTEGER NOT NULL DEFAULT 0,
    outcome_count           INTEGER NOT NULL DEFAULT 0,
    weighted_sample_size    REAL NOT NULL DEFAULT 0.0,
    trigger_reason          TEXT NOT NULL DEFAULT '',
    allowed_or_blocked      TEXT NOT NULL DEFAULT 'blocked',
    blocked_reason          TEXT,
    reversal_candidate      INTEGER NOT NULL DEFAULT 0,
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

-- 11) experience_outcomes: delayed outcome evaluation at +5, +20, +100 cycles (v7.1)
CREATE TABLE IF NOT EXISTS experience_outcomes (
    outcome_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          INTEGER NOT NULL,
    trade_id            INTEGER NOT NULL,
    created_at          TEXT NOT NULL,
    action              TEXT NOT NULL,
    entry_price         REAL NOT NULL,
    entry_cycle         INTEGER NOT NULL,
    strategy            TEXT NOT NULL DEFAULT '',
    regime              TEXT NOT NULL DEFAULT '',
    entry_type          TEXT NOT NULL DEFAULT 'full',
    entry_score         REAL NOT NULL DEFAULT 0.0,
    entry_confidence    REAL NOT NULL DEFAULT 0.0,
    pattern_signature   TEXT NOT NULL DEFAULT '',
    -- checkpoint: +5 cycles
    price_at_5          REAL,
    pnl_pct_at_5        REAL,
    mfe_at_5            REAL,
    mae_at_5            REAL,
    evaluated_at_5      TEXT,
    verdict_at_5        TEXT,
    -- checkpoint: +20 cycles
    price_at_20         REAL,
    pnl_pct_at_20       REAL,
    mfe_at_20           REAL,
    mae_at_20           REAL,
    evaluated_at_20     TEXT,
    verdict_at_20       TEXT,
    -- checkpoint: +100 cycles
    price_at_100        REAL,
    pnl_pct_at_100      REAL,
    mfe_at_100          REAL,
    mae_at_100          REAL,
    evaluated_at_100    TEXT,
    verdict_at_100      TEXT,
    -- final summary
    final_verdict       TEXT,
    lesson_generated    INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (session_id) REFERENCES version_sessions(session_id)
);

-- 12) missed_opportunities: trades the system avoided but shouldn't have (v7.1)
CREATE TABLE IF NOT EXISTS missed_opportunities (
    missed_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          INTEGER NOT NULL,
    recorded_at         TEXT NOT NULL,
    cycle_recorded      INTEGER NOT NULL,
    price_at_record     REAL NOT NULL,
    score_at_record     REAL NOT NULL DEFAULT 0.0,
    regime              TEXT NOT NULL DEFAULT '',
    strategy            TEXT NOT NULL DEFAULT '',
    block_reason        TEXT NOT NULL DEFAULT '',
    -- evaluation at +5 cycles
    evaluated_5         INTEGER NOT NULL DEFAULT 0,
    price_at_5          REAL,
    move_pct_at_5       REAL,
    -- evaluation at +20 cycles
    evaluated_20        INTEGER NOT NULL DEFAULT 0,
    price_at_20         REAL,
    move_pct_at_20      REAL,
    -- classification
    was_missed          INTEGER NOT NULL DEFAULT 0,
    severity            TEXT,
    lesson_id           INTEGER,
    FOREIGN KEY (session_id) REFERENCES version_sessions(session_id)
);

-- 13) regime_profiles: strategy performance per regime (v7.1)
CREATE TABLE IF NOT EXISTS regime_profiles (
    profile_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          INTEGER NOT NULL,
    regime              TEXT NOT NULL,
    strategy            TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    total_trades        INTEGER NOT NULL DEFAULT 0,
    wins                INTEGER NOT NULL DEFAULT 0,
    losses              INTEGER NOT NULL DEFAULT 0,
    total_pnl           REAL NOT NULL DEFAULT 0.0,
    avg_pnl             REAL NOT NULL DEFAULT 0.0,
    win_rate            REAL NOT NULL DEFAULT 0.0,
    avg_hold_cycles     REAL NOT NULL DEFAULT 0.0,
    best_entry_type     TEXT,
    confidence_score    REAL NOT NULL DEFAULT 0.5,
    recommended_action  TEXT DEFAULT 'neutral',
    UNIQUE(session_id, regime, strategy),
    FOREIGN KEY (session_id) REFERENCES version_sessions(session_id)
);

-- 14) behavior_states: dynamic market_reward + system_self state (v7.1)
CREATE TABLE IF NOT EXISTS behavior_states (
    state_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          INTEGER NOT NULL,
    updated_at          TEXT NOT NULL,
    cycle_number        INTEGER NOT NULL DEFAULT 0,
    -- market reward state
    market_reward_state TEXT NOT NULL DEFAULT 'neutral',
    reward_score        REAL NOT NULL DEFAULT 0.0,
    reward_trend        TEXT NOT NULL DEFAULT 'flat',
    recent_win_rate     REAL NOT NULL DEFAULT 0.5,
    recent_avg_pnl      REAL NOT NULL DEFAULT 0.0,
    -- system self state
    system_self_state   TEXT NOT NULL DEFAULT 'learning',
    self_score          REAL NOT NULL DEFAULT 0.0,
    calibration_quality REAL NOT NULL DEFAULT 0.5,
    -- derived modifiers (bounded)
    aggression_modifier REAL NOT NULL DEFAULT 0.0,
    patience_modifier   REAL NOT NULL DEFAULT 0.0,
    threshold_modifier  REAL NOT NULL DEFAULT 0.0,
    exposure_modifier   REAL NOT NULL DEFAULT 0.0,
    notes               TEXT,
    FOREIGN KEY (session_id) REFERENCES version_sessions(session_id)
);

-- 15) daily_bias: structured next-day bias from daily review (v7.1)
CREATE TABLE IF NOT EXISTS daily_bias (
    bias_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          INTEGER NOT NULL,
    review_id           INTEGER,
    bias_date           TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    overall_stance      TEXT NOT NULL DEFAULT 'neutral',
    confidence_in_bias  REAL NOT NULL DEFAULT 0.5,
    -- per-regime bias
    sleeping_bias       TEXT NOT NULL DEFAULT 'normal',
    active_bias         TEXT NOT NULL DEFAULT 'normal',
    breakout_bias       TEXT NOT NULL DEFAULT 'normal',
    -- strategy preferences (JSON arrays)
    preferred_strategies TEXT,
    avoid_strategies     TEXT,
    -- threshold adjustments
    buy_threshold_adj   REAL NOT NULL DEFAULT 0.0,
    sell_threshold_adj  REAL NOT NULL DEFAULT 0.0,
    exposure_cap_adj    REAL NOT NULL DEFAULT 0.0,
    -- meta
    expires_at          TEXT,
    active              INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (session_id) REFERENCES version_sessions(session_id),
    FOREIGN KEY (review_id) REFERENCES daily_reviews(review_id)
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

-- v7.1 indexes
CREATE INDEX IF NOT EXISTS idx_experience_outcomes_trade ON experience_outcomes(trade_id);
CREATE INDEX IF NOT EXISTS idx_experience_outcomes_cycle ON experience_outcomes(entry_cycle);
CREATE INDEX IF NOT EXISTS idx_experience_outcomes_pending ON experience_outcomes(final_verdict);
CREATE INDEX IF NOT EXISTS idx_missed_opportunities_cycle ON missed_opportunities(cycle_recorded);
CREATE INDEX IF NOT EXISTS idx_missed_opportunities_pending ON missed_opportunities(evaluated_5, evaluated_20);
CREATE INDEX IF NOT EXISTS idx_regime_profiles_lookup ON regime_profiles(regime, strategy);
CREATE INDEX IF NOT EXISTS idx_behavior_states_session ON behavior_states(session_id);
CREATE INDEX IF NOT EXISTS idx_daily_bias_date ON daily_bias(bias_date);
CREATE INDEX IF NOT EXISTS idx_daily_bias_active ON daily_bias(active);
CREATE INDEX IF NOT EXISTS idx_adaptation_journal_session ON adaptation_journal(session_id);
CREATE INDEX IF NOT EXISTS idx_adaptation_journal_target ON adaptation_journal(target);
CREATE INDEX IF NOT EXISTS idx_adaptation_journal_status ON adaptation_journal(allowed_or_blocked);

-- 16) evolution_snapshots: periodic mind evolution score snapshots (v7.3)
CREATE TABLE IF NOT EXISTS evolution_snapshots (
    snapshot_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id              INTEGER NOT NULL,
    timestamp               TEXT NOT NULL,
    cycle_number            INTEGER NOT NULL DEFAULT 0,
    evolution_score         INTEGER NOT NULL DEFAULT 0,
    mind_level              TEXT NOT NULL DEFAULT 'Rookie',
    -- skill sub-scores (0-100)
    discipline_score        INTEGER NOT NULL DEFAULT 0,
    risk_control_score      INTEGER NOT NULL DEFAULT 0,
    timing_score            INTEGER NOT NULL DEFAULT 0,
    adaptation_score        INTEGER NOT NULL DEFAULT 0,
    regime_reading_score    INTEGER NOT NULL DEFAULT 0,
    opportunity_score       INTEGER NOT NULL DEFAULT 0,
    consistency_score       INTEGER NOT NULL DEFAULT 0,
    self_correction_score   INTEGER NOT NULL DEFAULT 0,
    patience_score          INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (session_id) REFERENCES version_sessions(session_id)
);

-- 17) milestones: significant system events (v7.3)
CREATE TABLE IF NOT EXISTS milestones (
    milestone_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id              INTEGER,
    timestamp               TEXT NOT NULL,
    milestone_type          TEXT NOT NULL DEFAULT 'achievement',
    title                   TEXT NOT NULL,
    description             TEXT,
    evolution_score_at      INTEGER NOT NULL DEFAULT 0,
    mind_level_at           TEXT NOT NULL DEFAULT 'Rookie',
    version_tag             TEXT,
    FOREIGN KEY (session_id) REFERENCES version_sessions(session_id)
);

-- v7.3 indexes
CREATE INDEX IF NOT EXISTS idx_evolution_snapshots_session ON evolution_snapshots(session_id);
CREATE INDEX IF NOT EXISTS idx_evolution_snapshots_cycle ON evolution_snapshots(cycle_number);
CREATE INDEX IF NOT EXISTS idx_milestones_session ON milestones(session_id);
CREATE INDEX IF NOT EXISTS idx_milestones_type ON milestones(milestone_type);
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


def insert_adaptation_v72(session_id: int, **kwargs) -> int:
    """Insert a v7.2 adaptation journal entry. Returns journal_id."""
    now = kwargs.pop("timestamp", datetime.now(timezone.utc).isoformat())
    kwargs["session_id"] = session_id
    kwargs["timestamp"] = now
    # Remove keys not in table
    allowed_keys = {
        "session_id", "timestamp", "category", "target", "old_value", "new_value",
        "delta", "evidence_count", "outcome_count", "weighted_sample_size",
        "trigger_reason", "allowed_or_blocked", "blocked_reason", "reversal_candidate",
    }
    filtered = {k: v for k, v in kwargs.items() if k in allowed_keys}
    if "reversal_candidate" in filtered and isinstance(filtered["reversal_candidate"], bool):
        filtered["reversal_candidate"] = 1 if filtered["reversal_candidate"] else 0
    with get_db() as conn:
        cols = ", ".join(filtered.keys())
        placeholders = ", ".join("?" for _ in filtered)
        cursor = conn.execute(
            f"INSERT INTO adaptation_journal ({cols}) VALUES ({placeholders})",
            list(filtered.values())
        )
        return cursor.lastrowid


def get_adaptation_journal(session_id: int = None, limit: int = 20,
                           status_filter: str = None) -> list[dict]:
    """Get adaptation journal entries."""
    with get_db() as conn:
        where_parts = []
        params = []
        if session_id:
            where_parts.append("session_id = ?")
            params.append(session_id)
        if status_filter:
            where_parts.append("allowed_or_blocked = ?")
            params.append(status_filter)
        where = " WHERE " + " AND ".join(where_parts) if where_parts else ""
        rows = conn.execute(
            f"SELECT * FROM adaptation_journal{where} ORDER BY journal_id DESC LIMIT ?",
            params + [limit]
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


# ---------------------------------------------------------------------------
# experience_outcomes helpers (v7.1)
# ---------------------------------------------------------------------------

def insert_experience_outcome(session_id: int, trade_id: int, action: str,
                               entry_price: float, entry_cycle: int,
                               strategy: str = "", regime: str = "",
                               entry_type: str = "full", entry_score: float = 0.0,
                               entry_confidence: float = 0.0,
                               pattern_signature: str = "") -> int:
    """Create a pending outcome record for delayed evaluation. Returns outcome_id."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO experience_outcomes
               (session_id, trade_id, created_at, action, entry_price, entry_cycle,
                strategy, regime, entry_type, entry_score, entry_confidence,
                pattern_signature)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, trade_id, now, action, entry_price, entry_cycle,
             strategy, regime, entry_type, entry_score, entry_confidence,
             pattern_signature)
        )
        return cursor.lastrowid


def get_pending_outcomes_at(checkpoint: int, current_cycle: int) -> list[dict]:
    """Get outcomes that need evaluation at a given checkpoint offset.

    checkpoint is 5, 20, or 100.
    Returns outcomes where entry_cycle + checkpoint <= current_cycle
    and the relevant checkpoint column is still NULL.
    """
    col_map = {5: "evaluated_at_5", 20: "evaluated_at_20", 100: "evaluated_at_100"}
    col = col_map.get(checkpoint)
    if not col:
        return []
    with get_db() as conn:
        rows = conn.execute(
            f"""SELECT * FROM experience_outcomes
                WHERE entry_cycle + ? <= ? AND {col} IS NULL
                ORDER BY entry_cycle ASC LIMIT 100""",
            (checkpoint, current_cycle)
        ).fetchall()
        return rows_to_dicts(rows)


def update_outcome_checkpoint(outcome_id: int, checkpoint: int,
                               price: float, pnl_pct: float,
                               mfe: float, mae: float,
                               verdict: str) -> None:
    """Update a specific checkpoint on an outcome record."""
    now = datetime.now(timezone.utc).isoformat()
    suffix = {5: "5", 20: "20", 100: "100"}.get(checkpoint)
    if not suffix:
        return
    with get_db() as conn:
        conn.execute(
            f"""UPDATE experience_outcomes SET
                price_at_{suffix} = ?, pnl_pct_at_{suffix} = ?,
                mfe_at_{suffix} = ?, mae_at_{suffix} = ?,
                evaluated_at_{suffix} = ?, verdict_at_{suffix} = ?
                WHERE outcome_id = ?""",
            (price, pnl_pct, mfe, mae, now, verdict, outcome_id)
        )


def set_outcome_final_verdict(outcome_id: int, verdict: str) -> None:
    """Set the final verdict after all checkpoints evaluated."""
    with get_db() as conn:
        conn.execute(
            "UPDATE experience_outcomes SET final_verdict = ? WHERE outcome_id = ?",
            (verdict, outcome_id)
        )


def mark_outcome_lesson_generated(outcome_id: int) -> None:
    """Mark that a lesson was generated from this outcome."""
    with get_db() as conn:
        conn.execute(
            "UPDATE experience_outcomes SET lesson_generated = 1 WHERE outcome_id = ?",
            (outcome_id,)
        )


def get_outcomes_needing_final_verdict() -> list[dict]:
    """Get outcomes where all 3 checkpoints are evaluated but no final verdict."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM experience_outcomes
               WHERE evaluated_at_5 IS NOT NULL
               AND evaluated_at_20 IS NOT NULL
               AND evaluated_at_100 IS NOT NULL
               AND final_verdict IS NULL
               LIMIT 50"""
        ).fetchall()
        return rows_to_dicts(rows)


def get_outcomes_needing_lessons() -> list[dict]:
    """Get outcomes with final verdict but no lesson yet."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM experience_outcomes
               WHERE final_verdict IS NOT NULL
               AND lesson_generated = 0
               LIMIT 50"""
        ).fetchall()
        return rows_to_dicts(rows)


def get_outcome_summary() -> dict:
    """Get outcome evaluation stats for API/UI."""
    with get_db() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN final_verdict IS NULL THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN final_verdict IS NOT NULL THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN final_verdict = 'correct' THEN 1 ELSE 0 END) as correct,
                SUM(CASE WHEN final_verdict = 'wrong' THEN 1 ELSE 0 END) as wrong,
                SUM(CASE WHEN final_verdict = 'neutral' THEN 1 ELSE 0 END) as neutral_v,
                AVG(CASE WHEN pnl_pct_at_5 IS NOT NULL THEN pnl_pct_at_5 END) as avg_5c,
                AVG(CASE WHEN pnl_pct_at_20 IS NOT NULL THEN pnl_pct_at_20 END) as avg_20c,
                AVG(CASE WHEN pnl_pct_at_100 IS NOT NULL THEN pnl_pct_at_100 END) as avg_100c
            FROM experience_outcomes
        """).fetchone()
        return dict_from_row(row) if row else {}


# ---------------------------------------------------------------------------
# missed_opportunities helpers (v7.1)
# ---------------------------------------------------------------------------

def insert_missed_opportunity(session_id: int, cycle_recorded: int,
                               price_at_record: float, score_at_record: float,
                               regime: str, strategy: str,
                               block_reason: str) -> int:
    """Insert a missed opportunity record. Returns missed_id."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO missed_opportunities
               (session_id, recorded_at, cycle_recorded, price_at_record,
                score_at_record, regime, strategy, block_reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, now, cycle_recorded, price_at_record,
             score_at_record, regime, strategy, block_reason)
        )
        return cursor.lastrowid


def get_pending_missed(checkpoint: int, current_cycle: int) -> list[dict]:
    """Get missed opportunities needing evaluation at a checkpoint.

    checkpoint: 5 or 20.
    """
    col = {5: "evaluated_5", 20: "evaluated_20"}.get(checkpoint)
    if not col:
        return []
    with get_db() as conn:
        rows = conn.execute(
            f"""SELECT * FROM missed_opportunities
                WHERE cycle_recorded + ? <= ? AND {col} = 0
                ORDER BY cycle_recorded ASC LIMIT 100""",
            (checkpoint, current_cycle)
        ).fetchall()
        return rows_to_dicts(rows)


def update_missed_evaluation(missed_id: int, checkpoint: int,
                              price: float, move_pct: float,
                              was_missed: bool = False,
                              severity: str = None) -> None:
    """Update evaluation for a missed opportunity at a checkpoint."""
    suffix = {5: "5", 20: "20"}.get(checkpoint)
    if not suffix:
        return
    with get_db() as conn:
        updates = [f"evaluated_{suffix} = 1", f"price_at_{suffix} = ?", f"move_pct_at_{suffix} = ?"]
        params = [price, move_pct]
        if was_missed:
            updates.append("was_missed = 1")
        if severity:
            updates.append("severity = ?")
            params.append(severity)
        params.append(missed_id)
        conn.execute(
            f"UPDATE missed_opportunities SET {', '.join(updates)} WHERE missed_id = ?",
            params
        )


def get_missed_opportunity_summary() -> dict:
    """Summary of missed opportunities for API/UI."""
    with get_db() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN was_missed = 1 THEN 1 ELSE 0 END) as confirmed_missed,
                SUM(CASE WHEN severity = 'minor' THEN 1 ELSE 0 END) as minor,
                SUM(CASE WHEN severity = 'moderate' THEN 1 ELSE 0 END) as moderate,
                SUM(CASE WHEN severity = 'major' THEN 1 ELSE 0 END) as major,
                AVG(CASE WHEN was_missed = 1 THEN move_pct_at_5 END) as avg_missed_move_5,
                AVG(CASE WHEN was_missed = 1 THEN move_pct_at_20 END) as avg_missed_move_20
            FROM missed_opportunities
        """).fetchone()
        result = dict_from_row(row) if row else {}

        # By strategy
        strat_rows = conn.execute("""
            SELECT strategy, COUNT(*) as cnt,
                   SUM(CASE WHEN was_missed = 1 THEN 1 ELSE 0 END) as missed
            FROM missed_opportunities
            GROUP BY strategy ORDER BY missed DESC LIMIT 10
        """).fetchall()
        result["by_strategy"] = rows_to_dicts(strat_rows)

        # By regime
        regime_rows = conn.execute("""
            SELECT regime, COUNT(*) as cnt,
                   SUM(CASE WHEN was_missed = 1 THEN 1 ELSE 0 END) as missed
            FROM missed_opportunities
            GROUP BY regime ORDER BY missed DESC LIMIT 10
        """).fetchall()
        result["by_regime"] = rows_to_dicts(regime_rows)

        return result


# ---------------------------------------------------------------------------
# regime_profiles helpers (v7.1)
# ---------------------------------------------------------------------------

def upsert_regime_profile(session_id: int, regime: str, strategy: str,
                           pnl: float, is_win: bool,
                           hold_cycles: float = 0,
                           entry_type: str = "full") -> None:
    """Update or create a regime-strategy performance profile."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        existing = conn.execute(
            """SELECT * FROM regime_profiles
               WHERE session_id = ? AND regime = ? AND strategy = ?""",
            (session_id, regime, strategy)
        ).fetchone()

        if existing:
            new_trades = existing["total_trades"] + 1
            new_wins = existing["wins"] + (1 if is_win else 0)
            new_losses = existing["losses"] + (0 if is_win else 1)
            new_pnl = existing["total_pnl"] + pnl
            new_avg = new_pnl / new_trades if new_trades > 0 else 0
            new_wr = new_wins / new_trades * 100 if new_trades > 0 else 0
            # Running average of hold cycles
            old_hold = existing["avg_hold_cycles"] or 0
            new_hold = (old_hold * existing["total_trades"] + hold_cycles) / new_trades

            conn.execute(
                """UPDATE regime_profiles SET
                    total_trades = ?, wins = ?, losses = ?,
                    total_pnl = ?, avg_pnl = ?, win_rate = ?,
                    avg_hold_cycles = ?, updated_at = ?
                   WHERE profile_id = ?""",
                (new_trades, new_wins, new_losses,
                 round(new_pnl, 6), round(new_avg, 6), round(new_wr, 1),
                 round(new_hold, 1), now, existing["profile_id"])
            )
        else:
            conn.execute(
                """INSERT INTO regime_profiles
                   (session_id, regime, strategy, updated_at, total_trades,
                    wins, losses, total_pnl, avg_pnl, win_rate,
                    avg_hold_cycles, best_entry_type)
                   VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, regime, strategy, now,
                 1 if is_win else 0, 0 if is_win else 1,
                 round(pnl, 6), round(pnl, 6),
                 100.0 if is_win else 0.0,
                 round(hold_cycles, 1), entry_type)
            )


def update_regime_recommendation(session_id: int, regime: str, strategy: str,
                                  confidence: float, action: str) -> None:
    """Update the recommendation for a regime-strategy pair."""
    with get_db() as conn:
        conn.execute(
            """UPDATE regime_profiles SET
                confidence_score = ?, recommended_action = ?
               WHERE session_id = ? AND regime = ? AND strategy = ?""",
            (round(confidence, 3), action, session_id, regime, strategy)
        )


def get_regime_profiles(session_id: int = None, regime: str = None,
                        strategy: str = None) -> list[dict]:
    """Get regime profiles with optional filters."""
    with get_db() as conn:
        where_parts = []
        params = []
        if session_id:
            where_parts.append("session_id = ?")
            params.append(session_id)
        if regime:
            where_parts.append("regime = ?")
            params.append(regime)
        if strategy:
            where_parts.append("strategy = ?")
            params.append(strategy)
        where = " WHERE " + " AND ".join(where_parts) if where_parts else ""
        rows = conn.execute(
            f"SELECT * FROM regime_profiles{where} ORDER BY total_trades DESC",
            params
        ).fetchall()
        return rows_to_dicts(rows)


def get_best_strategy_for_regime(session_id: int, regime: str,
                                  min_trades: int = 3) -> dict | None:
    """Get the best-performing strategy for a given regime."""
    with get_db() as conn:
        row = conn.execute(
            """SELECT * FROM regime_profiles
               WHERE session_id = ? AND regime = ? AND total_trades >= ?
               ORDER BY win_rate DESC, avg_pnl DESC LIMIT 1""",
            (session_id, regime, min_trades)
        ).fetchone()
        return dict_from_row(row)


def get_strategy_recommendation(session_id: int, regime: str,
                                 strategy: str) -> str:
    """Get recommendation for a strategy in a regime. Returns 'prefer'/'avoid'/'neutral'."""
    with get_db() as conn:
        row = conn.execute(
            """SELECT recommended_action FROM regime_profiles
               WHERE session_id = ? AND regime = ? AND strategy = ?""",
            (session_id, regime, strategy)
        ).fetchone()
        return row["recommended_action"] if row else "neutral"


# ---------------------------------------------------------------------------
# behavior_states helpers (v7.1)
# ---------------------------------------------------------------------------

def upsert_behavior_state(session_id: int, **kwargs) -> int:
    """Update or create the dynamic behavior state."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        existing = conn.execute(
            "SELECT state_id FROM behavior_states WHERE session_id = ? ORDER BY state_id DESC LIMIT 1",
            (session_id,)
        ).fetchone()

        if existing:
            sets = ", ".join(f"{k} = ?" for k in kwargs)
            vals = list(kwargs.values())
            conn.execute(
                f"UPDATE behavior_states SET {sets}, updated_at = ? WHERE state_id = ?",
                vals + [now, existing["state_id"]]
            )
            return existing["state_id"]
        else:
            kwargs["session_id"] = session_id
            kwargs["updated_at"] = now
            cols = ", ".join(kwargs.keys())
            placeholders = ", ".join("?" for _ in kwargs)
            cursor = conn.execute(
                f"INSERT INTO behavior_states ({cols}) VALUES ({placeholders})",
                list(kwargs.values())
            )
            return cursor.lastrowid


def get_behavior_state(session_id: int) -> dict | None:
    """Get the current behavior state for a session."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM behavior_states WHERE session_id = ? ORDER BY state_id DESC LIMIT 1",
            (session_id,)
        ).fetchone()
        return dict_from_row(row)


# ---------------------------------------------------------------------------
# daily_bias helpers (v7.1)
# ---------------------------------------------------------------------------

def insert_daily_bias(session_id: int, review_id: int = None,
                      bias_date: str = None, **kwargs) -> int:
    """Insert a new daily bias record. Returns bias_id."""
    now = datetime.now(timezone.utc).isoformat()
    if not bias_date:
        from datetime import date as _date
        bias_date = _date.today().isoformat()
    kwargs["session_id"] = session_id
    kwargs["review_id"] = review_id
    kwargs["bias_date"] = bias_date
    kwargs["created_at"] = now
    with get_db() as conn:
        cols = ", ".join(kwargs.keys())
        placeholders = ", ".join("?" for _ in kwargs)
        cursor = conn.execute(
            f"INSERT INTO daily_bias ({cols}) VALUES ({placeholders})",
            list(kwargs.values())
        )
        return cursor.lastrowid


def get_active_bias(session_id: int) -> dict | None:
    """Get today's active bias."""
    with get_db() as conn:
        row = conn.execute(
            """SELECT * FROM daily_bias
               WHERE session_id = ? AND active = 1
               ORDER BY bias_id DESC LIMIT 1""",
            (session_id,)
        ).fetchone()
        return dict_from_row(row)


def expire_old_biases(session_id: int, keep_bias_id: int = None) -> int:
    """Deactivate old biases. Returns count expired."""
    with get_db() as conn:
        if keep_bias_id:
            cursor = conn.execute(
                "UPDATE daily_bias SET active = 0 WHERE session_id = ? AND active = 1 AND bias_id != ?",
                (session_id, keep_bias_id)
            )
        else:
            cursor = conn.execute(
                "UPDATE daily_bias SET active = 0 WHERE session_id = ? AND active = 1",
                (session_id,)
            )
        return cursor.rowcount


def get_bias_history(session_id: int = None, limit: int = 10) -> list[dict]:
    """Get bias history."""
    with get_db() as conn:
        if session_id:
            rows = conn.execute(
                "SELECT * FROM daily_bias WHERE session_id = ? ORDER BY bias_id DESC LIMIT ?",
                (session_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM daily_bias ORDER BY bias_id DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return rows_to_dicts(rows)


# ---------------------------------------------------------------------------
# evolution_snapshots helpers (v7.3)
# ---------------------------------------------------------------------------

def insert_evolution_snapshot(session_id: int, cycle_number: int,
                               evolution_score: int, mind_level: str,
                               discipline_score: int = 0, risk_control_score: int = 0,
                               timing_score: int = 0, adaptation_score: int = 0,
                               regime_reading_score: int = 0, opportunity_score: int = 0,
                               consistency_score: int = 0, self_correction_score: int = 0,
                               patience_score: int = 0) -> int:
    """Insert an evolution snapshot. Returns snapshot_id."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO evolution_snapshots
               (session_id, timestamp, cycle_number, evolution_score, mind_level,
                discipline_score, risk_control_score, timing_score,
                adaptation_score, regime_reading_score, opportunity_score,
                consistency_score, self_correction_score, patience_score)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, now, cycle_number, evolution_score, mind_level,
             discipline_score, risk_control_score, timing_score,
             adaptation_score, regime_reading_score, opportunity_score,
             consistency_score, self_correction_score, patience_score)
        )
        return cursor.lastrowid


def get_evolution_history(session_id: int = None, limit: int = 100) -> list[dict]:
    """Get evolution score history for charting."""
    with get_db() as conn:
        if session_id:
            rows = conn.execute(
                """SELECT * FROM evolution_snapshots
                   WHERE session_id = ?
                   ORDER BY snapshot_id DESC LIMIT ?""",
                (session_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM evolution_snapshots ORDER BY snapshot_id DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return rows_to_dicts(rows)


def get_latest_evolution_snapshot(session_id: int = None) -> dict | None:
    """Get the most recent evolution snapshot."""
    with get_db() as conn:
        if session_id:
            row = conn.execute(
                "SELECT * FROM evolution_snapshots WHERE session_id = ? ORDER BY snapshot_id DESC LIMIT 1",
                (session_id,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM evolution_snapshots ORDER BY snapshot_id DESC LIMIT 1"
            ).fetchone()
        return dict_from_row(row)


# ---------------------------------------------------------------------------
# milestones helpers (v7.3)
# ---------------------------------------------------------------------------

def insert_milestone(session_id: int, title: str, description: str = None,
                      milestone_type: str = "achievement",
                      evolution_score_at: int = 0, mind_level_at: str = "Rookie",
                      version_tag: str = None) -> int:
    """Insert a milestone event. Returns milestone_id."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO milestones
               (session_id, timestamp, milestone_type, title, description,
                evolution_score_at, mind_level_at, version_tag)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, now, milestone_type, title, description,
             evolution_score_at, mind_level_at, version_tag)
        )
        return cursor.lastrowid


def get_milestones(session_id: int = None, limit: int = 50) -> list[dict]:
    """Get milestones, newest first."""
    with get_db() as conn:
        if session_id:
            rows = conn.execute(
                "SELECT * FROM milestones WHERE session_id = ? ORDER BY milestone_id DESC LIMIT ?",
                (session_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM milestones ORDER BY milestone_id DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return rows_to_dicts(rows)
