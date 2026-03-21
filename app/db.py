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
   18) news_event_analysis — classified news with observer scores (v7.4)
   19) mind_feed_events    — observer feed stream (v7.4)
   20) mind_state_snapshots — periodic mind state captures (v7.4)
   21) personality_snapshots — periodic personality trait captures (v7.4 C2)
   22) session_intents      — daily posture records (v7.4 C2)
   23) lifetime_mind_stats  — cross-session aggregation cache (v7.4 C2)
   24) news_truth_reviews   — delayed truth validation of news (v7.4 C3)
   25) mind_journal_entries — daily reflections and insights (v7.4 C3)
   26) action_reflections   — per-trade interpretation/grading (v7.4 C3)
   27) replay_markers       — timeline reconstruction markers (v7.4 C3)
   28) lifetime_identity    — persistent identity singleton (v7.4.1 Continuity)
   29) capital_ledger       — capital events: funding, refills, withdrawals (v7.4.1)
   30) lifetime_portfolio   — financial state persisting across versions (v7.4.1)
   31) crowd_sentiment_events — crowd belief snapshots for belief vs reality (v7.5)
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

-- 18) news_event_analysis: classified news with observer scores (v7.4)
CREATE TABLE IF NOT EXISTS news_event_analysis (
    analysis_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    news_event_id           INTEGER,
    session_id              INTEGER,
    timestamp               TEXT NOT NULL,
    headline                TEXT NOT NULL,
    source                  TEXT,
    category                TEXT NOT NULL DEFAULT 'general',
    trust_score             REAL NOT NULL DEFAULT 0.5,
    novelty_score           REAL NOT NULL DEFAULT 0.5,
    relevance_score         REAL NOT NULL DEFAULT 0.0,
    impact_bias             TEXT NOT NULL DEFAULT 'neutral',
    impact_strength         REAL NOT NULL DEFAULT 0.0,
    half_life               REAL NOT NULL DEFAULT 1.0,
    market_scope            TEXT DEFAULT 'crypto',
    volatility_warning      INTEGER NOT NULL DEFAULT 0,
    hype_score              REAL NOT NULL DEFAULT 0.0,
    bullshit_risk           REAL NOT NULL DEFAULT 0.0,
    sentiment               TEXT NOT NULL DEFAULT 'neutral',
    verdict                 TEXT NOT NULL DEFAULT 'noise',
    explanation             TEXT,
    accepted                INTEGER NOT NULL DEFAULT 0,
    url                     TEXT,
    original_timestamp      TEXT,
    raw_summary             TEXT,
    source_name             TEXT,
    fetched_at              TEXT,
    reasoning_text          TEXT,
    extracted_signals_json  TEXT,
    FOREIGN KEY (news_event_id) REFERENCES news_events(news_id),
    FOREIGN KEY (session_id) REFERENCES version_sessions(session_id)
);

-- 19) mind_feed_events: observer feed stream (v7.4)
CREATE TABLE IF NOT EXISTS mind_feed_events (
    event_id                INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id              INTEGER NOT NULL,
    timestamp               TEXT NOT NULL,
    event_type              TEXT NOT NULL DEFAULT 'system',
    title                   TEXT NOT NULL DEFAULT '',
    summary                 TEXT NOT NULL,
    detail                  TEXT,
    decision                TEXT,
    mood                    TEXT,
    source                  TEXT,
    source_trust            REAL,
    novelty_score           REAL NOT NULL DEFAULT 0.0,
    relevance_score         REAL NOT NULL DEFAULT 0.0,
    hype_score              REAL NOT NULL DEFAULT 0.0,
    bs_risk                 REAL NOT NULL DEFAULT 0.0,
    confidence              REAL NOT NULL DEFAULT 0.5,
    linked_news_event_id    INTEGER,
    linked_trade_id         INTEGER,
    linked_cycle_snapshot_id INTEGER,
    metadata_json           TEXT,
    FOREIGN KEY (session_id) REFERENCES version_sessions(session_id),
    FOREIGN KEY (linked_news_event_id) REFERENCES news_events(news_id),
    FOREIGN KEY (linked_trade_id) REFERENCES trade_ledger(trade_id),
    FOREIGN KEY (linked_cycle_snapshot_id) REFERENCES cycle_snapshots(snapshot_id)
);

-- 20) mind_state_snapshots: periodic mind state captures (v7.4)
CREATE TABLE IF NOT EXISTS mind_state_snapshots (
    snapshot_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id              INTEGER NOT NULL,
    timestamp               TEXT NOT NULL,
    cycle_number            INTEGER NOT NULL DEFAULT 0,
    mind_state              TEXT NOT NULL DEFAULT 'idle_waiting',
    mind_state_label        TEXT NOT NULL DEFAULT 'Idle & Waiting',
    action_impulse          TEXT NOT NULL DEFAULT 'none',
    crowd_heat              TEXT NOT NULL DEFAULT 'neutral',
    signal_quality          REAL NOT NULL DEFAULT 0.5,
    narrative_distortion    REAL NOT NULL DEFAULT 0.0,
    clarity                 INTEGER NOT NULL DEFAULT 50,
    current_focus           TEXT,
    reasoning_summary       TEXT,
    fear_greed_value        INTEGER,
    noise_ratio             REAL,
    market_state            TEXT,
    thoughts_json           TEXT,
    concerns_json           TEXT,
    FOREIGN KEY (session_id) REFERENCES version_sessions(session_id)
);

-- v7.4 indexes
CREATE INDEX IF NOT EXISTS idx_news_analysis_verdict ON news_event_analysis(verdict);
CREATE INDEX IF NOT EXISTS idx_news_analysis_ts ON news_event_analysis(timestamp);
CREATE INDEX IF NOT EXISTS idx_news_analysis_news_event ON news_event_analysis(news_event_id);
CREATE INDEX IF NOT EXISTS idx_mind_feed_session ON mind_feed_events(session_id);
CREATE INDEX IF NOT EXISTS idx_mind_feed_type ON mind_feed_events(event_type);
CREATE INDEX IF NOT EXISTS idx_mind_feed_ts ON mind_feed_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_mind_state_snap_session ON mind_state_snapshots(session_id);
CREATE INDEX IF NOT EXISTS idx_mind_state_snap_cycle ON mind_state_snapshots(cycle_number);

-- 21) personality_snapshots: periodic personality trait captures (v7.4 Chunk 2)
CREATE TABLE IF NOT EXISTS personality_snapshots (
    snapshot_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id              INTEGER NOT NULL,
    timestamp               TEXT NOT NULL,
    dominant_trait           TEXT,
    patience_score          INTEGER NOT NULL DEFAULT 50,
    aggression_control      INTEGER NOT NULL DEFAULT 50,
    hype_resistance         INTEGER NOT NULL DEFAULT 50,
    adaptability_score      INTEGER NOT NULL DEFAULT 50,
    discipline_score        INTEGER NOT NULL DEFAULT 50,
    self_correction_score   INTEGER NOT NULL DEFAULT 50,
    risk_awareness_score    INTEGER NOT NULL DEFAULT 50,
    oneliner                TEXT,
    evidence_json           TEXT,
    FOREIGN KEY (session_id) REFERENCES version_sessions(session_id)
);

