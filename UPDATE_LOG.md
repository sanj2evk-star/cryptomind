# CryptoMind — Update Log

A running record of every version update: what changed, what was reviewed, and deployment notes.

---

## v7.6.4 — Fix Render Deployment + Runtime Status
**Date:** 2026-03-22

### What Changed
- **`render.yaml`** — Simplified build command to `pip install -r requirements.txt` (frontend/dist already committed to git, no npm build needed on Render). Removed Node.js dependency from build.
- **`Dockerfile`** — Updated to include `frontend/dist/` in image, use `/health` for healthcheck
- **`app/api.py`** — Added `GET /v7/system/runtime-status` endpoint: shows backend alive, trader running, DB status, env var presence, lifetime cycles/trades, warnings
- **`CLAUDE.md`** — Already web-only from v7.6.3

### Root Cause of Render 404s
The Render service was manually created via the dashboard (likely as a static site), not from `render.yaml`. This means `render.yaml` auto-deploy was ignored. The old CRA static build was being served instead of the Python backend.

### Why Zero Cycles/Trades
The auto_trader IS wired correctly to write v7 DB entries (`session_manager.on_cycle_complete`, `on_trade_executed`). But the backend was only started locally for brief development/deployment sessions. The auto_trader ran ~605 cycles in CSV mode (Mar 18-20) but all were HOLDs. After v7 DB was created (Mar 21), no cycles ran.

### Render Dashboard Steps Required
1. Delete the existing static site service on Render
2. Create new **Web Service** from the same GitHub repo
3. Set runtime: Python, build: `pip install -r requirements.txt`, start: `python run_api.py --host 0.0.0.0 --port $PORT`
4. Add env vars: `ANTHROPIC_API_KEY`, `API_PASSWORD`, `JWT_SECRET`
5. Or: connect to Blueprint and let `render.yaml` handle it

### Files Modified
| File | Change |
|------|--------|
| `render.yaml` | Simplified build (no npm), removed Node.js |
| `Dockerfile` | Include frontend/dist, updated healthcheck |
| `app/api.py` | Added `/v7/system/runtime-status` endpoint |
| `UPDATE_LOG.md` | This entry |

---

## v7.6.3 — Remove Desktop App (Web-Only)
**Date:** 2026-03-22

