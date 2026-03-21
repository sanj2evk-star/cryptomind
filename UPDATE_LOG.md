# CryptoMind — Update Log

A running record of every version update: what changed, what was reviewed, and deployment notes.

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

*This log is maintained after every version update for future reference.*