-- 22) session_intents: daily posture records (v7.4 Chunk 2)
CREATE TABLE IF NOT EXISTS session_intents (
    intent_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id              INTEGER NOT NULL,
    timestamp               TEXT NOT NULL,
    intent                  TEXT NOT NULL DEFAULT 'neutral',
    confidence              REAL NOT NULL DEFAULT 0.3,
    reasoning               TEXT,
    factors_json            TEXT,
    context_json            TEXT,
    FOREIGN KEY (session_id) REFERENCES version_sessions(session_id)
);

-- 23) lifetime_mind_stats: cross-session aggregation cache (v7.4 Chunk 2)
CREATE TABLE IF NOT EXISTS lifetime_mind_stats (
    stat_id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp               TEXT NOT NULL,
    total_sessions          INTEGER NOT NULL DEFAULT 0,
    total_cycles            INTEGER NOT NULL DEFAULT 0,
    total_trades            INTEGER NOT NULL DEFAULT 0,
    total_hours             REAL NOT NULL DEFAULT 0.0,
    lifetime_pnl            REAL NOT NULL DEFAULT 0.0,
    avg_evolution_score     REAL NOT NULL DEFAULT 0.0,
    peak_evolution_score    INTEGER NOT NULL DEFAULT 0,
    peak_level              TEXT NOT NULL DEFAULT 'Seed',
    data_json               TEXT
);

-- v7.4 Chunk 2 indexes
CREATE INDEX IF NOT EXISTS idx_personality_snap_session ON personality_snapshots(session_id);
CREATE INDEX IF NOT EXISTS idx_session_intents_session ON session_intents(session_id);
CREATE INDEX IF NOT EXISTS idx_session_intents_ts ON session_intents(timestamp);

-- 24) news_truth_reviews: delayed truth validation of news predictions (v7.4 Chunk 3)
CREATE TABLE IF NOT EXISTS news_truth_reviews (
    review_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id             INTEGER,
    session_id              INTEGER,
    headline                TEXT NOT NULL,
    expected_bias           TEXT NOT NULL DEFAULT 'neutral',
    review_window           INTEGER NOT NULL DEFAULT 5,
    price_at_news           REAL,
    price_at_review         REAL,
    actual_move_pct         REAL,
    verdict                 TEXT NOT NULL DEFAULT 'pending',
    explanation             TEXT,
    reviewed_at             TEXT,
    created_at              TEXT NOT NULL,
    FOREIGN KEY (analysis_id) REFERENCES news_event_analysis(analysis_id),
    FOREIGN KEY (session_id) REFERENCES version_sessions(session_id)
);

-- 25) mind_journal_entries: daily reflections and insights (v7.4 Chunk 3)
CREATE TABLE IF NOT EXISTS mind_journal_entries (
    entry_id                INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id              INTEGER,
    journal_date            TEXT NOT NULL,
    created_at              TEXT NOT NULL,
    entry_type              TEXT NOT NULL DEFAULT 'daily',
    key_insight             TEXT,
    mistakes_text           TEXT,
    lessons_text            TEXT,
    bias_shifts_text        TEXT,
    market_summary          TEXT,
    mood_arc                TEXT,
    trades_reflection       TEXT,
    confidence              REAL NOT NULL DEFAULT 0.5,
    data_json               TEXT,
    FOREIGN KEY (session_id) REFERENCES version_sessions(session_id)
);

-- 26) action_reflections: per-trade interpretation and grading (v7.4 Chunk 3)
CREATE TABLE IF NOT EXISTS action_reflections (
    reflection_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id                INTEGER,
    session_id              INTEGER,
    timestamp               TEXT NOT NULL,
    action                  TEXT NOT NULL,
    entry_timing_grade      TEXT NOT NULL DEFAULT 'C',
    size_grade              TEXT NOT NULL DEFAULT 'C',
    patience_impact         TEXT NOT NULL DEFAULT 'neutral',
    overall_grade           TEXT NOT NULL DEFAULT 'C',
    reasoning               TEXT,
    what_went_well          TEXT,
    what_could_improve      TEXT,
    data_json               TEXT,
    FOREIGN KEY (trade_id) REFERENCES trade_ledger(trade_id),
    FOREIGN KEY (session_id) REFERENCES version_sessions(session_id)
);

-- 27) replay_markers: timeline reconstruction markers (v7.4 Chunk 3)
CREATE TABLE IF NOT EXISTS replay_markers (
    marker_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id              INTEGER,
    timestamp               TEXT NOT NULL,
    marker_type             TEXT NOT NULL DEFAULT 'event',
    cycle_number            INTEGER,
    title                   TEXT NOT NULL,
    detail                  TEXT,
    linked_trade_id         INTEGER,
    linked_news_analysis_id INTEGER,
    linked_mind_state       TEXT,
    price_at_marker         REAL,
    mood_at_marker          TEXT,
    importance              INTEGER NOT NULL DEFAULT 5,
    data_json               TEXT,
    FOREIGN KEY (session_id) REFERENCES version_sessions(session_id)
);

-- v7.4 Chunk 3 indexes
CREATE INDEX IF NOT EXISTS idx_truth_reviews_analysis ON news_truth_reviews(analysis_id);
CREATE INDEX IF NOT EXISTS idx_truth_reviews_verdict ON news_truth_reviews(verdict);
CREATE INDEX IF NOT EXISTS idx_truth_reviews_session ON news_truth_reviews(session_id);
CREATE INDEX IF NOT EXISTS idx_journal_entries_session ON mind_journal_entries(session_id);
CREATE INDEX IF NOT EXISTS idx_journal_entries_date ON mind_journal_entries(journal_date);
CREATE INDEX IF NOT EXISTS idx_action_reflections_trade ON action_reflections(trade_id);
CREATE INDEX IF NOT EXISTS idx_action_reflections_session ON action_reflections(session_id);
CREATE INDEX IF NOT EXISTS idx_replay_markers_session ON replay_markers(session_id);
CREATE INDEX IF NOT EXISTS idx_replay_markers_cycle ON replay_markers(cycle_number);
CREATE INDEX IF NOT EXISTS idx_replay_markers_type ON replay_markers(marker_type);

-- 28) lifetime_identity: persistent identity across versions (v7.4.1 Continuity)
CREATE TABLE IF NOT EXISTS lifetime_identity (
    id                      INTEGER PRIMARY KEY DEFAULT 1,
    first_seen_at           TEXT NOT NULL,
    total_cycles            INTEGER NOT NULL DEFAULT 0,
    total_trades            INTEGER NOT NULL DEFAULT 0,
    total_sessions          INTEGER NOT NULL DEFAULT 0,
    last_version            TEXT NOT NULL DEFAULT '7.4.0',
    dominant_traits_json    TEXT,
    memory_depth_score      REAL NOT NULL DEFAULT 0.0,
    continuity_score        REAL NOT NULL DEFAULT 0.0,
    updated_at              TEXT NOT NULL
);