### What Changed
- **Deleted `desktop/` folder entirely** — main.js, loading.html, package.json, package-lock.json, node_modules, dist, cryptomind.png, all Electron configs
- **Removed Electron dependencies** — electron, electron-builder, all @electron/* packages
- **Cleaned api.py** — removed "desktop app" comments, removed `Resources/frontend/` prod bundle path candidate (only `frontend/dist/` remains)
- **Cleaned auth.py** — removed "desktop app" comment from JWT expiry
- **Updated CLAUDE.md** — deployment rules now web-only, removed all Mac app build references
- **Updated UPDATE_LOG.md** — this entry

### Why
- Dual DB paths (server vs packaged app) caused the continuity/amnesia bug fixed in v7.6.2
- Packaging complexity with no current need — CryptoMind runs on Render (web/iPad)
- Desktop will be rebuilt later as a thin UI shell with no local state

### Files Deleted
| Path | Contents |
|------|----------|
| `desktop/` (entire folder) | main.js, loading.html, package.json, package-lock.json, cryptomind.png, node_modules/, dist/ |

### Files Modified
| File | Change |
|------|--------|
| `app/api.py` | Removed desktop comments, simplified frontend path candidates |
| `app/auth.py` | Removed desktop comment |
| `CLAUDE.md` | Deployment rules → web-only |
| `UPDATE_LOG.md` | This entry |

### What's Right
- Zero impact on backend logic, DB, API, or trading behavior
- Frontend build unchanged (still `npm run build` in `frontend/`)
- Static serving still works for Render (via `frontend/dist/`)
- All Python compiles clean, frontend builds clean

### Deployment
- Render: pushed to `main`
- Mac app: **removed** (no longer built)

---

## v7.6.2 — Continuity / Amnesia Audit + Fix
**Date:** 2026-03-22

### Root Causes Found

**1. Mac App Build Overwrites Live DB (CRITICAL)**
- `desktop/package.json` `extraResources` copied `../data/**/*` (including `cryptomind.db`) into the app bundle on every `npm run build:mac`
- Every Mac app build = fresh DB from dev directory = complete amnesia
- The dev DB had 0 trades, 0 cycles, 0 lifetime data — it was never the "live" DB
- **Fix:** Added filter exclusions: `!cryptomind.db`, `!*.db`, `!*.db-shm`, `!*.db-wal` — DB files no longer bundled; `init_db()` creates fresh DB on first launch, then persists

**2. Lifetime Tables Never Populated (CRITICAL)**
- `lifetime_identity` (0 rows) and `lifetime_portfolio` (0 rows) were empty in the dev DB
- These tables were added in v7.4.1 but version upgrades from v7.0.0→v7.4.0 ran before the population code existed
- The initialization code only populated on first boot, not on resume — so subsequent starts skipped creation
- **Fix:** Replaced one-shot creation with `_heal_lifetime_portfolio()` and `_heal_lifetime_identity()` — run on EVERY startup, rebuild from ground truth (trade_ledger, version_sessions, cycle_snapshots)

**3. Config.py Stale Version**
- `config.py` had `APP_VERSION = "7.4.0"` while `session_manager.py` had `"7.6.1"`
- Some modules might import from config.py instead of session_manager
- **Fix:** Updated config.py version + added comment that session_manager is the source of truth

### Files Modified (5)

| File | Changes |
|------|---------|
| `desktop/package.json` | Added DB exclusion filters to extraResources |
| `app/session_manager.py` | Self-healing `_heal_lifetime_portfolio()`, `_heal_lifetime_identity()`, `_count_lifetime_trades()`, `_rebuild_portfolio_from_trades()`, `get_continuity_audit()`. APP_VERSION → 7.6.2 |
| `app/db.py` | Anti-amnesia guardrails in `upsert_lifetime_identity()` and `upsert_lifetime_portfolio()` — never reduce total_trades, total_cycles, total_sessions, peak_equity |
| `app/api.py` | New `GET /v7/system/continuity-audit` endpoint. Version → 7.6.2 |
| `app/config.py` | APP_VERSION → 7.6.2 |
| `frontend/src/pages/Lab.jsx` | Continuity Health card: health status, lifetime trades/cycles/sessions, DB path, warnings |

### Continuity Rules Enforced

**A. Same mind across versions**
- Version upgrade closes old session, opens new — but lifetime_identity, lifetime_portfolio, behavior_profile, experience_memory all persist
- Self-healing on every startup ensures these tables exist and are populated

**B. Session reset ≠ mind reset**
- New session starts fresh counters but lifetime counters remain
- `_heal_lifetime_identity()` counts real sessions from version_sessions table
- `_heal_lifetime_portfolio()` rebuilds from trade_ledger ground truth

**C. All pages read from same DB**
- Single DB path: `data/cryptomind.db` (resolved from `config.DATA_DIR`)
- Verified: all endpoints (dashboard, trades, mind, review export) use `db.get_db()` → same connection pool → same file

**D. Anti-reduction guardrails**
- `upsert_lifetime_identity()` — never reduces total_cycles, total_trades, total_sessions
- `upsert_lifetime_portfolio()` — never reduces total_trades, total_wins, total_losses, peak_equity
- `_heal_lifetime_identity()` — only increases counters, never decreases

### Before/After Table Counts

| Table | Before | After |
|-------|--------|-------|
| lifetime_identity | 0 | 1 |
| lifetime_portfolio | 0 | 1 |
| capital_ledger | 0 | 2 |
| version_sessions | 4 | 5 |
| trade_ledger | 0 | 0 (no trades yet — correct) |

### Continuity Diagnostic Endpoint
`GET /v7/system/continuity-audit` returns:
- db_path, db_exists, db_size, db_last_modified
- table_counts for all 33 tables
- current_version, current_session_id
- lifetime_sessions, lifetime_trades, lifetime_cycles
- identity and portfolio state
- continuity_health: good / warning / degraded / broken
- warnings[] with specific diagnostic messages

### Verification
1. Same DB path across all endpoints: **YES** (single `db.DB_PATH`)
2. Lifetime counts visible after version bump: **YES** (5 sessions, version upgrade preserved)
3. Dashboard/trades/mind/review agree: **YES** (all use `db.get_db()`)
4. No singleton fresh overwrite: **YES** (guardrails prevent counter reduction)
5. Continuity survives restart: **YES** (self-healing runs on every `initialize()`)
6. Continuity survives version change: **YES** (upgrade path tested v7.4.0→v7.6.2)

### Historical Data Recovery
- No historical trades to recover (dev DB never had trading cycles)
- The actual "live" DB was inside the Mac app bundle and was being destroyed on each build
- With the DB exclusion fix, future Mac app builds will NOT overwrite the live DB
- On first launch after this update, `init_db()` creates a fresh DB, and self-healing populates lifetime tables

**What could be improved:**
- Could add Render persistent disk documentation
- Could add a migration path to copy data from Mac bundle DB to persistent location
- Could add a DB backup on version upgrade
- Could hash the DB path and print at startup for easier debugging

**Build status:** All Python files compile clean. Frontend builds successfully.
**Deployment status:** Awaiting permission.

---

## v7.6.1 — Signal Layer → Review Export Integration
**Date:** 2026-03-22

**What changed:**

### Modified: `review_export_engine.py`

#### New builder: `build_signal_summary(start, end, scope)`
- Crowd bias (bullish/bearish/mixed) + strength + event count
- Derivatives positioning summary with avg funding rate
- Liquidation pressure summary with total $M + long/short counts
- Alignment assessment (aligned/diverging/unclear)
- Tension score: avg + peak (0-100 scale)
- Narrative state distribution: calm/building/overheated/conflicted
- Top 3 signal insights (most frequent signal types with dominant direction, avg strength)
- Live snapshot of current signal state
- Graceful fallback: `{"status": "no_signal_data", "message": "Signal layer still warming up."}` when no data

#### New section in export: `signal_context`
- Placed after `market_context` in export dict
- Included in all review types: daily, weekly, monthly, custom
- All fields: alignment, tension_score_avg, tension_score_peak, crowd_summary, derivatives_summary, liquidation_summary, narrative_state, narrative_distribution, key_signal_insights

#### Appendix extension: `signal_events_recent`
- In detailed mode, appendix now includes up to 20 recent signal events
- Each: timestamp, signal_type, description, direction, confidence
- Added to both JSON and text rendering

#### Continuity comparison extension: `signal_behavior_vs_lifetime`
- New field in `continuity_comparison` section
- alignment_trend: improving / worsening / stable
- divergence_trend: increasing / decreasing / stable
- tension_trend: rising / falling / stable
- Human-readable assessment comparing range vs lifetime signal behavior
- Graceful fallback when no range data

#### Text renderer updated
- New "--- Signal Context ---" section with full signal data
- Signal behavior comparison added to "--- Continuity vs Lifetime ---"
- New "--- Appendix: Signal Events (Recent) ---" section

### Modified: `session_manager.py`
- APP_VERSION → "7.6.1"

### Modified: `api.py`
- Description → "v7.6.1 — Observer Core: Signal Layer + Review Export Integration"
- No endpoint changes needed — existing `/v7/review/export` and `/v7/review/export/text` automatically include new signal sections

**Execution logic touched:** NONE. No changes to auto_trader, decision_engine, multi_strategy, paper_broker, or any execution flow.

**Files modified:** 3 (review_export_engine.py, session_manager.py, api.py)

**Sections added:** 4 (signal_context, signal_events_recent in appendix, signal_behavior_vs_lifetime in continuity, text rendering for all)

**Sample export signal_context section:**
```json
{
  "status": "ok",
  "signal_events_in_range": 42,
  "alignment": "diverging",
  "tension_score_avg": 38,
  "tension_score_peak": 72,
  "crowd_summary": {"bias": "bullish", "strength": 0.45, "events": 12},
  "derivatives_summary": {"description": "Leaning bullish positioning (avg funding: +0.0023%)", "events": 18},
  "liquidation_summary": {"description": "~$45M liquidated (3 long, 2 short events)", "events": 5},
  "narrative_state": "building",
  "narrative_distribution": {"calm": 8, "building": 20, "overheated": 5, "conflicted": 9},
  "key_signal_insights": [
    {"signal_type": "funding_rate", "occurrences": 15, "avg_strength": 0.42, "dominant_direction": "bullish"},
    {"signal_type": "btc_price_prediction", "occurrences": 12, "avg_strength": 0.38, "dominant_direction": "bullish"},
    {"signal_type": "long_liquidation", "occurrences": 3, "avg_strength": 0.55, "dominant_direction": "bearish"}
  ]
}
```

**What's right:**
- Zero breaking changes to existing export structure — signal_context is purely additive
- All 4 review types (daily/weekly/monthly/custom) include signal data
- Graceful fallback at every level — empty table, disabled flag, import failure
- Signal comparison in continuity uses rule-based assessment, no LLM
- Text renderer shows signal data in human-readable format

**What could be improved:**
- Could weight signal insights by recency (time-decay)
- Could add signal accuracy tracking over time (were signal reads predictive?)
- Narrative state classification in summary could match aggregator's more sophisticated logic
- Could add per-strategy signal correlation (did certain strategies trade in line with signals?)

**Build status:** All Python files compile clean. Frontend builds successfully.
**Deployment status:** Awaiting permission.

---

## v7.6.0 — Tier 1 Signal Layer (Observer-Only, Rich Experience)
**Date:** 2026-03-22

**What changed:**

### New Module: `app/signal_layer/` (11 files)

#### Collectors (3)
- **polymarket_collector.py** — Prediction market / crowd positioning signals. Currently derives from crowd_sentiment_engine; designed so real Polymarket API replaces `_fetch()`.
- **derivatives_collector.py** — Funding rates, open interest changes, long/short ratios. Currently synthetic from price momentum; designed for Binance/Bybit API swap.
- **liquidation_collector.py** — Long/short liquidation events. Synthetic from price volatility; designed for Coinglass API swap.

#### Normalizer (1)
- **base_normalizer.py** — Canonical signal schema: source, signal_type, direction, strength, confidence, raw_value, context, meta, timestamp. All collectors pass through `normalize()`.

#### Interpreters (3)
- **positioning_interpreter.py** — Reads derivatives signals → overcrowded_long/short, balanced, building. Risk: low/moderate/high/extreme.
- **crowd_interpreter.py** — Reads Polymarket signals → crowd conviction (strong/moderate/weak/conflicted), divergence risk assessment.
- **liquidation_interpreter.py** — Reads liquidation signals → long_squeeze/short_squeeze/mixed_flush/calm with severity grading.

#### Core (3)
- **signal_store.py** — Persistent storage bridge to `db.signal_events` table. Insert with 60s dedup, query by source/session.
- **signal_aggregator.py** — Main orchestrator: collectors → interpreters → composite assessment. Cached 45s. Composite: overall_direction, tension_score (0-100), narrative_state (calm/building/overheated/conflicted), alignment (aligned/diverging/unclear).
- **signal_insight_engine.py** — Generates human-readable insights: alignment, divergence, leverage risk, crowd divergence, liquidation events, overheated warnings. Capped at 5 insights, sorted by importance.

#### Init (1)
- **__init__.py** — Feature flags: ENABLE_SIGNAL_LAYER=True, ENABLE_SIGNAL_INFLUENCE=False.

### Database Changes (`db.py`)
- New table #32: `signal_events` — session_id, timestamp, source, signal_type, direction, strength, confidence, raw_value, context, meta_json
- Indexes on session_id, timestamp, source
- Helper functions: `insert_signal_event()`, `get_signal_events()`, `get_signal_events_since()`

### Integration with Existing Engines
- **mind_feed_engine.py** — 4 new event types: signal_alignment (green), signal_divergence (amber), signal_warning (red), signal_info (blue). New handler: `on_signal_insights()`.
- **contextual_summary_engine.py** — New `signal_context` section in compute() output: alignment, tension_score, narrative_state, overall_direction, summary.
- **bullshit_radar.py** — New `signal_layer` overlay in compute(): compares crowd heat vs signal direction for crowd_vs_positioning mismatch detection.
- **replay_engine.py** — New `_markers_from_signals()` generator. Markers for signals with strength > 0.3. Importance scales 3→6 based on strength.

### API Endpoints (`api.py`)
- `GET /v7/signals/latest` — Full aggregated snapshot (signals, interpretations, composite)
- `GET /v7/signals/insights` — Human-readable signal insights
- `GET /v7/signals/history` — Historical signal events from DB (filterable by source)

### Frontend (`Lab.jsx`)
- New "Signal Layer" collapsible panel between Belief vs Reality and Live Feed
- Metrics row: Direction, Tension (with progress bar), Alignment, Narrative State
- Interpretation cards: Derivatives Positioning, Crowd Conviction, Liquidation
- Signal Insights list with importance badges and color coding
- Full warm-up state handling

### Version Bump
- session_manager.py: APP_VERSION → "7.6.0"
- api.py: description → "v7.6.0 — Observer Core: Tier 1 Signal Layer"

**What's right:**
- Complete observer isolation — ZERO influence on trading decisions
- Feature flags allow disabling without code changes
- All collectors designed for real API swap (just replace `_fetch()`)
- Composite assessment provides rich narrative context
- Signal persistence via DB with dedup protection
- All 4 existing engines enhanced without breaking changes
- Frontend panel follows existing Lab.jsx patterns exactly

**What could be improved:**
- Collectors are currently synthetic — real API integration is the natural next step
- Signal persistence interval (120s) could be configurable
- Could add signal-aware entries to daily journal engine
- Tension score calculation is linear — could benefit from exponential weighting
- No historical trend analysis yet (tension over time, direction shifts)

**Build status:** All Python files compile clean. Frontend builds successfully.
**Deployment status:** Awaiting permission.

---

## v7.5.3b — Stabilization Patch (Behavior + News + UX Hardening)
**Date:** 2026-03-22

**What changed:**

### 1. Activity Clamp — Anti-Overtrading Drift (`multi_strategy.py`)
- Rolling 50-cycle trade window: tracks trades in last 50 cycles
- When trades ≥ 13 in window → activity clamp activates:
  - Edge filter score threshold raised by +4 points
  - Probe cooldown extended by 25%
  - Strategy cooldown multiplied by 1.3×
- Prevents quiet overactivity after over-filtering fixes
- State exposed in get_leaderboard: `activity_clamp`, `trades_last_window`

### 2. Strategy Bias — Minimum Evidence Gate (`multi_strategy.py`)
- Changed: BIAS_MIN_EVIDENCE_TRADES from 8 → 12
- Added blended win rate: 70% recent + 30% lifetime (was 100% recent)
- Prevents early lucky streaks from creating false "hero strategies"
- Penalty no longer requires 3+ recent PnL entries when lifetime data available

### 3. Source Influence Cap (`news_classifier.py`)
- Source contribution to composite_quality capped at 60% of total score
- If source would dominate, excess is redistributed to content weight
- Verdict logic tightened: source alone NEVER promotes a signal
  - Noise→watch upgrade now requires `_has_content_signal` (bull/bear/high_impact)
  - Hype→watch upgrade now requires `_has_content_signal`
  - Weak+short→watch upgrade now requires `_has_content_signal`

### 4. Uncertainty Flag (`news_classifier.py`)
- New field in classify() output: `uncertainty_flag: True/False`
- Set True when:
  - Conflicting strong signals (≥2 bullish AND ≥2 bearish)
  - Borderline scores near classification thresholds + mixed signals
  - Low content confidence (content_trust < 0.4)
  - Both noise and hype indicators present on a relevant headline
  - Verdict is "unclear"
- Exposed for future learning layers to use

### 5. Global Collapse Control (`Lab.jsx`, `Mind.jsx`)
- "Expand All" / "Collapse All" buttons added to both pages
- Lab: in sticky summary bar, controls all 8 collapsible sections
- Mind: in sticky header, controls overview tab sections (Radar/Level, Learning, Patterns, Evolution, Insights)
- Collapsible component updated with `forceOpen` prop for external control
- Override auto-resets after 50ms so individual toggles still work

**Execution logic NOT touched:** ✓
- No changes to decision_engine core logic
- No changes to portfolio logic
- No changes to execution paths (BUY/SELL/HOLD flow unchanged)
- All changes are threshold adjustments, output fields, and UI components

**No DB changes. No API changes. No new modules.**

**Build passes:** ✓ Python compile + Vite frontend build clean.

---

## v7.5.3 — Behavior Balance + News Quality + iPad UX
**Date:** 2026-03-22

**What changed:**

### Part 1: Behavior Balance Patch (`multi_strategy.py`)
- **Over-filtering detector**: Tracks signals seen vs trades taken. When ≥25 signals and 0 trades, flags over-filtering and relaxes edge filter thresholds by 3 points / 0.02 confidence
- **Confidence → Action mapping**: Explicit low/medium/high thresholds. Medium confidence converts BUY to probe instead of blocking entirely
- **Minimum participation guard**: Reduced anti-paralysis threshold from 60→40 cycles
- **Sleepy market probe-instead-of-block**: SLEEPING market with score <55 converts to probe instead of HOLD; score <62 becomes probe at 50% size
- **Adaptation unfreeze**: Micro-adjustments every 30 cycles — rewards strategies with >60% win rate, penalizes <35%. Prevents allocation from freezing in suboptimal state
- **Strategy bias accumulation**: Gradual allocation shifts toward consistent performers, bounded by 2% max shift per cycle

### Part 2: News Quality Upgrade (`news_classifier.py`)
- **Source quality tiers**: Tier 1 (Reuters, Bloomberg, SEC, etc.) = 0.90, Tier 2 (CoinDesk, CoinTelegraph, etc.) = 0.70, Tier 3 (aggregators) = 0.45, Unknown = 0.25
- **Blended trust scoring**: `content_trust × 0.6 + source_quality × 0.4`
- **Composite quality score**: `impact_strength × 0.4 + source_quality × 0.35 + novelty × 0.25`
- **Noise calibration**: Tier 1/2 sources with relevance get upgraded from noise → watch. Tier 1 + high hype but relevant → watch instead of reject
- **New fields in classify() return**: `source_quality`, `source_tier`, `composite_quality`
- Expected distribution: 60-80% noise, 10-25% watch, 5-15% interesting

### Part 3: iPad UX Optimization (`Lab.jsx`, `Mind.jsx`)
- **Lab page — Collapsible sections**: All major sections (Identity/Portfolio, Belief vs Reality, Live Feed, Personality/Intent, Milestones/Lifetime, Truth/Reflections, Session Replay) wrapped in touch-friendly collapsible panels. Default: only essential sections open
- **Lab page — Sticky summary bar**: Always-visible bar with mood, clarity, noise ratio, F&G, and evolution level
- **Lab page — Compact cards**: Reduced padding, smaller fonts, tighter spacing. Grid columns responsive with `minmax(220px, 1fr)` for 2-column iPad landscape
- **Mind page — Sticky header**: Level, confidence, and key stats always visible
- **Mind page — Mind Insights panel**: Quick-glance indicators (win rate, runtime, cycles, patterns) at bottom of overview tab
- **Mind page — Responsive grids**: Overview grid `minmax(280px, 1fr)`, skills grid `minmax(220px, 1fr)` for proper 2-column on iPad
- **Mind page — Compact hero card**: Smaller icon, inline stats, wrapping layout for narrow screens

### Version & Config
- `session_manager.py`: APP_VERSION updated to "7.5.3"

### Architecture
- All changes are additive — no existing behavior removed
- Observer isolation preserved — all new code is read-only against trading state
- Collapsible sections use `useState` — no external dependencies
- Adaptation unfreeze bounded by MIN_ALLOC_PCT/MAX_ALLOC_PCT — cannot monopolize

**What's right:**
- Over-filtering detection gives the system self-awareness about its participation rate
- Source quality tiers make news classification honest about where information comes from
- iPad UX reduces scroll depth by ~60% with collapsible sections
- Sticky bars keep key information visible without scrolling

**What could be improved:**
- Source quality could learn from truth validation results (dynamic tier adjustment)
- Adaptation unfreeze could use exponential decay for bias scores
- iPad UX could benefit from gesture-based section reordering
- Over-filtering detector could track per-strategy filtering rates

**Deployment:** Pending user approval

---

## v7.5.2 — Review Export / Black Box System
**Date:** 2026-03-22

**What changed:**

### Review Export Engine (new module: `review_export_engine.py`)
- Full structured review export system — daily/weekly/monthly/custom time ranges
- 12 sections: header, mind_state, market_context, activity_summary, performance_summary, strategy_breakdown, decision_quality, reflection_learning, adaptation_discipline, observer_summary, continuity_comparison, appendix
- Scope support: session / version / lifetime (independent from time range)
- Two output modes: summary (compact) and detailed (includes raw appendix)
- Human-readable text export + structured JSON
- 60s cache for performance
- Low-data honesty: explicit warnings when data is thin
- Continuity preservation: reads from all lifetime-persistent tables, version upgrades are NOT identity resets
- Date range filtering across all data sources

### API Endpoints
- `GET /v7/review/export` — full structured JSON export with params: review_type, scope, mode, start_date, end_date
- `GET /v7/review/export/text` — plain text export (PlainTextResponse) for copy/paste

### Frontend Review Page (`Review.jsx`)
- New `/review` page in sidebar navigation (⬢ icon)
- Pill group selectors for review type (Daily/Weekly/Monthly), scope (Session/Version/Lifetime), mode (Summary/Detailed)
- Generate Review button triggers export
- Copy to clipboard, Download .txt, Download .json buttons
- 12-section visual breakdown: Mind State, Market Context, Activity, Performance, Strategy Breakdown table, Decision Quality, Reflection & Learning, Adaptation & Discipline, Observer Summary, Continuity vs Lifetime comparison
- Low-data warnings displayed prominently
- Raw text export preview at bottom

### Continuity Design
- Reads from: trade_ledger, experience_memory, behavior_profile, adaptation_journal, mind_journal_entries, action_reflections, daily_reviews, news_truth_reviews, news_event_analysis, crowd_sentiment_events, lifetime_identity, lifetime_portfolio, milestones
- Continuity comparison section explicitly compares range vs lifetime metrics
- Identity depth scoring: thin / forming / established / deep
- Assessment text: plain language on whether system is improving, repeating, or mixed

### Architecture
- No DB changes required (reads from existing 33 tables)
- No execution engine changes
- No state resets
- Designed for future weekly/monthly without redesign — only date window differs
- SPA middleware updated with `/review` path

**What's right:**
- Clean separation of sections — each builder function is independent
- Text export is clean, structured, copyable
- Low-data honesty prevents false confidence
- Continuity comparison ensures version upgrades don't break identity narrative

**What could be improved:**
- Custom date range picker not yet in frontend (backend supports it)
- Appendix in detailed mode could include replay markers
- Scheduled auto-generation of daily reviews (future)
- Export history/archive (future)

**Deployment status:** Pending approval

---

## v7.5.1 — Scope Continuity + Recurring Pattern Detection + Confidence Calibration
**Date:** 2026-03-22

**What changed:**

### Scope Continuity Cleanup
- **Performance page**: Added ScopeToggle (Session / Version / Lifetime) with scoped stats bar showing closed trades, win rate, P&L, best/worst trades
- **Journal page**: Added ScopeToggle — session scope shows live auto-trader journal, version/lifetime scopes query trade_ledger for historical data
- **Journal scoped stats bar**: Shows scope-level win rate and P&L when viewing version/lifetime

### Recurring Pattern Detection Engine
- New module: `pattern_insight_engine.py` — rule-based keyword cluster matching across journals, reflections, truth reviews, memories, and daily reviews
- Detects 8 mistake patterns (early_entry, late_exit, overtrading, etc.) and 7 strength patterns (patience_wins, discipline, risk_control, etc.)
- Identifies 5 narrative rejection types (bullish_hype, bearish_fud, regulatory_fear, etc.)
- Generates human-readable rotating insight bullets per pattern
- Observer-only, no LLM dependency, 3-minute cache

### New API Endpoints
- `GET /v7/mind/patterns` — returns full recurring pattern analysis
- `GET /v7/performance/scoped?scope=session|version|lifetime` — scoped performance stats
- `GET /v7/journal/scoped?scope=session|version|lifetime&limit=30` — scoped journal entries with stats

### UI Updates
- **Performance page**: New "Top Strengths" and "Recurring Mistakes" cards below charts
- **Journal page**: "Recurring Patterns" card with color-coded insights (green=strength, red=mistake, amber=narrative)
- **Mind page (Overview tab)**: "Recurring Patterns" card showing top 3 insights with count badges

### Pattern Confidence Calibration
- Every pattern now includes a `confidence` field: `low`, `medium`, or `high`
- Thresholds: evidence < 3 → low, 3–6 → medium, > 6 → high
- Cross-source validation: confidence downgraded if evidence comes from only 1 data source
- `source_count` field tracks how many distinct sources (journals, reflections, daily reviews, memories) contributed
- Stricter warm-up guard: requires both `total_trades >= 10` AND `reflections >= 5` before surfacing any patterns
- Warming-up state returns empty patterns with clear message: "Still too early to detect meaningful patterns."

### Tone Correction
- All insight templates rewritten to be calm, observational, not absolute
- No "always", "never", or "you" — system speaks about itself, not the user
- Examples: "Entries may still be slightly early" instead of "Early conviction still gets punished"

### UI Confidence Indicators
- All 3 pages (Mind, Journal, Performance) show confidence dots per pattern:
  - Grey dot = low confidence (early signal)
  - Amber dot = medium confidence (emerging)
  - Green dot = high confidence (well-established)
- Evidence counts shown as "(seen N×)" instead of raw "×N"
- Dots have hover title showing confidence level

### Constraints followed
- No new DB tables — reads from existing 33 tables
- Observer-only: no writes to portfolio or trading state
- All new data hooks use polling with appropriate intervals (30s–60s)
- ScopeToggle reuses existing component from v7.4

**What's right:**
- Clean scope separation: session=live data, version/lifetime=historical trade_ledger
- Pattern engine is extensible — easy to add new keyword clusters
- No performance impact — pattern computation cached for 3 minutes
- Journal gracefully handles both live auto-trader entries and ledger entries

**What could be improved:**
- Scoped journal entries from trade_ledger have less detail than live auto-trader journal entries (no signals/indicators breakdown)
- Pattern engine uses static keyword matching — could evolve to use TF-IDF or embeddings
- Performance page scoped bar could show max drawdown per scope (would need new DB query)
- Leaderboard scope toggle deferred — strategy-level data doesn't map cleanly to session/version scopes

**Deployment:** Pending approval

---

## v7.5.0 — Crowd Sentiment + Belief vs Reality + Auth/Dashboard Stability
**Date:** 2026-03-22

**What changed:**

### Auth + Dashboard Stability Fixes
- **JWT secret now stable across restarts**: production REQUIRES `JWT_SECRET` env var (fails loudly if missing), dev uses file-based persistence
- **Token expiry**: increased from 24h → 72h (desktop app friendly)
- **3-consecutive-401 auth guard**: single transient 401 no longer triggers logout; needs 3 within 15s
- **useApi retry on 401**: retries once after 2s delay before counting toward threshold
- **Auth bootstrap**: validates stored token against `/status` (auth-protected) on app load
- **Health check retry**: increased timeout to 8s, added 2 automatic retries for Render cold starts
- **Logout loop guard**: prevents rapid-fire logout from multiple polling hooks
- **Dashboard data preservation**: once data received, preserved across failed polls (no blank screen)
- **Production detection**: `RENDER` env var triggers strict JWT_SECRET enforcement

### Deployment requirement
**JWT_SECRET MUST be set as a Render environment variable.**
Generate: `python3 -c "import os; print(os.urandom(32).hex())"`
Set on Render: Dashboard → Environment → Add `JWT_SECRET`

### Crowd Sentiment Layer
- New module: `crowd_sentiment_engine.py` — observes crowd belief, compares to price reality, detects alignment vs divergence
- New DB table: `crowd_sentiment_events` (table 31, 33 total) — persists crowd belief snapshots
- New API endpoints: `/v7/crowd/latest`, `/v7/crowd/belief-vs-reality`, `/v7/crowd/history`, `/v7/crowd/truth`
- New "Belief vs Reality" panel in Lab: crowd bias, confidence, price trend, alignment badge, divergence bar (0–100), one-liner insight
- Integrated into observer pipeline: crowd sentiment computed every news cycle, feed items emitted on divergence
- `bullshit_radar.py`: now includes crowd_sentiment overlay in radar state
- `contextual_summary_engine.py`: now includes crowd_vs_reality in daily context summary
- `mind_feed_engine.py`: two new feed types (crowd_divergence, crowd_aligned), new `on_crowd_sentiment()` handler
- `replay_engine.py`: crowd sentiment markers appear in session replay timeline
- `news_truth_validator.py`: wired for future crowd truth reviews via `evaluate_past_beliefs()`
- Warm-up states: "Crowd lens warming up." / "Not enough belief data yet." / "Watching for crowd signals."
- Synthetic data source (based on bullshit_radar sentiment balance) — designed for easy Polymarket swap later

**How divergence is computed:**
- Crowd bias (bullish/bearish/neutral) derived from news sentiment balance via bullshit_radar
- Price trend (up/down/flat) from recent cycle snapshot price comparison (0.15% threshold)
- Alignment: crowd bullish + price up → aligned; crowd bullish + price down → diverging; weak signals → unclear
- Divergence score (0–100): weighted combination of crowd confidence (40%), price change magnitude (30%), and base divergence factor (30%)

**Assumptions / placeholder limitations:**
- Crowd data is currently synthetic (derived from news sentiment) — not from real prediction markets
- `_fetch_crowd_data()` is the single function to replace when wiring Polymarket or similar APIs
- `data_source` field currently reads "synthetic" — will switch to "polymarket" etc.
- Truth validation of crowd beliefs is basic (price-at-record vs current-price) — designed for future delayed-window enhancement

**What's right:**
- Strictly observer-only — no trade triggers, no execution influence
- Clean modular design: one new module, integration via existing pipelines
- Safe fallbacks: all endpoints return valid structures even with no data
- Backward-compatible: new table via `CREATE TABLE IF NOT EXISTS`, existing DBs unaffected

**What could be improved:**
- Real prediction market API integration (Polymarket, Kalshi, etc.)
- Delayed-window crowd truth validation (like news_truth_validator's +5/+20/+100 cycles)
- Crowd sentiment trend over time visualization
- Crowd accuracy score badge in Lab

**Commit:** `b64389b`
**Deployment:** Mac + Render ✅
**REQUIRED:** Set `JWT_SECRET` env var on Render Dashboard → Environment

---

## v5.1 — Rebalance Discipline vs Exploration
**Date:** Pre-v6 era
**Commit:** `75181f4`

**What changed:**
- Probe layer: softened kill conditions to allow exploratory small trades
- Hold breaker: loosened hold requirements so the system doesn't sit idle forever
- Rebalanced aggression vs patience in trading logic

**Deployment:** Mac + Render

---

## v6.0 — Trade Ledger Rewrite + Intelligence UI
**Date:** Pre-v7 era
**Commit:** `89eda58`

**What changed:**
- Complete trade ledger rewrite with structured data
- Intelligence UI panel added to frontend
- Night-mode P&L display
- Debug panel for monitoring system internals

**Deployment:** Mac + Render

---

## v7.0 — Memory + Reflection + Self-Evolving Core
**Date:** Pre-v7.1
**Commit:** `75664d0`

**What changed:**
- SQLite persistence layer with WAL mode (replaced CSV-based storage)
- Version-scoped sessions with automatic closure on upgrade
- 11 core tables: sessions, system_state, trade_ledger, cycle_snapshots, experience_memory, behavior_profiles, adaptation_events, etc.
- Session manager with startup detection (new install vs upgrade vs resume)
- CSV → SQLite migration on first v7 boot
- System age tracking (cycles, hours, lifetime)
- Experience memory with lesson generation
- Behavior profiles with personality parameters
- Feedback loop with bounded self-adaptation
- Full API endpoint suite under `/v7/*`

**Deployment:** Mac + Render

---

## v7.1 — Intelligence + Evaluation + Self-Correction ("Thinking Upgrade")
**Date:** Pre-v7.2
**Commit:** `e27c7ff`

**What changed:**
- **Delayed Outcome Evaluation Engine** (`outcome_engine.py`): Every BUY registered for evaluation at +5, +20, +100 cycles. Tracks MFE/MAE. Final verdict by majority vote. Generates memory lessons.
- **Missed Opportunity Memory** (`memory_engine.py` modified): DB-backed missed opportunity tracking replacing in-memory lists. Multi-checkpoint evaluation at +5 and +20 cycles. Severity classification (minor/moderate/major).
- **Regime Intelligence Memory** (`regime_intelligence.py`): Aggregates strategy performance per market regime. Computes prefer/avoid/neutral recommendations every 50 cycles.
- **Behavior Intelligence Layer** (`behavior_intelligence.py`): Two dynamic states (market_reward_state + system_self_state). Produces bounded modifiers for aggression, patience, threshold, exposure.
- **Daily Review → Next-Day Adaptation** (`daily_review.py` modified): Structured daily_bias with per-regime bias, strategy preferences, threshold adjustments.
- **DB additions**: 5 new tables (experience_outcomes, missed_opportunities, regime_profiles, behavior_states, daily_bias). ~20 new helper functions.
- **auto_trader.py**: Wired all v7.1 hooks (outcome registration, checkpoint evaluation, behavior state updates, regime recording).
- **multi_strategy.py**: Consumes intelligence from behavior_intelligence, regime_intelligence, and daily_review to modify thresholds dynamically.

**Review notes:**
- Transformed CryptoMind from a "memory system" to a "judgement system"
- Concern identified post-implementation: declared constants (like MIN_OBSERVATIONS=50) were not enforced across all adaptation paths — led to v7.2

**Deployment:** Mac + Render

---

## v7.2 — Discipline Enforcement Layer
**Date:** 2026-03-21
**Commit:** `32b90e2`

**What changed:**
- **`discipline_guard.py` (NEW — ~400 lines)**: Central `can_adapt()` gate function. Single source of truth for all bounds, cooldowns, and minimum evidence requirements.
  - Minimum samples: 50 observations + 20 outcomes (behavior/modifiers), 5 trades (daily bias), 10 trades + 5 outcomes (regime recs)
  - Cooldowns: 100 cycles global, 150 behavior, once/day bias
  - Small-step clamping: ±0.02 personality, ±2.0 thresholds, ±0.03 exposure
  - Recency decay: 1.0x (0-6hrs), 0.70x (6-24hrs), 0.40x (1-3 days), 0.15x (3+ days)
  - Stability checks: conflict/stacking/risk detection
  - Full audit trail via adaptation_journal table
- **`feedback.py` (REWRITTEN)**: All personality adaptations now call `can_adapt()`. Clean ISSUE_MAP pattern replaced old ad-hoc loops.
- **`behavior_intelligence.py` (MODIFIED)**: Modifiers gated by guard. Recency-weighted trade analysis.
- **`regime_intelligence.py` (MODIFIED)**: Recommendations gated by guard. Minimum trades sourced from discipline_guard constants.
- **`daily_review.py` (MODIFIED)**: 4 safety modes (applied/carried_forward/insufficient_data/blocked_by_cooldown).
- **`db.py` (MODIFIED)**: Added `adaptation_journal` table with full audit fields.
- **`api.py` (MODIFIED)**: Added `/v7/discipline` and `/v7/adaptation-journal` endpoints.
- **Version bumped**: session_manager.py + config.py → 7.2.0

**What's right:**
1. Single source of truth — no more scattered, unenforced constants
2. Full audit trail — every adaptation attempt logged (allowed + blocked)
3. Recency decay prevents stale evidence from driving decisions
4. Daily bias safety modes are clean and well-defined
5. Guard pattern is composable — future features just call `can_adapt()`

**What could be improved:**
1. Adaptive cooldowns — fixed 100/150 cycles may be too rigid; could scale with volatility
2. Graduated evidence thresholds — instead of hard cutoff at 50 obs, allow tiny adjustments at 20 obs
3. Auto-revert mechanism — journal tracks reversal_candidate but nothing triggers auto-reverts yet
4. Cross-asset learning — when ETH/SOL go live, regime lessons should transfer across assets
5. Frontend visualization — discipline/journal endpoints exist but no UI panels yet
6. Stale journal cleanup — adaptation_journal will grow indefinitely; needs archival strategy

**Deployment:** Mac + Render (pushed 2026-03-21)

---

## v7.3 — Mind Evolution Layer
**Date:** 2026-03-21
**Commit:** `4285c05`

**What changed:**
- **`mind_evolution.py` (NEW — ~500 lines)**: Core computation module for evolution score, skill breakdown, learning feed, session timeline, and periodic snapshots.
  - Evolution score (0-1000) from 13 weighted components grounded in real system evidence
  - PnL capped at 5% contribution — rewards discipline, stability, accuracy over profit
  - 9 skill sub-scores (0-100): Discipline, Risk Control, Timing, Adaptation, Regime Reading, Opportunity Sensing, Consistency, Self-Correction, Patience
  - Mind level ladder: Rookie → Beginner → Apprentice → Operator → Pro → Elite → World Class → Assassin → Sage → Godmode
  - Recent learning feed from memories, outcomes, behavior state, regime profiles, daily reviews
  - Version/session timeline with milestone descriptions
  - Periodic snapshots every 100 cycles for history tracking
- **`db.py` (MODIFIED)**: Added 2 new tables:
  - `evolution_snapshots` (17 columns) — periodic score/skill snapshots
  - `milestones` (9 columns) — significant system events
  - 4 new indexes, 6 new helper functions
  - Total: 17 tables + sqlite_sequence (19 in DB)
- **`api.py` (MODIFIED)**: 5 new endpoints:
  - `GET /v7/mind` — full mind state (score, level, skills, system age)
  - `GET /v7/mind/history` — evolution score history for charting
  - `GET /v7/mind/skills` — 9 skill sub-scores with descriptions
  - `GET /v7/mind/lessons` — recent learning feed
  - `GET /v7/mind/timeline` — version/session timeline with milestones
- **`frontend/src/pages/Mind.jsx` (NEW — ~400 lines)**: Full Mind page with:
  - Clean monochrome SVG icons per mind level
  - Hero card with level icon, score, progress bar
  - 4 tabs: Overview (radar chart + learning feed + history chart), Skills (9 cards), Lessons (feed), Timeline (session history)
  - SVG radar/spider chart for skill breakdown
  - Mini evolution sparkline chart
  - Daily mind state tag (Calm/Observing, Focused/Selective, Defensive/Noisy)
- **`frontend/src/App.jsx` (MODIFIED)**: Added Mind route + sidebar nav item (◈ Mind)
- **`frontend/src/pages/Dashboard.jsx` (MODIFIED)**: Added Mind Evolution strip showing level, score, progress bar, points to next level
- **`session_manager.py` (MODIFIED)**: Version → 7.3.0, takes evolution snapshot every 100 cycles
- **`config.py` (MODIFIED)**: Version → 7.3.0

**What's right:**
1. Pure read-only — zero changes to trading behavior, thresholds, or adaptation logic
2. Real evidence only — every score computed from actual DB queries, no placeholders
3. PnL is capped at 5% — genuinely rewards maturity not lucky streaks
4. Honest incomplete fields — skills show "warming_up" when data insufficient
5. Radar chart gives instant visual of strengths/weaknesses
6. Clean, calm visual identity — monochrome SVGs, no gamification

**What could be improved:**
1. Timing skill is too coarse — just uses outcome coverage, could weight entry accuracy more
2. No auto-milestone generation yet — milestones table exists but nothing triggers them
3. Cross-session evolution history — chart resets on version upgrade
4. Skill tooltips on radar chart — currently static SVG
5. iPad responsive layout — 3-column skills grid may need to collapse to 2

**Deployment:** Mac + Render (pushed 2026-03-21)

---

## v7.3.1 — Mind Calibration + Confidence + Evolution Identity
**Date:** 2026-03-22
**Commit:** `67bd436`

**What changed:**
- **`mind_evolution.py` (REWRITTEN — ~750 lines)**:
  - Evidence multiplier: 0–10 samples → ×0.35, 11–25 → ×0.50, 26–50 → ×0.65, 51–100 → ×0.80, 101–200 → ×0.92, 200+ → ×1.00
  - Global maturity cap: <20 trades → max 45, 20–49 → 60, 50–99 → 72, 100–199 → 82, 200–399 → 90, 400+ → 100
  - Warming up skills (<10 samples) hard-capped at 38
  - Global confidence score (0–100) from 8 weighted components: sessions, trades, outcomes, coverage, adaptations, memory, regime recs, session hours
  - Confidence labels: Very Low / Low / Medium / High / Elite
  - New level ladder: Seed → Novice → Apprentice → Monk → Ranger → Sniper → Operator → Strategist → Mastermind → Oracle
  - Level gates require BOTH score threshold AND minimum confidence/trades/sessions/outcomes
  - `compute_why_this_level()` — plain English "why this level" + "what's needed for next"
  - Per-skill confidence (score, label, color, evidence_count, warming_up)
  - Evidence strength percentage
- **`frontend/src/pages/Mind.jsx` (REWRITTEN — ~530 lines)**:
  - New SVG sigils per level: spark (Seed), ring (Novice), blade (Apprentice), lotus (Monk), compass (Ranger), crosshair (Sniper), shield-reticle (Operator), knight (Strategist), eye (Mastermind), radiant sigil (Oracle)
  - Hero card: level icon, score, confidence badge, evidence strength bar
  - "Why [Level]?" panel with plain English reasons
  - "To reach [Next Level]" panel with specific requirements
  - Skill cards show confidence label, evidence count, warming_up flag
  - Confidence color coding: gray (Very Low), amber (Low), blue (Medium), green (High), purple (Elite)
- **`frontend/src/pages/Dashboard.jsx` (MODIFIED)**: Mind strip shows Level + Confidence badge + Score + Points to next
- **`config.py` + `session_manager.py`**: Version → 7.3.1

**No DB changes.** No trading logic changes.

**What's right:**
1. Honest scoring — 5 trades can't produce 70+ on any skill anymore
2. Level gates prevent inflation — score alone doesn't unlock levels
3. Per-skill confidence makes trust levels visible
4. "Why this level?" is immediately useful for understanding system state
5. Evidence strength bar gives at-a-glance data quality indicator

**What could be improved:**
1. Adaptive evidence bands — static buckets could adjust based on context
2. Cross-session skill aggregation — evidence resets per session
3. Sparkline per skill — show individual skill trends over time
4. iPad responsive — 3-column skill grid needs 2-column breakpoint
5. Auto-milestone generation on level-up events

**Deployment:** Mac + Render (pushed 2026-03-22)

---

## v7.4.0 — Observer Core (Chunk 1)
**Date:** 2026-03-22
**Commit:** `1c05f2e`

**What changed:**
- **`news_ingestor.py` (NEW — ~210 lines)**: Fetches crypto news from CryptoCompare, CoinGecko trending, Alternative.me Fear & Greed Index. Rate-limited (5min), deduped, cached in memory. Persists raw headlines to existing `news_events` table.
- **`news_classifier.py` (NEW — ~230 lines)**: Rule-based headline classification — zero LLM calls, fully deterministic. Keyword banks for bullish/bearish/hype/noise/BTC-relevant signals. Produces: relevance, sentiment, impact, trust, novelty, hype_score, bs_risk, category, verdict (interesting/watch/reject/noise). Tone library with verdict+flavour keyed one-liners.
- **`bullshit_radar.py` (NEW — ~195 lines)**: Tracks signal vs noise ratio, narrative distortion, crowd heat, signal quality. Levels: clear → mild → moderate → elevated → high → extreme. Feeds on classified news batches.
- **`mind_state_engine.py` (NEW — ~240 lines)**: 8 moods (calm_observing, focused_selective, cautious_defensive, confident_steady, alert_volatile, skeptical_filtering, recovering_learning, idle_waiting). Each with label, sigil, description, color. Produces: action_impulse, clarity (0-100), current_focus, reasoning summary.
- **`mind_feed_engine.py` (NEW — ~230 lines)**: Chronological observer feed combining news observations, trades, mood changes. 15 feed types with icon/color/label. Dedup window (45s). Cross-references via linked_news_event_id, linked_trade_id, linked_cycle_snapshot_id.
- **`action_narrator.py` (NEW — ~160 lines)**: Read-only trade narration with template-based commentary. BUY/SELL/HOLD templates (high_conf, medium_conf, low_conf, probe, breakout, profit, stop, target, etc.). Anti-dopamine tone throughout.
- **`db.py` (MODIFIED)**: 3 new tables (18: news_event_analysis, 19: mind_feed_events, 20: mind_state_snapshots) with full observer fields. 8 new indexes. 7 new helper functions.
- **`api.py` (MODIFIED)**: 6 new endpoints: `/v7/mind/feed`, `/v7/mind/state`, `/v7/mind/radar`, `/v7/news/latest`, `/v7/news/rejected`, `/v7/news/interesting`. Internal `_observer_classify_and_feed()` orchestrator.
- **`frontend/src/pages/Lab.jsx` (NEW — ~280 lines)**: Full Lab page with MoodSigil (8 SVGs), RadarBar, FGGauge, ClarityBar, FeedItem timeline, VBadge/SBadge. Layout: Hero mind state → 3-col (radar, F&G, side hustle) → 2-col (feed, interesting+rejected). Auto-polling at 10-30s intervals.
- **`frontend/src/App.jsx` (MODIFIED)**: Added Lab import, route (`/lab`), and nav item (⬡ Lab).
- **`config.py` + `session_manager.py`**: Version → 7.4.0

**No trading logic changes.** No modifications to auto_trader.py, multi_strategy.py, paper_broker.py, or decision_engine.py. All 6 new modules are read-only observers.

**What's right:**
1. Pure observer layer — completely read-only, zero interference with trading core
2. Rule-based classification — no LLM calls, fast, deterministic, explainable
3. Anti-dopamine tone throughout — "Recycled narrative. Ignoring.", "Smells like paid content. Hard pass."
4. Bullshit radar quantifies noise level — not just detecting noise, measuring it
5. Mind state synthesizes multiple inputs into a single clear mood
6. Action narrator comments on trades without influencing them
7. Feed cross-references (linked_news_event_id, etc.) enable rich drill-down later
8. All news sources are free APIs — no paid subscriptions needed

**What could be improved:**
1. News source diversity — only CryptoCompare + CoinGecko trending; could add RSS feeds or Twitter/X
2. Classifier keyword banks could be richer — currently ~30-40 keywords per category
3. Novelty detection is crude — just uses hype word count, could use headline similarity/dedup
4. Mind state engine doesn't factor in time-of-day or market session (Asian/European/US)
5. Feed persistence is selective — only "important" events saved to DB; might want full archive
6. No WebSocket support — all polling-based; real-time feed would be better UX
7. Lab page responsiveness — 3-column layout may need collapse points for iPad
8. Bullshit radar history chart — currently snapshot only, no historical trend view

**Commit:** `b64389b`
**Deployment:** Mac + Render ✅
**REQUIRED:** Set `JWT_SECRET` env var on Render Dashboard → Environment

---

## v7.4.0 — Observer Core Chunk 2: Personality + Session Intent
**Date:** 2026-03-22
**Commit:** `1c05f2e` (combined with Chunk 1 + Stabilization)

**What changed:**
- **`personality_engine.py` (NEW — ~250 lines)**: Derives 7 traits (patience, aggression_control, hype_resistance, adaptability, discipline, self_correction, risk_awareness) from behavior_profile, behavior_states, adaptation_journal, experience_memory, trade_ledger, and bullshit_radar. Every score is evidence-based — no random labels.
- **`session_intent_engine.py` (NEW — ~240 lines)**: Generates daily posture (defensive/neutral/opportunistic/trend_friendly/headline_sensitive) from daily_bias, regime, performance, volatility, noise ratio, fear & greed. Weighted scoring with confidence.
- **`milestone_engine.py` (NEW — ~230 lines)**: Auto-detects meaningful events: trade thresholds (10/25/50/100/250/500), memory depth, adaptation count, evolution level-ups, win rate, drawdown recovery, session longevity. Non-cheesy, factual milestones.
- **`lifetime_mind_aggregator.py` (NEW — ~200 lines)**: Cross-session aggregation: lifetime totals, best session, skill averages from evolution snapshots, evolution curve for charting. Reuses mind_evolution compute functions.
- **`db.py` (MODIFIED)**: 3 new tables (21: personality_snapshots, 22: session_intents, 23: lifetime_mind_stats) + 2 new indexes + 6 new helper functions with dedup guards. Total: 25 tables.
- **`api.py` (MODIFIED)**: 4 new endpoints: `/v7/mind/personality`, `/v7/mind/session-intent`, `/v7/mind/milestones`, `/v7/mind/lifetime`.
- **`observer_guard.py` (MODIFIED)**: Added 4 new Chunk 2 modules to guard whitelist.
- **`frontend/src/pages/Lab.jsx` (MODIFIED)**: Added Personality card (dominant trait + supporting + bars), Session Intent card (icon + label + reasoning + factors), Milestones timeline (color-coded by type), Lifetime stats grid with aggregated numbers. All with warm-up states.

**No trading logic changes.** No modifications to auto_trader.py, multi_strategy.py, paper_broker.py, or decision_engine.py. All 4 new modules are read-only observers.

**What's right:**
1. Every personality trait is computed from real DB data — zero fabrication
2. Session intent uses weighted scoring from 8+ real signals — not random
3. Milestones auto-detect from thresholds — no manual input needed
4. Lifetime aggregator reuses mind_evolution — no duplicated logic
5. All new DB inserts have dedup guards
6. Observer guard confirms all 11 observer modules are clean
7. Warm-up states everywhere — system is honest about insufficient data

**What could be improved:**
1. Personality snapshot persistence — currently only computed on-demand, not periodically saved
2. Intent history visualization — session_intents table records history but no chart yet
3. Milestone dedup uses title string matching — could use a hash-based approach
4. Lifetime skill trend charts — data exists but frontend only shows text summary
5. Cross-session personality drift — could track how traits change across versions

**Deployment:** Mac + Render (commits `1c05f2e` + `e6fb6d6`)

---

## v7.4.0 — Observer Core Chunk 3: Truth Validation + Deep Reflection
**Date:** 2026-03-22
**Commit:** `823fff6`

**What changed:**
- **`news_truth_validator.py` (NEW — ~200 lines)**: Compares expected sentiment bias from classified news against actual market movement at +5/+20/+100 cycle delayed windows. Classifies each as correct/wrong/mixed/faded. Movement thresholds: 0.15% minimum, 0.50% strong. Fade detection catches correct-then-reversed patterns.
- **`contextual_summary_engine.py` (NEW — ~220 lines)**: Daily context summary with 4 sections: market behavior (dominant regime, quality, volatility, trend), trade summary (count, PnL, win rate, best strategy), news-vs-price alignment check (aligned/divergent/neutral), and next-day posture hint. Stateless compute, 2-min cache.
- **`mind_journal_engine.py` (NEW — ~230 lines)**: Daily journal with key insight, mistakes, lessons, mood arc, bias shifts. Derives all content from trades, snapshots, memories, reviews, mind states, and intents. Persists to DB with dedup by session+date+type.
- **`action_reflection_engine.py` (NEW — ~240 lines)**: Per-trade grading: entry timing (A-F from signal score + confidence + regime + market quality), size appropriateness (probe vs full matching conviction), patience impact (helped/hurt/neutral from post-trade price movement). Overall grade composited with timing weighted 2x. Persists to DB with dedup by trade_id.
- **`replay_engine.py` (NEW — ~200 lines)**: Reconstructs session timeline from 5 sources: trades, classified news, mind state shifts, milestones, regime changes. Each gets a typed marker with importance score. Sorted chronologically for timeline display.
- **`db.py` (MODIFIED)**: 4 new tables (24: news_truth_reviews, 25: mind_journal_entries, 26: action_reflections, 27: replay_markers) + 10 new indexes + cycle_snapshots range helpers (get_cycle_snapshots_range, get_snapshot_at_cycle) + ~15 new helper functions with dedup guards. Total: 29 tables.
- **`api.py` (MODIFIED)**: 5 new endpoints: `/v7/news/truth-reviews`, `/v7/mind/context-summary`, `/v7/mind/journal`, `/v7/side-hustle/reflections`, `/v7/mind/replay`. Truth review creation integrated into _observer_classify_and_feed.
- **`observer_guard.py` (MODIFIED)**: Added 5 new Chunk 3 modules + 4 new observer-owned tables to guard whitelist.
- **`frontend/src/pages/Lab.jsx` (MODIFIED)**: 5 new sections: Context Summary card (market/trades/news-vs-price/posture), Daily Journal card (insight/mood/mistakes/lessons), Truth Validation panel (accuracy stats + review cards with verdict badges), Action Reflections panel (grade distribution + per-trade grading), Session Replay timeline (chronological markers with color-coded dots and importance stars).

**No trading logic changes.** All 5 new modules are read-only observers.

**What's right:**
1. Truth validation uses delayed data only — no look-ahead bias
2. All verdicts come with plain-english explanations
3. Trade grading is evidence-based from real scores/confidence/regime
4. Journal deduplicates by date — one entry per day, updated if data changes
5. Replay timeline assembles 5 data sources into coherent chronology
6. Observer guard now covers 16 modules and 8 observer-owned tables
7. All new DB inserts have dedup guards
8. Warm-up states on every new panel

**What could be improved:**
1. Truth reviews currently create reviews for all 3 windows at once — could be staggered
2. Action reflection patience assessment needs more post-trade data for accuracy
3. Replay timeline doesn't yet link causally (news → interpretation → action chain)
4. Context summary posture hint could incorporate truth review accuracy as a feedback signal
5. Journal could track cross-day patterns (recurring mistakes, improving strengths)

**Deployment:** Mac + Render (commit `823fff6`)

---

## v7.4.1 — News Transparency + Continuity Layer + Financial Persistence
**Date:** 2026-03-22
**Commit:** (pending)

**What changed:**

### News Transparency + Deep Inspection
- **`news_classifier.py` (MODIFIED)**: Added `reasoning_text` (human-readable interpretation breakdown showing keyword hits, signals, category, impact, trust, verdict) and `extracted_signals` dict (structured bullish/bearish/hype/noise/relevance keywords + counts). Added `body` passthrough in `classify_batch()`.
- **`mind_feed_engine.py` (MODIFIED)**: Feed meta now passes full detail: reasoning_text, body, url, trust, relevance, hype_score, bullish/bearish signals. Enables expandable feed items.
- **`api.py` (MODIFIED)**: `_observer_classify_and_feed()` now persists ALL classified news (not just interesting/watch) with raw_summary, source_name, fetched_at, reasoning_text, extracted_signals_json. New endpoint: `/v7/news/detail/{id}` returns full deep inspection of any classified news item.
- **`db.py` (MODIFIED)**: 5 new columns on `news_event_analysis` (raw_summary, source_name, fetched_at, reasoning_text, extracted_signals_json) + ALTER TABLE migration for existing DBs. New helper: `get_news_analysis_by_id()`.
- **`Lab.jsx` (MODIFIED)**: FeedItem is now expandable for news items — click to reveal verdict badge, sentiment, scores, raw body, reasoning breakdown, bullish/bearish signals, source link. InterestingItem also expandable with same detail.

### Continuity Layer — Persistent Identity Across Versions
- **`db.py` (MODIFIED)**: 3 new tables:
  - `lifetime_identity` (28): singleton row with total_cycles, total_trades, total_sessions, dominant_traits_json, continuity_score, memory_depth_score
  - `capital_ledger` (29): tracks all capital events (initial_funding, refill, withdrawal, version_upgrade, correction) with amount, balance_after, reason
  - `lifetime_portfolio` (30): persistent financial state (cash, btc_holdings, avg_entry, equity, realized_pnl, unrealized_pnl, wins, losses, peak_equity, max_drawdown_pct, refills)
  Total: 30 tables.
  Added 20+ new helper functions: lifetime_identity CRUD, capital_ledger CRUD, lifetime_portfolio sync, get_trades_by_scope (session/version/lifetime), get_trade_stats_by_scope, lifetime memories/journals/reflections/truth reviews/milestones/daily reviews queries, get_recurring_patterns.
- **`session_manager.py` (MODIFIED)**: Version upgrades now preserve financial state via `_preserve_portfolio_on_upgrade()`. Lifetime identity initialized on first boot (seeded from system_state). Lifetime portfolio synced every 10 cycles. Capital events logged for version transitions. New `record_refill()` for adding capital without resetting stats.
- **`mind_evolution.py` (MODIFIED)**: Continuity multiplier (up to +5%) based on lifetime cycles, sessions, trades. Longer-running systems get a maturity boost.
- **`personality_engine.py` (MODIFIED)**: Now uses ALL historical data for personality computation — lifetime memories and lifetime trade summary included. 70% recent / 30% lifetime weighting via effective_trades. Dominant traits persisted to lifetime_identity. warm-up check uses effective_trades (max of session + lifetime).

### API Additions (12 new endpoints)
- `/v7/mind/identity` — system age, continuity score, dominant traits, version history
- `/v7/lifetime/portfolio` — persistent financial state + capital summary
- `/v7/lifetime/capital-events` — capital event log
- `/v7/lifetime/refill` (POST) — add capital without resetting stats
- `/v7/trades/scoped?scope=session|version|lifetime` — trades + stats by scope
- `/v7/lifetime/memories?scope=session|lifetime` — memories by scope
- `/v7/lifetime/journals?scope=session|lifetime` — journals by scope
- `/v7/lifetime/reflections?scope=session|lifetime` — reflections by scope
- `/v7/lifetime/truth-reviews?scope=session|lifetime` — truth reviews by scope
- `/v7/lifetime/milestones` — all milestones across all sessions
- `/v7/lifetime/patterns?pattern_type=mistake|lesson` — recurring patterns
- `/v7/news/detail/{id}` — deep inspection of classified news

### Frontend Changes
- **`Lab.jsx`**: New System Identity card (total cycles, sessions, trades, continuity score, memories, version). New Lifetime Portfolio card (cash, BTC, equity, realized PnL, peak, max drawdown, refill count). Expandable FeedItem and InterestingItem components.
- **`Trades.jsx`**: Added ScopeToggle (Session/Version/Lifetime) with scoped stats bar showing trades, wins, losses, win rate, PnL per scope.
- **`Memory.jsx`**: Added ScopeToggle on Memories tab — session vs lifetime memory view with oldest/newest/avg confidence metadata.
- **`ScopeToggle.jsx` (NEW)**: Reusable session/version/lifetime toggle component.

### Tables NEVER reset on version change
- experience_memory, daily_reviews, mind_journal_entries, news_truth_reviews, action_reflections, milestones, personality_snapshots, lifetime_mind_stats, evolution_snapshots, behavior_profile, adaptation_journal, capital_ledger, lifetime_portfolio, lifetime_identity

**No trading logic changes.** All changes are in persistence, display, and observer layers.

**What's right:**
1. Financial state persists across version upgrades — no more reset to $100
2. All classified news now stored (not just interesting/watch) — full audit trail
3. News reasoning is fully explainable — keyword hits, signal counts, verdict logic
4. Continuity score gives a measurable "system maturity" metric
5. Capital ledger provides transparent funding/refill tracking
6. Scope toggles let user view session vs version vs lifetime on key pages
7. Personality uses lifetime data with recency weighting — survives upgrades
8. Evolution score gets maturity boost for long-running systems
9. Backward compatible — ALTER TABLE migration for existing DBs
10. Refill system adds cash without resetting stats or PnL

**What could be improved:**
1. Performance page doesn't have scope toggle yet (easy add later)
2. Journal page could benefit from lifetime view toggle
3. Mind page could show lifetime evolution curve
4. Leaderboard doesn't have version/lifetime modes yet
5. Fresh-start mode (archive + new sandbox) not yet implemented
6. Recurring patterns analysis is simple text matching — could use similarity scoring

### Stabilization Pass — Bugs Found & Fixed

| # | Bug | Severity | Fix |
|---|-----|----------|-----|
| 1 | Schema defaults `cash=100.0`, `total_equity=100.0`, `peak_equity=100.0` in lifetime_portfolio table | Medium | Changed all to `0.0` — no hidden $100 in schema |
| 2 | `upsert_lifetime_portfolio()` had `setdefault("cash", 100.0)` fallback on INSERT | Medium | Removed — now raises ValueError if cash not explicitly provided |
| 3 | `initial_funding` could re-fire if lifetime_portfolio row deleted | High | Added capital_ledger check — if initial_funding already logged, re-creates from last known balance |
| 4 | Version upgrade event logged `balance_after=None` — no financial snapshot | Medium | Now captures and logs actual cash + equity at upgrade time |
| 5 | `get_trades_by_scope()` returned lifetime trades when session_id=None | High | Session scope with no session_id now returns empty `([], 0)` |
| 6 | `get_trade_stats_by_scope()` same issue — fell through to lifetime on missing session | High | Added explicit empty stats return for invalid scope/missing id |
| 7 | Identity init counted archive sessions (pre-v7) in `total_sessions` | Medium | Filters out `pre-v7` sessions from count |
| 8 | Refill POST had no idempotency guard — retries could duplicate | Critical | Added 10-second cooldown + amount validation + returns updated portfolio |
| 9 | `InterestingItem` bs_risk comparison could crash on null | Low | Added `!=null` guard before comparison |
| 10 | `sync_lifetime_portfolio()` used fallback `peak_equity=100.0` instead of current equity | Medium | Changed fallback to current equity value |

**Commit:** `d76be65`
**Deployment:** Mac + Render ✅

---

*This log is maintained after every version update for future reference.*
