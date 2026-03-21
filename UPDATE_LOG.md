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

## v7.4.0 — Observer Core (Chunk 1)
**Date:** 2026-03-22
**Commit:** *(pending)*

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

**Deployment:** *(pending — awaiting user confirmation)*

---

## v7.4.0 — Observer Core Chunk 2: Personality + Session Intent
**Date:** 2026-03-22
**Commit:** *(pending)*

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

**Deployment:** *(pending — awaiting user confirmation)*

---

*This log is maintained after every version update for future reference.*