-- 29) capital_ledger: tracks all capital events (funding, refills, withdrawals)
CREATE TABLE IF NOT EXISTS capital_ledger (
    ledger_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp               TEXT NOT NULL,
    event_type              TEXT NOT NULL DEFAULT 'initial_funding',
    amount                  REAL NOT NULL DEFAULT 0.0,
    balance_after           REAL,
    reason                  TEXT,
    session_id              INTEGER,
    version                 TEXT,
    notes                   TEXT,
    FOREIGN KEY (session_id) REFERENCES version_sessions(session_id)
);

-- 30) lifetime_portfolio: financial state that persists across versions (singleton)
CREATE TABLE IF NOT EXISTS lifetime_portfolio (
    id                      INTEGER PRIMARY KEY DEFAULT 1,
    cash                    REAL NOT NULL DEFAULT 0.0,
    btc_holdings            REAL NOT NULL DEFAULT 0.0,
    avg_entry_price         REAL NOT NULL DEFAULT 0.0,
    total_equity            REAL NOT NULL DEFAULT 0.0,
    realized_pnl            REAL NOT NULL DEFAULT 0.0,
    unrealized_pnl          REAL NOT NULL DEFAULT 0.0,
    total_trades            INTEGER NOT NULL DEFAULT 0,
    total_wins              INTEGER NOT NULL DEFAULT 0,
    total_losses            INTEGER NOT NULL DEFAULT 0,
    total_holds             INTEGER NOT NULL DEFAULT 0,
    total_blocked           INTEGER NOT NULL DEFAULT 0,
    peak_equity             REAL NOT NULL DEFAULT 0.0,
    max_drawdown_pct        REAL NOT NULL DEFAULT 0.0,
    total_refills           INTEGER NOT NULL DEFAULT 0,
    total_refill_amount     REAL NOT NULL DEFAULT 0.0,
    last_price              REAL NOT NULL DEFAULT 0.0,
    updated_at              TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_capital_ledger_type ON capital_ledger(event_type);
CREATE INDEX IF NOT EXISTS idx_capital_ledger_ts ON capital_ledger(timestamp);

-- 31) crowd_sentiment_events: crowd belief snapshots (v7.5 Crowd Sentiment)
CREATE TABLE IF NOT EXISTS crowd_sentiment_events (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp               TEXT NOT NULL,
    source                  TEXT NOT NULL DEFAULT 'internal_sentiment',
    event_id                TEXT,
    question                TEXT,
    crowd_probability       REAL NOT NULL DEFAULT 0.5,
    bias                    TEXT NOT NULL DEFAULT 'neutral',
    confidence_strength     REAL NOT NULL DEFAULT 0.0,
    notes_json              TEXT
);

CREATE INDEX IF NOT EXISTS idx_crowd_sentiment_ts ON crowd_sentiment_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_crowd_sentiment_bias ON crowd_sentiment_events(bias);
"""


def init_db():
    """Create all tables if they don't exist. Safe to call multiple times."""
    with get_db() as conn:
        conn.executescript(_SCHEMA)
        # Migrations: add columns to existing tables (safe to re-run)
        _migrate_news_transparency(conn)
    print(f"[db] Initialized database at {DB_PATH}")


def _migrate_news_transparency(conn):
    """Add news transparency columns if missing (v7.4.1)."""
    new_cols = [
        ("raw_summary", "TEXT"),
        ("source_name", "TEXT"),
        ("fetched_at", "TEXT"),
        ("reasoning_text", "TEXT"),
        ("extracted_signals_json", "TEXT"),
    ]
    for col_name, col_type in new_cols:
        try:
            conn.execute(f"ALTER TABLE news_event_analysis ADD COLUMN {col_name} {col_type}")
        except Exception:
            pass  # column already exists


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


# ---------------------------------------------------------------------------
# news_event_analysis helpers (v7.4)
# ---------------------------------------------------------------------------

def insert_news_analysis(session_id: int, headline: str, verdict: str,
                          news_event_id: int = None, **kwargs) -> int:
    """Insert a classified news analysis.  Deduplicates by headline."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        existing = conn.execute(
            "SELECT analysis_id FROM news_event_analysis WHERE headline = ? LIMIT 1",
            (headline,)
        ).fetchone()
        if existing:
            return existing["analysis_id"]
        data = {
            "session_id":         session_id,
            "news_event_id":      news_event_id,
            "timestamp":          now,
            "headline":           headline,
            "verdict":            verdict,
        }
        data.update(kwargs)
        cols = ", ".join(data.keys())
        ph   = ", ".join("?" for _ in data)
        cursor = conn.execute(
            f"INSERT INTO news_event_analysis ({cols}) VALUES ({ph})",
            list(data.values()),
        )
        return cursor.lastrowid


def get_news_analyses(verdict: str = None, limit: int = 50) -> list[dict]:
    with get_db() as conn:
        if verdict:
            rows = conn.execute(
                "SELECT * FROM news_event_analysis WHERE verdict = ? ORDER BY analysis_id DESC LIMIT ?",
                (verdict, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM news_event_analysis ORDER BY analysis_id DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return rows_to_dicts(rows)


def get_news_analysis_by_id(analysis_id: int) -> dict | None:
    """Get a single news analysis by ID with all fields."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM news_event_analysis WHERE analysis_id = ?",
            (analysis_id,)
        ).fetchone()
        return dict_from_row(row)


def get_news_analysis_summary() -> dict:
    with get_db() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN verdict = 'interesting' THEN 1 ELSE 0 END) as interesting,
                SUM(CASE WHEN verdict = 'watch' THEN 1 ELSE 0 END) as watched,
                SUM(CASE WHEN verdict = 'reject' THEN 1 ELSE 0 END) as rejected,
                SUM(CASE WHEN verdict = 'noise' THEN 1 ELSE 0 END) as noise,
                SUM(CASE WHEN sentiment = 'bullish' THEN 1 ELSE 0 END) as bullish,
                SUM(CASE WHEN sentiment = 'bearish' THEN 1 ELSE 0 END) as bearish
            FROM news_event_analysis
        """).fetchone()
        return dict_from_row(row) if row else {}


# ---------------------------------------------------------------------------
# mind_feed_events helpers (v7.4)
# ---------------------------------------------------------------------------

def insert_mind_feed_event(session_id: int, event_type: str, summary: str,
                            title: str = "", detail: str = None,
                            mood: str = None, source: str = None,
                            novelty_score: float = 0.0,
                            relevance_score: float = 0.0,
                            hype_score: float = 0.0,
                            bs_risk: float = 0.0,
                            confidence: float = 0.5,
                            linked_news_event_id: int = None,
                            linked_trade_id: int = None,
                            linked_cycle_snapshot_id: int = None,
                            metadata_json: str = None) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        # dedupe (same type + summary within 60s)
        existing = conn.execute(
            """SELECT event_id FROM mind_feed_events
               WHERE session_id = ? AND event_type = ? AND summary = ?
               AND timestamp > datetime(?, '-60 seconds')
               LIMIT 1""",
            (session_id, event_type, summary, now)
        ).fetchone()
        if existing:
            return existing["event_id"]
        cursor = conn.execute(
            """INSERT INTO mind_feed_events
               (session_id, timestamp, event_type, title, summary, detail,
                mood, source, novelty_score, relevance_score, hype_score,
                bs_risk, confidence, linked_news_event_id, linked_trade_id,
                linked_cycle_snapshot_id, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, now, event_type, title, summary, detail,
             mood, source, novelty_score, relevance_score, hype_score,
             bs_risk, confidence, linked_news_event_id, linked_trade_id,
             linked_cycle_snapshot_id, metadata_json)
        )
        return cursor.lastrowid


