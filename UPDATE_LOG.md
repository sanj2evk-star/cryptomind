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

*This log is maintained after every version update for future reference.*