def get_mind_feed_events(session_id: int = None, event_type: str = None,
                          limit: int = 50) -> list[dict]:
    with get_db() as conn:
        w, p = [], []
        if session_id:
            w.append("session_id = ?"); p.append(session_id)
        if event_type:
            w.append("event_type = ?"); p.append(event_type)
        where = " WHERE " + " AND ".join(w) if w else ""
        rows = conn.execute(
            f"SELECT * FROM mind_feed_events{where} ORDER BY event_id DESC LIMIT ?",
            p + [limit]
        ).fetchall()
        return rows_to_dicts(rows)


# ---------------------------------------------------------------------------
# mind_state_snapshots helpers (v7.4)
# ---------------------------------------------------------------------------

def insert_mind_state_snapshot(session_id: int, cycle_number: int,
                                mind_state: str, mind_state_label: str,
                                action_impulse: str = "none",
                                crowd_heat: str = "neutral",
                                signal_quality: float = 0.5,
                                narrative_distortion: float = 0.0,
                                clarity: int = 50,
                                current_focus: str = None,
                                reasoning_summary: str = None,
                                fear_greed_value: int = None,
                                noise_ratio: float = None,
                                market_state: str = None,
                                thoughts_json: str = None,
                                concerns_json: str = None) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        # Dedup: skip if same session + cycle already snapshotted in last 60s
        existing = conn.execute(
            """SELECT snapshot_id FROM mind_state_snapshots
               WHERE session_id = ? AND cycle_number = ?
               AND timestamp > datetime('now', '-60 seconds') LIMIT 1""",
            (session_id, cycle_number),
        ).fetchone()
        if existing:
            return existing[0]
        cursor = conn.execute(
            """INSERT INTO mind_state_snapshots
               (session_id, timestamp, cycle_number, mind_state, mind_state_label,
                action_impulse, crowd_heat, signal_quality, narrative_distortion,
                clarity, current_focus, reasoning_summary, fear_greed_value,
                noise_ratio, market_state, thoughts_json, concerns_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, now, cycle_number, mind_state, mind_state_label,
             action_impulse, crowd_heat, signal_quality, narrative_distortion,
             clarity, current_focus, reasoning_summary, fear_greed_value,
             noise_ratio, market_state, thoughts_json, concerns_json)
        )
        return cursor.lastrowid


def get_mind_state_history(session_id: int = None, limit: int = 50) -> list[dict]:
    with get_db() as conn:
        if session_id:
            rows = conn.execute(
                "SELECT * FROM mind_state_snapshots WHERE session_id = ? ORDER BY snapshot_id DESC LIMIT ?",
                (session_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM mind_state_snapshots ORDER BY snapshot_id DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return rows_to_dicts(rows)


# ---------------------------------------------------------------------------
# personality_snapshots helpers (v7.4 Chunk 2)
# ---------------------------------------------------------------------------

def insert_personality_snapshot(session_id: int, dominant_trait: str = None,
                                patience_score: int = 50,
                                aggression_control: int = 50,
                                hype_resistance: int = 50,
                                adaptability_score: int = 50,
                                discipline_score: int = 50,
                                self_correction_score: int = 50,
                                risk_awareness_score: int = 50,
                                oneliner: str = None,
                                evidence_json: str = None) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        # Dedup: skip if same session snapshotted in last 5 min
        existing = conn.execute(
            """SELECT snapshot_id FROM personality_snapshots
               WHERE session_id = ? AND timestamp > datetime('now', '-300 seconds')
               LIMIT 1""",
            (session_id,)
        ).fetchone()
        if existing:
            return existing[0]
        cursor = conn.execute(
            """INSERT INTO personality_snapshots
               (session_id, timestamp, dominant_trait,
                patience_score, aggression_control, hype_resistance,
                adaptability_score, discipline_score, self_correction_score,
                risk_awareness_score, oneliner, evidence_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, now, dominant_trait,
             patience_score, aggression_control, hype_resistance,
             adaptability_score, discipline_score, self_correction_score,
             risk_awareness_score, oneliner, evidence_json)
        )
        return cursor.lastrowid


def get_personality_history(session_id: int = None, limit: int = 50) -> list[dict]:
    with get_db() as conn:
        if session_id:
            rows = conn.execute(
                "SELECT * FROM personality_snapshots WHERE session_id = ? ORDER BY snapshot_id DESC LIMIT ?",
                (session_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM personality_snapshots ORDER BY snapshot_id DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return rows_to_dicts(rows)


# ---------------------------------------------------------------------------
# session_intents helpers (v7.4 Chunk 2)
# ---------------------------------------------------------------------------

def insert_session_intent(session_id: int, intent: str = "neutral",
                          confidence: float = 0.3, reasoning: str = None,
                          factors_json: str = None,
                          context_json: str = None) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        # Dedup: skip if same session + intent in last 10 min
        existing = conn.execute(
            """SELECT intent_id FROM session_intents
               WHERE session_id = ? AND intent = ?
               AND timestamp > datetime('now', '-600 seconds') LIMIT 1""",
            (session_id, intent)
        ).fetchone()
        if existing:
            return existing[0]
        cursor = conn.execute(
            """INSERT INTO session_intents
               (session_id, timestamp, intent, confidence, reasoning,
                factors_json, context_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (session_id, now, intent, confidence, reasoning,
             factors_json, context_json)
        )
        return cursor.lastrowid


def get_session_intents(session_id: int = None, limit: int = 20) -> list[dict]:
    with get_db() as conn:
        if session_id:
            rows = conn.execute(
                "SELECT * FROM session_intents WHERE session_id = ? ORDER BY intent_id DESC LIMIT ?",
                (session_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM session_intents ORDER BY intent_id DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return rows_to_dicts(rows)


# ---------------------------------------------------------------------------
# lifetime_mind_stats helpers (v7.4 Chunk 2)
# ---------------------------------------------------------------------------

def upsert_lifetime_stats(total_sessions: int = 0, total_cycles: int = 0,
                          total_trades: int = 0, total_hours: float = 0.0,
                          lifetime_pnl: float = 0.0,
                          avg_evolution_score: float = 0.0,
                          peak_evolution_score: int = 0,
                          peak_level: str = "Seed",
                          data_json: str = None) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        existing = conn.execute(
            "SELECT stat_id FROM lifetime_mind_stats ORDER BY stat_id DESC LIMIT 1"
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE lifetime_mind_stats SET
                   timestamp = ?, total_sessions = ?, total_cycles = ?,
                   total_trades = ?, total_hours = ?, lifetime_pnl = ?,
                   avg_evolution_score = ?, peak_evolution_score = ?,
                   peak_level = ?, data_json = ?
                   WHERE stat_id = ?""",
                (now, total_sessions, total_cycles, total_trades, total_hours,
                 lifetime_pnl, avg_evolution_score, peak_evolution_score,
                 peak_level, data_json, existing[0])
            )
            return existing[0]
        else:
            cursor = conn.execute(
                """INSERT INTO lifetime_mind_stats
                   (timestamp, total_sessions, total_cycles, total_trades,
                    total_hours, lifetime_pnl, avg_evolution_score,
                    peak_evolution_score, peak_level, data_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (now, total_sessions, total_cycles, total_trades, total_hours,
                 lifetime_pnl, avg_evolution_score, peak_evolution_score,
                 peak_level, data_json)
            )
            return cursor.lastrowid


def get_lifetime_stats() -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM lifetime_mind_stats ORDER BY stat_id DESC LIMIT 1"
        ).fetchone()
        if row:
            return rows_to_dicts([row])[0]
        return None


# ---------------------------------------------------------------------------
# cycle_snapshots range helper (v7.4 Chunk 3)
# ---------------------------------------------------------------------------

def get_cycle_snapshots_range(session_id: int, cycle_start: int,
                               cycle_end: int) -> list[dict]:
    """Get cycle snapshots within a cycle number range (inclusive)."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM cycle_snapshots
               WHERE session_id = ? AND cycle_number >= ? AND cycle_number <= ?
               ORDER BY cycle_number ASC""",
            (session_id, cycle_start, cycle_end)
        ).fetchall()
        return rows_to_dicts(rows)


def get_snapshot_at_cycle(session_id: int, cycle_number: int) -> dict | None:
    """Get the snapshot closest to a specific cycle number."""
    with get_db() as conn:
        row = conn.execute(
            """SELECT * FROM cycle_snapshots
               WHERE session_id = ? AND cycle_number <= ?
               ORDER BY cycle_number DESC LIMIT 1""",
            (session_id, cycle_number)
        ).fetchone()
        return dict_from_row(row)


# ---------------------------------------------------------------------------
# news_truth_reviews helpers (v7.4 Chunk 3)
# ---------------------------------------------------------------------------

def insert_truth_review(session_id: int, headline: str, expected_bias: str,
                        review_window: int = 5, analysis_id: int = None,
                        price_at_news: float = None) -> int:
    """Create a pending truth review. Returns review_id."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        # Dedup: same headline + window
        existing = conn.execute(
            """SELECT review_id FROM news_truth_reviews
               WHERE headline = ? AND review_window = ? LIMIT 1""",
            (headline, review_window)
        ).fetchone()
        if existing:
            return existing[0]
        cursor = conn.execute(
            """INSERT INTO news_truth_reviews
               (analysis_id, session_id, headline, expected_bias, review_window,
                price_at_news, verdict, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (analysis_id, session_id, headline, expected_bias, review_window,
             price_at_news, now)
        )
        return cursor.lastrowid


def get_pending_truth_reviews(review_window: int = None) -> list[dict]:
    """Get truth reviews that haven't been evaluated yet."""
    with get_db() as conn:
        if review_window:
            rows = conn.execute(
                """SELECT * FROM news_truth_reviews
                   WHERE verdict = 'pending' AND review_window = ?
                   ORDER BY created_at ASC LIMIT 100""",
                (review_window,)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM news_truth_reviews
                   WHERE verdict = 'pending'
                   ORDER BY created_at ASC LIMIT 100"""
            ).fetchall()
        return rows_to_dicts(rows)


def complete_truth_review(review_id: int, price_at_review: float,
                          actual_move_pct: float, verdict: str,
                          explanation: str = None) -> None:
    """Complete a truth review with the actual outcome."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute(
            """UPDATE news_truth_reviews SET
               price_at_review = ?, actual_move_pct = ?,
               verdict = ?, explanation = ?, reviewed_at = ?
               WHERE review_id = ?""",
            (price_at_review, actual_move_pct, verdict, explanation, now, review_id)
        )


def get_truth_reviews(session_id: int = None, verdict: str = None,
                      limit: int = 50) -> list[dict]:
    """Get truth reviews with optional filters."""
    with get_db() as conn:
        w, p = [], []
        if session_id:
            w.append("session_id = ?"); p.append(session_id)
        if verdict:
            w.append("verdict = ?"); p.append(verdict)
        where = " WHERE " + " AND ".join(w) if w else ""
        rows = conn.execute(
            f"SELECT * FROM news_truth_reviews{where} ORDER BY review_id DESC LIMIT ?",
            p + [limit]
        ).fetchall()
        return rows_to_dicts(rows)


def get_truth_review_summary() -> dict:
    """Summary stats for truth reviews."""
    with get_db() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN verdict = 'pending' THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN verdict = 'correct' THEN 1 ELSE 0 END) as correct,
                SUM(CASE WHEN verdict = 'wrong' THEN 1 ELSE 0 END) as wrong,
                SUM(CASE WHEN verdict = 'mixed' THEN 1 ELSE 0 END) as mixed,
                SUM(CASE WHEN verdict = 'faded' THEN 1 ELSE 0 END) as faded,
                SUM(CASE WHEN verdict = 'unclear' THEN 1 ELSE 0 END) as unclear,
                AVG(CASE WHEN verdict NOT IN ('pending', 'unclear') THEN actual_move_pct END) as avg_move
            FROM news_truth_reviews
        """).fetchone()
        return dict_from_row(row) if row else {}


# ---------------------------------------------------------------------------
# mind_journal_entries helpers (v7.4 Chunk 3)
# ---------------------------------------------------------------------------

def insert_journal_entry(session_id: int, journal_date: str,
                          entry_type: str = "daily", **kwargs) -> int:
    """Insert a journal entry. Dedup by session + date + type."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        existing = conn.execute(
            """SELECT entry_id FROM mind_journal_entries
               WHERE session_id = ? AND journal_date = ? AND entry_type = ?
               LIMIT 1""",
            (session_id, journal_date, entry_type)
        ).fetchone()
        if existing:
            # Update existing entry
            sets = ", ".join(f"{k} = ?" for k in kwargs)
            vals = list(kwargs.values())
            if sets:
                conn.execute(
                    f"UPDATE mind_journal_entries SET {sets} WHERE entry_id = ?",
                    vals + [existing[0]]
                )
            return existing[0]
        kwargs["session_id"] = session_id
        kwargs["journal_date"] = journal_date
        kwargs["entry_type"] = entry_type
        kwargs["created_at"] = now
        cols = ", ".join(kwargs.keys())
        ph = ", ".join("?" for _ in kwargs)
        cursor = conn.execute(
            f"INSERT INTO mind_journal_entries ({cols}) VALUES ({ph})",
            list(kwargs.values())
        )
        return cursor.lastrowid


def get_journal_entries(session_id: int = None, limit: int = 20) -> list[dict]:
    with get_db() as conn:
        if session_id:
            rows = conn.execute(
                "SELECT * FROM mind_journal_entries WHERE session_id = ? ORDER BY entry_id DESC LIMIT ?",
                (session_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM mind_journal_entries ORDER BY entry_id DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return rows_to_dicts(rows)


def get_latest_journal_entry(session_id: int = None) -> dict | None:
    with get_db() as conn:
        if session_id:
            row = conn.execute(
                "SELECT * FROM mind_journal_entries WHERE session_id = ? ORDER BY entry_id DESC LIMIT 1",
                (session_id,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM mind_journal_entries ORDER BY entry_id DESC LIMIT 1"
            ).fetchone()
        return dict_from_row(row)


# ---------------------------------------------------------------------------
# action_reflections helpers (v7.4 Chunk 3)
# ---------------------------------------------------------------------------

def insert_action_reflection(trade_id: int, session_id: int, action: str,
                              entry_timing_grade: str = "C",
                              size_grade: str = "C",
                              patience_impact: str = "neutral",
                              overall_grade: str = "C",
                              reasoning: str = None,
                              what_went_well: str = None,
                              what_could_improve: str = None,
                              data_json: str = None) -> int:
    """Insert a trade reflection. Dedup by trade_id."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        existing = conn.execute(
            "SELECT reflection_id FROM action_reflections WHERE trade_id = ? LIMIT 1",
            (trade_id,)
        ).fetchone()
        if existing:
            return existing[0]
        cursor = conn.execute(
            """INSERT INTO action_reflections
               (trade_id, session_id, timestamp, action,
                entry_timing_grade, size_grade, patience_impact,
                overall_grade, reasoning, what_went_well,
                what_could_improve, data_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (trade_id, session_id, now, action,
             entry_timing_grade, size_grade, patience_impact,
             overall_grade, reasoning, what_went_well,
             what_could_improve, data_json)
        )
        return cursor.lastrowid


def get_action_reflections(session_id: int = None, limit: int = 30) -> list[dict]:
    with get_db() as conn:
        if session_id:
            rows = conn.execute(
                "SELECT * FROM action_reflections WHERE session_id = ? ORDER BY reflection_id DESC LIMIT ?",
                (session_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM action_reflections ORDER BY reflection_id DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return rows_to_dicts(rows)


def get_reflection_for_trade(trade_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM action_reflections WHERE trade_id = ? LIMIT 1",
            (trade_id,)
        ).fetchone()
        return dict_from_row(row)


def get_reflection_summary(session_id: int = None) -> dict:
    """Grade distribution summary for action reflections."""
    with get_db() as conn:
        where = "WHERE session_id = ?" if session_id else ""
        params = [session_id] if session_id else []
        row = conn.execute(f"""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN overall_grade = 'A' THEN 1 ELSE 0 END) as grade_a,
                SUM(CASE WHEN overall_grade = 'B' THEN 1 ELSE 0 END) as grade_b,
                SUM(CASE WHEN overall_grade = 'C' THEN 1 ELSE 0 END) as grade_c,
                SUM(CASE WHEN overall_grade = 'D' THEN 1 ELSE 0 END) as grade_d,
                SUM(CASE WHEN overall_grade = 'F' THEN 1 ELSE 0 END) as grade_f,
                SUM(CASE WHEN patience_impact = 'helped' THEN 1 ELSE 0 END) as patience_helped,
                SUM(CASE WHEN patience_impact = 'hurt' THEN 1 ELSE 0 END) as patience_hurt
            FROM action_reflections {where}
        """, params).fetchone()
        return dict_from_row(row) if row else {}


# ---------------------------------------------------------------------------
# replay_markers helpers (v7.4 Chunk 3)
# ---------------------------------------------------------------------------

def insert_replay_marker(session_id: int, title: str,
                          marker_type: str = "event",
                          cycle_number: int = None,
                          detail: str = None,
                          linked_trade_id: int = None,
                          linked_news_analysis_id: int = None,
                          linked_mind_state: str = None,
                          price_at_marker: float = None,
                          mood_at_marker: str = None,
                          importance: int = 5,
                          data_json: str = None) -> int:
    """Insert a replay marker. Dedup by session + title + cycle."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        if cycle_number is not None:
            existing = conn.execute(
                """SELECT marker_id FROM replay_markers
                   WHERE session_id = ? AND title = ? AND cycle_number = ? LIMIT 1""",
                (session_id, title, cycle_number)
            ).fetchone()
            if existing:
                return existing[0]
        cursor = conn.execute(
            """INSERT INTO replay_markers
               (session_id, timestamp, marker_type, cycle_number, title, detail,
                linked_trade_id, linked_news_analysis_id, linked_mind_state,
                price_at_marker, mood_at_marker, importance, data_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, now, marker_type, cycle_number, title, detail,
             linked_trade_id, linked_news_analysis_id, linked_mind_state,
             price_at_marker, mood_at_marker, importance, data_json)
        )
        return cursor.lastrowid


def get_replay_markers(session_id: int, limit: int = 100) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM replay_markers
               WHERE session_id = ?
               ORDER BY COALESCE(cycle_number, 0) ASC, marker_id ASC
               LIMIT ?""",
            (session_id, limit)
        ).fetchall()
        return rows_to_dicts(rows)


def get_replay_timeline(session_id: int, cycle_start: int = 0,
                         cycle_end: int = 999999) -> list[dict]:
    """Get replay markers within a cycle range, plus linked snapshots."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM replay_markers
               WHERE session_id = ?
               AND COALESCE(cycle_number, 0) >= ?
               AND COALESCE(cycle_number, 999999) <= ?
               ORDER BY COALESCE(cycle_number, 0) ASC, importance DESC
               LIMIT 200""",
            (session_id, cycle_start, cycle_end)
        ).fetchall()
        return rows_to_dicts(rows)


# ---------------------------------------------------------------------------
# lifetime_identity helpers (v7.4.1 Continuity Layer)
# ---------------------------------------------------------------------------

def get_lifetime_identity() -> dict | None:
    """Get the singleton lifetime identity row."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM lifetime_identity WHERE id = 1").fetchone()
        return dict_from_row(row)


def upsert_lifetime_identity(**kwargs) -> None:
    """Update or create the lifetime identity singleton."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        existing = conn.execute("SELECT id FROM lifetime_identity WHERE id = 1").fetchone()
        if existing:
            sets = ", ".join(f"{k} = ?" for k in kwargs)
            vals = list(kwargs.values())
            conn.execute(f"UPDATE lifetime_identity SET {sets}, updated_at = ? WHERE id = 1",
                         vals + [now])
        else:
            kwargs.setdefault("first_seen_at", now)
            kwargs["updated_at"] = now
            kwargs["id"] = 1
            cols = ", ".join(kwargs.keys())
            ph = ", ".join("?" for _ in kwargs)
            conn.execute(f"INSERT INTO lifetime_identity ({cols}) VALUES ({ph})",
                         list(kwargs.values()))


def increment_identity_counters(cycles: int = 0, trades: int = 0, sessions: int = 0) -> None:
    """Atomically increment lifetime identity counters."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        existing = conn.execute("SELECT id FROM lifetime_identity WHERE id = 1").fetchone()
        if existing:
            conn.execute(
                """UPDATE lifetime_identity SET
                   total_cycles = total_cycles + ?,
                   total_trades = total_trades + ?,
                   total_sessions = total_sessions + ?,
                   updated_at = ?
                   WHERE id = 1""",
                (cycles, trades, sessions, now)
            )
        else:
            conn.execute(
                """INSERT INTO lifetime_identity
                   (id, first_seen_at, total_cycles, total_trades, total_sessions,
                    last_version, updated_at)
                   VALUES (1, ?, ?, ?, ?, '7.4.0', ?)""",
                (now, cycles, trades, sessions, now)
            )


# ---------------------------------------------------------------------------
# Lifetime query helpers (cross-session, cumulative)
# ---------------------------------------------------------------------------

def get_lifetime_memories(limit: int = 100) -> list[dict]:
    """Get experience memories across ALL sessions (lifetime view)."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM experience_memory
               WHERE is_active = 1
               ORDER BY confidence_weight DESC, times_observed DESC
               LIMIT ?""",
            (limit,)
        ).fetchall()
        return rows_to_dicts(rows)


def get_lifetime_memories_summary() -> dict:
    """Get aggregate memory stats across all sessions."""
    with get_db() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) as active,
                AVG(confidence_weight) as avg_confidence,
                MAX(times_observed) as max_observed,
                MIN(created_at) as oldest,
                MAX(created_at) as newest
            FROM experience_memory
        """).fetchone()
        return dict_from_row(row) if row else {}


def get_lifetime_journals(limit: int = 50) -> list[dict]:
    """Get journal entries across ALL sessions."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM mind_journal_entries
               ORDER BY journal_date DESC, entry_id DESC
               LIMIT ?""",
            (limit,)
        ).fetchall()
        return rows_to_dicts(rows)


def get_lifetime_reflections(limit: int = 50) -> list[dict]:
    """Get action reflections across ALL sessions."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM action_reflections
               ORDER BY reflection_id DESC LIMIT ?""",
            (limit,)
        ).fetchall()
        return rows_to_dicts(rows)


def get_lifetime_reflection_summary() -> dict:
    """Reflection grade distribution across ALL sessions."""
    with get_db() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN overall_grade = 'A' THEN 1 ELSE 0 END) as grade_a,
                SUM(CASE WHEN overall_grade = 'B' THEN 1 ELSE 0 END) as grade_b,
                SUM(CASE WHEN overall_grade = 'C' THEN 1 ELSE 0 END) as grade_c,
                SUM(CASE WHEN overall_grade = 'D' THEN 1 ELSE 0 END) as grade_d,
                SUM(CASE WHEN overall_grade = 'F' THEN 1 ELSE 0 END) as grade_f
            FROM action_reflections
        """).fetchone()
        return dict_from_row(row) if row else {}


def get_lifetime_truth_reviews(limit: int = 50) -> list[dict]:
    """Get truth reviews across ALL sessions."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM news_truth_reviews
               ORDER BY review_id DESC LIMIT ?""",
            (limit,)
        ).fetchall()
        return rows_to_dicts(rows)


def get_lifetime_truth_summary() -> dict:
    """Truth review accuracy across ALL sessions."""
    with get_db() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN verdict = 'correct' THEN 1 ELSE 0 END) as correct,
                SUM(CASE WHEN verdict = 'wrong' THEN 1 ELSE 0 END) as wrong,
                SUM(CASE WHEN verdict = 'mixed' THEN 1 ELSE 0 END) as mixed,
                SUM(CASE WHEN verdict = 'unclear' THEN 1 ELSE 0 END) as unclear,
                SUM(CASE WHEN verdict = 'faded' THEN 1 ELSE 0 END) as faded,
                SUM(CASE WHEN verdict = 'pending' THEN 1 ELSE 0 END) as pending
            FROM news_truth_reviews
        """).fetchone()
        return dict_from_row(row) if row else {}


def get_lifetime_milestones(limit: int = 50) -> list[dict]:
    """Get milestones across ALL sessions."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM milestones
               ORDER BY milestone_id DESC LIMIT ?""",
            (limit,)
        ).fetchall()
        return rows_to_dicts(rows)


def get_recurring_patterns(pattern_type: str = "mistake", limit: int = 10) -> list[dict]:
    """Find recurring patterns in journal entries (mistakes, lessons, etc.).

    Scans all journal entries across all sessions to find repeated themes.
    """
    with get_db() as conn:
        col = "mistakes_text" if pattern_type == "mistake" else "lessons_text"
        rows = conn.execute(
            f"""SELECT {col} as text, journal_date, session_id
                FROM mind_journal_entries
                WHERE {col} IS NOT NULL AND {col} != ''
                ORDER BY journal_date DESC
                LIMIT ?""",
            (limit * 3,)
        ).fetchall()
        return rows_to_dicts(rows)


def get_lifetime_daily_reviews(limit: int = 50) -> list[dict]:
    """Get daily reviews across ALL sessions."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM daily_reviews
               ORDER BY review_id DESC LIMIT ?""",
            (limit,)
        ).fetchall()
        return rows_to_dicts(rows)


# ---------------------------------------------------------------------------
# capital_ledger helpers (v7.4.1 Financial Continuity)
# ---------------------------------------------------------------------------

def insert_capital_event(event_type: str, amount: float, balance_after: float = None,
                         reason: str = None, session_id: int = None,
                         version: str = None, notes: str = None) -> int:
    """Record a capital event (funding, refill, withdrawal, correction)."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO capital_ledger
               (timestamp, event_type, amount, balance_after, reason, session_id, version, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (now, event_type, amount, balance_after, reason, session_id, version, notes)
        )
        return cursor.lastrowid


def get_capital_events(limit: int = 50) -> list[dict]:
    """Get all capital events."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM capital_ledger ORDER BY ledger_id DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return rows_to_dicts(rows)


def get_capital_summary() -> dict:
    """Capital event summary."""
    with get_db() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) as total_events,
                SUM(CASE WHEN event_type = 'refill' THEN amount ELSE 0 END) as total_refills,
                SUM(CASE WHEN event_type = 'withdrawal' THEN amount ELSE 0 END) as total_withdrawals,
                SUM(CASE WHEN event_type = 'initial_funding' THEN amount ELSE 0 END) as initial_funding
            FROM capital_ledger
        """).fetchone()
        return dict_from_row(row) if row else {}


# ---------------------------------------------------------------------------
# lifetime_portfolio helpers (v7.4.1 Financial Continuity)
# ---------------------------------------------------------------------------

def get_lifetime_portfolio() -> dict | None:
    """Get the singleton lifetime portfolio state."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM lifetime_portfolio WHERE id = 1").fetchone()
        return dict_from_row(row)


def upsert_lifetime_portfolio(**kwargs) -> None:
    """Update or create the lifetime portfolio singleton.
    On INSERT, cash MUST be explicitly provided — no hidden $100 fallback."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        existing = conn.execute("SELECT id FROM lifetime_portfolio WHERE id = 1").fetchone()
        if existing:
            if not kwargs:
                return  # nothing to update
            sets = ", ".join(f"{k} = ?" for k in kwargs)
            vals = list(kwargs.values())
            conn.execute(f"UPDATE lifetime_portfolio SET {sets}, updated_at = ? WHERE id = 1",
                         vals + [now])
        else:
            if "cash" not in kwargs:
                raise ValueError("lifetime_portfolio INSERT requires explicit 'cash' — no hidden defaults")
            kwargs["updated_at"] = now
            kwargs["id"] = 1
            cols = ", ".join(kwargs.keys())
            ph = ", ".join("?" for _ in kwargs)
            conn.execute(f"INSERT INTO lifetime_portfolio ({cols}) VALUES ({ph})",
                         list(kwargs.values()))


def sync_lifetime_portfolio(cash: float, btc_holdings: float, avg_entry: float,
                             price: float, realized_pnl: float,
                             total_trades: int, wins: int, losses: int,
                             holds: int, blocked: int) -> None:
    """Sync lifetime portfolio from current auto_trader state."""
    equity = cash + btc_holdings * price
    unrealized = btc_holdings * (price - avg_entry) if btc_holdings > 0 and avg_entry > 0 else 0

    existing = get_lifetime_portfolio()
    peak = max(equity, existing.get("peak_equity", 0) if existing else equity)
    dd = ((peak - equity) / peak * 100) if peak > 0 else 0
    max_dd = max(dd, existing.get("max_drawdown_pct", 0) if existing else 0)

    upsert_lifetime_portfolio(
        cash=round(cash, 4),
        btc_holdings=round(btc_holdings, 8),
        avg_entry_price=round(avg_entry, 2),
        total_equity=round(equity, 4),
        realized_pnl=round(realized_pnl, 6),
        unrealized_pnl=round(unrealized, 6),
        total_trades=total_trades,
        total_wins=wins,
        total_losses=losses,
        total_holds=holds,
        total_blocked=blocked,
        peak_equity=round(peak, 4),
        max_drawdown_pct=round(max_dd, 2),
        last_price=round(price, 2),
    )


def get_trades_by_scope(scope: str = "session", session_id: int = None,
                         version: str = None, limit: int = 100) -> tuple[list[dict], int]:
    """Get trades filtered by scope: session, version, or lifetime."""
    with get_db() as conn:
        if scope == "lifetime":
            rows = conn.execute(
                "SELECT * FROM trade_ledger ORDER BY trade_id DESC LIMIT ?",
                (limit,)
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) as c FROM trade_ledger").fetchone()["c"]
        elif scope == "version" and version:
            rows = conn.execute(
                """SELECT * FROM trade_ledger WHERE version_tag = ?
                   ORDER BY trade_id DESC LIMIT ?""",
                (version, limit)
            ).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) as c FROM trade_ledger WHERE version_tag = ?",
                (version,)
            ).fetchone()["c"]
        elif scope == "session" and session_id:
            rows = conn.execute(
                """SELECT * FROM trade_ledger WHERE session_id = ?
                   ORDER BY trade_id DESC LIMIT ?""",
                (session_id, limit)
            ).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) as c FROM trade_ledger WHERE session_id = ?",
                (session_id,)
            ).fetchone()["c"]
        else:
            # No valid scope/id — return empty, not lifetime
            return [], 0
        return rows_to_dicts(rows), total


def get_trade_stats_by_scope(scope: str = "session", session_id: int = None,
                              version: str = None) -> dict:
    """Get trade stats by scope."""
    with get_db() as conn:
        where = ""
        params = []
        if scope == "lifetime":
            pass  # no WHERE — all trades
        elif scope == "version" and version:
            where = "WHERE version_tag = ?"
            params = [version]
        elif scope == "session" and session_id:
            where = "WHERE session_id = ?"
            params = [session_id]
        else:
            # Invalid scope/missing id — return empty stats
            return {"total": 0, "buys": 0, "sells": 0, "holds": 0, "wins": 0,
                    "losses": 0, "total_pnl": 0, "win_rate": 0, "scope": scope}

        row = conn.execute(f"""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN action = 'BUY' THEN 1 ELSE 0 END) as buys,
                SUM(CASE WHEN action = 'SELL' THEN 1 ELSE 0 END) as sells,
                SUM(CASE WHEN action = 'HOLD' THEN 1 ELSE 0 END) as holds,
                SUM(CASE WHEN action = 'SELL' AND pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN action = 'SELL' AND pnl <= 0 THEN 1 ELSE 0 END) as losses,
                SUM(CASE WHEN action = 'SELL' THEN pnl ELSE 0 END) as total_pnl,
                AVG(CASE WHEN action = 'SELL' THEN pnl END) as avg_pnl,
                MAX(CASE WHEN action = 'SELL' THEN pnl END) as best_trade,
                MIN(CASE WHEN action = 'SELL' THEN pnl END) as worst_trade
            FROM trade_ledger {where}
        """, params).fetchone()
        result = dict_from_row(row) if row else {}
        sells = result.get("sells", 0) or 0
        wins = result.get("wins", 0) or 0
        result["win_rate"] = round(wins / sells * 100, 1) if sells > 0 else 0
        result["scope"] = scope
        return result


# ---------------------------------------------------------------------------
# crowd_sentiment_events helpers (v7.5 Crowd Sentiment)
# ---------------------------------------------------------------------------

def insert_crowd_sentiment_event(source: str, event_id: str, question: str,
                                  crowd_probability: float, bias: str,
                                  confidence_strength: float,
                                  notes_json: str = None) -> int:
    """Insert a crowd sentiment snapshot."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO crowd_sentiment_events
               (timestamp, source, event_id, question, crowd_probability,
                bias, confidence_strength, notes_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (now, source, event_id, question, crowd_probability,
             bias, confidence_strength, notes_json)
        )
        return cursor.lastrowid


def get_crowd_sentiment_events(limit: int = 50) -> list[dict]:
    """Get recent crowd sentiment events, newest first."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM crowd_sentiment_events
               ORDER BY id DESC LIMIT ?""",
            (limit,)
        ).fetchall()
        return rows_to_dicts(rows)


def get_crowd_sentiment_latest() -> dict | None:
    """Get the most recent crowd sentiment event."""
    with get_db() as conn:
        row = conn.execute(
            """SELECT * FROM crowd_sentiment_events
               ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        return dict_from_row(row)
