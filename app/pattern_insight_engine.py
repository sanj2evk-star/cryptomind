"""
pattern_insight_engine.py — CryptoMind v7.5.1: Recurring Pattern Detection.

Reads from journal entries, action reflections, truth reviews, daily reviews,
and experience memory to surface recurring behavioral patterns.

Outputs:
    - top recurring mistakes (with confidence calibration)
    - top recurring strengths (with confidence calibration)
    - most common rejected narrative type
    - most repeated lesson
    - crowd accuracy patterns

Confidence levels:
    - LOW:    evidence_count < 3  (early signal, may not persist)
    - MEDIUM: evidence_count 3–6  (emerging pattern, worth watching)
    - HIGH:   evidence_count > 6  (well-established pattern)

Rule-based, explainable, no LLM dependency.
Observer-only — no effect on execution.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from collections import Counter

# Cache
_cache: dict | None = None
_cache_ts: float = 0
_CACHE_TTL = 180  # seconds


# ---------------------------------------------------------------------------
# Keyword clusters for pattern matching
# ---------------------------------------------------------------------------

_MISTAKE_PATTERNS = {
    "early_entry": ["early", "too soon", "premature", "jumped in", "before confirm"],
    "late_exit": ["held too long", "late exit", "should have sold", "missed exit", "overstayed"],
    "overtrading": ["too many trades", "overtrading", "churning", "excessive"],
    "ignored_signals": ["ignored", "override", "dismissed", "signal was clear"],
    "poor_sizing": ["too large", "too small", "sizing", "position size", "oversized"],
    "chased_hype": ["hype", "fomo", "chased", "crowd", "narrative"],
    "no_patience": ["impatient", "patience", "rushed", "didn't wait"],
    "fought_trend": ["against trend", "counter-trend", "fighting", "wrong direction"],
}

_STRENGTH_PATTERNS = {
    "patience_wins": ["patience", "waited", "patient", "let it run", "held through"],
    "good_timing": ["good entry", "well timed", "caught", "right time", "clean entry"],
    "discipline": ["disciplin", "stuck to rules", "followed plan", "stayed disciplined"],
    "risk_control": ["risk managed", "small loss", "cut loss", "controlled risk", "tight stop"],
    "trend_following": ["trend", "momentum", "followed the move", "rode"],
    "skepticism": ["skeptic", "didn't chase", "avoided hype", "filtered noise", "rejected"],
    "adaptability": ["adapt", "adjusted", "flexible", "shifted approach"],
}

_NARRATIVE_TYPES = {
    "bullish_hype": ["moon", "surge", "breakout", "rally", "pump", "bull run", "skyrocket"],
    "bearish_fud": ["crash", "collapse", "dump", "plunge", "bear", "panic"],
    "regulatory_fear": ["ban", "regulation", "sec", "crackdown", "lawsuit"],
    "adoption_hype": ["adoption", "institutional", "etf", "mainstream", "walmart"],
    "technical_noise": ["death cross", "golden cross", "pattern", "fibonacci"],
}


def _match_patterns(text: str, pattern_dict: dict) -> list[str]:
    """Match text against keyword clusters. Returns list of matched pattern names."""
    if not text:
        return []
    text_lower = text.lower()
    matches = []
    for name, keywords in pattern_dict.items():
        for kw in keywords:
            if kw in text_lower:
                matches.append(name)
                break
    return matches


def _human_label(pattern_key: str) -> str:
    """Convert pattern key to human-readable label."""
    labels = {
        "early_entry": "Early entries before confirmation",
        "late_exit": "Holding too long on exits",
        "overtrading": "Too many trades in low-quality conditions",
        "ignored_signals": "Ignoring clear signals",
        "poor_sizing": "Position sizing issues",
        "chased_hype": "Chasing crowd hype",
        "no_patience": "Not enough patience",
        "fought_trend": "Fighting the trend",
        "patience_wins": "Patience keeps paying off",
        "good_timing": "Good timing on entries",
        "discipline": "Staying disciplined under pressure",
        "risk_control": "Effective risk control",
        "trend_following": "Riding trends well",
        "skepticism": "Healthy skepticism filtering noise",
        "adaptability": "Adapting to market changes",
        "bullish_hype": "Bullish hype narratives",
        "bearish_fud": "Bearish fear narratives",
        "regulatory_fear": "Regulatory scare stories",
        "adoption_hype": "Adoption/institutional hype",
        "technical_noise": "Technical pattern noise",
    }
    return labels.get(pattern_key, pattern_key.replace("_", " ").title())


# ---------------------------------------------------------------------------
# Pattern extraction from different data sources
# ---------------------------------------------------------------------------

def _analyze_journals(journals: list[dict]) -> dict:
    """Extract patterns from journal entries."""
    mistake_counter = Counter()
    lesson_counter = Counter()

    for j in journals:
        mistakes = j.get("mistakes_text") or j.get("text") or ""
        lessons = j.get("lessons_text") or ""

        for m in _match_patterns(mistakes, _MISTAKE_PATTERNS):
            mistake_counter[m] += 1
        for s in _match_patterns(lessons, _STRENGTH_PATTERNS):
            lesson_counter[s] += 1

    return {
        "mistakes": mistake_counter,
        "lessons": lesson_counter,
    }


def _analyze_reflections(reflections: list[dict]) -> dict:
    """Extract patterns from action reflections (trade grading)."""
    grade_counts = Counter()
    timing_issues = Counter()
    patience_outcomes = Counter()

    for r in reflections:
        grade = r.get("overall_grade", "C")
        grade_counts[grade] += 1

        timing = r.get("entry_timing_grade", "C")
        if timing in ("D", "F"):
            timing_issues["poor_timing"] += 1
        elif timing in ("A", "B"):
            timing_issues["good_timing"] += 1

        patience = r.get("patience_impact", "neutral")
        if patience == "helped":
            patience_outcomes["patience_helped"] += 1
        elif patience == "hurt":
            patience_outcomes["patience_hurt"] += 1

        # Extract text patterns
        well = r.get("what_went_well", "")
        improve = r.get("what_could_improve", "")
        for s in _match_patterns(well, _STRENGTH_PATTERNS):
            timing_issues[f"strength_{s}"] += 1
        for m in _match_patterns(improve, _MISTAKE_PATTERNS):
            timing_issues[f"mistake_{m}"] += 1

    return {
        "grades": grade_counts,
        "timing": timing_issues,
        "patience": patience_outcomes,
    }


def _analyze_truth_reviews(reviews: list[dict]) -> dict:
    """Extract patterns from truth validation reviews."""
    verdict_counts = Counter()
    crowd_accuracy = Counter()

    for r in reviews:
        verdict = r.get("verdict", "unclear")
        verdict_counts[verdict] += 1

        bias = r.get("expected_bias", "neutral")
        if verdict == "correct":
            crowd_accuracy[f"{bias}_right"] += 1
        elif verdict == "wrong":
            crowd_accuracy[f"{bias}_wrong"] += 1
        elif verdict == "faded":
            crowd_accuracy[f"{bias}_faded"] += 1

    total_graded = verdict_counts.get("correct", 0) + verdict_counts.get("wrong", 0)
    accuracy = round(verdict_counts.get("correct", 0) / max(total_graded, 1) * 100, 1)

    return {
        "verdicts": verdict_counts,
        "crowd_accuracy": crowd_accuracy,
        "overall_accuracy": accuracy,
        "total_graded": total_graded,
    }


def _analyze_memories(memories: list[dict]) -> dict:
    """Extract patterns from experience memory."""
    lesson_counter = Counter()
    category_counter = Counter()

    for m in memories:
        lesson = m.get("lesson", "") or m.get("summary", "")
        category = m.get("category", "general")
        category_counter[category] += 1

        for s in _match_patterns(lesson, _STRENGTH_PATTERNS):
            lesson_counter[s] += 1
        for mk in _match_patterns(lesson, _MISTAKE_PATTERNS):
            lesson_counter[mk] += 1

    return {
        "lessons": lesson_counter,
        "categories": category_counter,
    }


def _analyze_daily_reviews(reviews: list[dict]) -> dict:
    """Extract patterns from daily reviews."""
    outcome_counter = Counter()

    for r in reviews:
        summary = r.get("summary", "") or ""
        for m in _match_patterns(summary, _MISTAKE_PATTERNS):
            outcome_counter[f"mistake_{m}"] += 1
        for s in _match_patterns(summary, _STRENGTH_PATTERNS):
            outcome_counter[f"strength_{s}"] += 1

    return {"outcomes": outcome_counter}


def _analyze_rejected_news(news: list[dict]) -> dict:
    """Analyze rejected news to find most common rejected narrative types."""
    narrative_counter = Counter()

    for n in news:
        headline = n.get("headline", "")
        explanation = n.get("explanation", "")
        text = f"{headline} {explanation}"
        for nt in _match_patterns(text, _NARRATIVE_TYPES):
            narrative_counter[nt] += 1

    return {"rejected_narratives": narrative_counter}


# ---------------------------------------------------------------------------
# Confidence calibration
# ---------------------------------------------------------------------------

def _compute_confidence(count: int, source_count: int = 1) -> str:
    """Compute confidence level for a pattern.

    Args:
        count: Total evidence count across all sources.
        source_count: Number of distinct data sources that contributed.

    Returns:
        "low", "medium", or "high".
    """
    if count < 3:
        return "low"
    if count <= 6:
        # Downgrade if only 1 source feeds this pattern — could be noise
        if source_count <= 1:
            return "low"
        return "medium"
    # >6 evidence points
    if source_count <= 1:
        return "medium"  # high count but single source → not fully trusted
    return "high"


def _count_sources(pattern: str, *counters: Counter) -> int:
    """Count how many distinct data sources contain this pattern."""
    return sum(1 for c in counters if c.get(pattern, 0) > 0)


# ---------------------------------------------------------------------------
# Insight generation
# ---------------------------------------------------------------------------

_INSIGHT_TEMPLATES = {
    "early_entry": [
        "Entries may still be slightly early — confirmation tends to help.",
        "There's a pattern of entering before the signal fully forms.",
    ],
    "late_exit": [
        "Exits tend to lag a bit — earlier recognition could help.",
        "Holding slightly past signals appears to erode some gains.",
    ],
    "patience_wins": [
        "Patience seems to pay off, especially in weaker trends.",
        "Waiting for confirmation appears to keep working well.",
    ],
    "good_timing": [
        "Entry timing looks like a developing strength.",
        "Catching good entry points is becoming more consistent.",
    ],
    "discipline": [
        "Discipline under pressure appears to be paying off.",
        "Sticking to rules in difficult conditions seems to work.",
    ],
    "chased_hype": [
        "Crowd excitement tends to lead to weaker entries.",
        "Hype-driven trades may be underperforming overall.",
    ],
    "skepticism": [
        "Healthy skepticism seems to be filtering real noise well.",
        "Not chasing narratives appears to protect capital.",
    ],
    "bullish_hype": [
        "Bullish hype tends to be the most commonly rejected narrative.",
        "Moon talk is frequently filtered as noise — likely correctly.",
    ],
    "bearish_fud": [
        "Bearish scare stories appear to be the most rejected narrative type.",
        "Fear narratives tend to get dismissed — often correctly so.",
    ],
    "fought_trend": [
        "Counter-trend positions seem to lose more often than not.",
        "Fighting the trend appears as a recurring friction point.",
    ],
    "no_patience": [
        "Rushing decisions may be costing — waiting tends to work better.",
        "Impatience appears to lead to weaker outcomes.",
    ],
    "overtrading": [
        "There may be too many trades in low-quality conditions.",
        "Selectivity could help — fewer but better setups.",
    ],
    "ignored_signals": [
        "Clear signals may have been overlooked a few times.",
        "Paying closer attention to confirmed signals could help.",
    ],
    "poor_sizing": [
        "Position sizing looks slightly off in some cases.",
        "More consistent sizing might smooth out results.",
    ],
    "risk_control": [
        "Risk management appears to be a developing strength.",
        "Cutting losses effectively seems to be working.",
    ],
    "trend_following": [
        "Riding trends looks like a reliable approach so far.",
        "Trend-following entries seem to produce decent results.",
    ],
    "adaptability": [
        "Adapting to changing conditions seems to be working.",
        "Flexibility in approach appears to help outcomes.",
    ],
}


def _generate_insight(pattern_key: str, count: int) -> str:
    """Generate a human-readable insight for a pattern."""
    templates = _INSIGHT_TEMPLATES.get(pattern_key, [])
    if templates:
        idx = int(time.time() / 300) % len(templates)
        return templates[idx]
    label = _human_label(pattern_key)
    return f"{label} — seen {count} times."


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute(limit: int = 5) -> dict:
    """Compute recurring patterns across all data sources.

    Returns structured dict with top mistakes, strengths, rejected narratives,
    truth accuracy, and generated insights.
    """
    global _cache, _cache_ts

    now = time.time()
    if _cache and (now - _cache_ts) < _CACHE_TTL:
        return _cache

    try:
        import db
    except Exception:
        return _empty_result()

    # Gather data from all sources
    try:
        journals = db.get_recurring_patterns(pattern_type="mistake", limit=30)
        journals_lessons = db.get_recurring_patterns(pattern_type="lesson", limit=30)
        all_journals = journals + journals_lessons
    except Exception:
        all_journals = []

    try:
        reflections = db.get_lifetime_reflections(limit=100)
    except Exception:
        reflections = []

    try:
        truth_reviews = db.get_truth_reviews(limit=100)
    except Exception:
        truth_reviews = []

    try:
        memories = db.get_lifetime_memories(limit=100)
    except Exception:
        memories = []

    try:
        daily_reviews = db.get_lifetime_daily_reviews(limit=50)
    except Exception:
        daily_reviews = []

    try:
        # Get rejected news for narrative analysis
        rejected = db.get_news_analyses(verdict="reject", limit=100)
    except Exception:
        rejected = []

    # Analyze each source
    j_analysis = _analyze_journals(all_journals)
    r_analysis = _analyze_reflections(reflections)
    t_analysis = _analyze_truth_reviews(truth_reviews)
    m_analysis = _analyze_memories(memories)
    d_analysis = _analyze_daily_reviews(daily_reviews)
    n_analysis = _analyze_rejected_news(rejected)

    # Combine mistake patterns
    all_mistakes = Counter()
    all_mistakes.update(j_analysis["mistakes"])
    for k, v in r_analysis["timing"].items():
        if k.startswith("mistake_"):
            all_mistakes[k.replace("mistake_", "")] += v
    for k, v in d_analysis["outcomes"].items():
        if k.startswith("mistake_"):
            all_mistakes[k.replace("mistake_", "")] += v

    # Combine strength patterns
    all_strengths = Counter()
    all_strengths.update(j_analysis["lessons"])
    for k, v in r_analysis["timing"].items():
        if k.startswith("strength_"):
            all_strengths[k.replace("strength_", "")] += v
    for k, v in d_analysis["outcomes"].items():
        if k.startswith("strength_"):
            all_strengths[k.replace("strength_", "")] += v
    if r_analysis["patience"]["patience_helped"] > r_analysis["patience"].get("patience_hurt", 0):
        all_strengths["patience_wins"] += r_analysis["patience"]["patience_helped"]
    all_strengths.update(m_analysis["lessons"])

    # Top patterns
    top_mistakes = all_mistakes.most_common(limit)
    top_strengths = all_strengths.most_common(limit)
    top_narratives = n_analysis["rejected_narratives"].most_common(limit)

    # ------------------------------------------------------------------
    # Warm-up guard — need meaningful data before surfacing patterns
    # ------------------------------------------------------------------
    total_data = len(all_journals) + len(reflections) + len(truth_reviews) + len(memories)

    # Count actual trades from the trade ledger for a stricter check
    try:
        with db.get_db() as _conn:
            trade_count_row = _conn.execute(
                "SELECT COUNT(*) as c FROM trade_ledger"
            ).fetchone()
            total_trades = trade_count_row["c"] if trade_count_row else 0
    except Exception:
        total_trades = 0

    warming_up = total_trades < 10 or len(reflections) < 5

    if warming_up:
        result = _empty_result()
        result["message"] = "Still too early to detect meaningful patterns."
        result["data_depth"] = {
            "journals": len(all_journals),
            "reflections": len(reflections),
            "truth_reviews": len(truth_reviews),
            "memories": len(memories),
            "daily_reviews": len(daily_reviews),
            "rejected_news": len(rejected),
            "total_trades": total_trades,
            "total": total_data,
        }
        _cache = result
        _cache_ts = now
        return result

    # ------------------------------------------------------------------
    # Source counters for confidence calibration
    # ------------------------------------------------------------------
    # Track which sources contributed to each pattern
    journal_mistakes = j_analysis["mistakes"]
    reflection_mistakes = Counter({
        k.replace("mistake_", ""): v
        for k, v in r_analysis["timing"].items() if k.startswith("mistake_")
    })
    daily_mistakes = Counter({
        k.replace("mistake_", ""): v
        for k, v in d_analysis["outcomes"].items() if k.startswith("mistake_")
    })

    journal_strengths = j_analysis["lessons"]
    reflection_strengths = Counter({
        k.replace("strength_", ""): v
        for k, v in r_analysis["timing"].items() if k.startswith("strength_")
    })
    daily_strengths = Counter({
        k.replace("strength_", ""): v
        for k, v in d_analysis["outcomes"].items() if k.startswith("strength_")
    })
    memory_lessons = m_analysis["lessons"]

    # ------------------------------------------------------------------
    # Build enriched pattern entries with confidence
    # ------------------------------------------------------------------
    def _enrich_mistake(p: str, c: int) -> dict:
        src = _count_sources(p, journal_mistakes, reflection_mistakes, daily_mistakes)
        conf = _compute_confidence(c, src)
        return {"pattern": p, "label": _human_label(p), "count": c,
                "confidence": conf, "source_count": src}

    def _enrich_strength(p: str, c: int) -> dict:
        src = _count_sources(p, journal_strengths, reflection_strengths,
                             daily_strengths, memory_lessons)
        conf = _compute_confidence(c, src)
        return {"pattern": p, "label": _human_label(p), "count": c,
                "confidence": conf, "source_count": src}

    def _enrich_narrative(p: str, c: int) -> dict:
        conf = _compute_confidence(c, 1)  # single source (rejected news)
        return {"pattern": p, "label": _human_label(p), "count": c,
                "confidence": conf, "source_count": 1}

    # Generate insights (max 5 bullets) — with confidence
    insights = []
    for pattern, count in top_mistakes[:2]:
        if count >= 2:
            src = _count_sources(pattern, journal_mistakes, reflection_mistakes, daily_mistakes)
            conf = _compute_confidence(count, src)
            insights.append({
                "type": "mistake",
                "pattern": pattern,
                "label": _human_label(pattern),
                "count": count,
                "confidence": conf,
                "insight": _generate_insight(pattern, count),
            })
    for pattern, count in top_strengths[:2]:
        if count >= 2:
            src = _count_sources(pattern, journal_strengths, reflection_strengths,
                                 daily_strengths, memory_lessons)
            conf = _compute_confidence(count, src)
            insights.append({
                "type": "strength",
                "pattern": pattern,
                "label": _human_label(pattern),
                "count": count,
                "confidence": conf,
                "insight": _generate_insight(pattern, count),
            })
    if top_narratives and top_narratives[0][1] >= 2:
        pattern, count = top_narratives[0]
        conf = _compute_confidence(count, 1)
        insights.append({
            "type": "narrative",
            "pattern": pattern,
            "label": _human_label(pattern),
            "count": count,
            "confidence": conf,
            "insight": _generate_insight(pattern, count),
        })

    result = {
        "top_mistakes": [_enrich_mistake(p, c) for p, c in top_mistakes],
        "top_strengths": [_enrich_strength(p, c) for p, c in top_strengths],
        "top_rejected_narratives": [_enrich_narrative(p, c) for p, c in top_narratives],
        "truth_accuracy": {
            "accuracy_pct": t_analysis["overall_accuracy"],
            "total_graded": t_analysis["total_graded"],
            "verdicts": dict(t_analysis["verdicts"]),
        },
        "grade_distribution": dict(r_analysis["grades"]),
        "patience_stats": dict(r_analysis["patience"]),
        "insights": insights,
        "data_depth": {
            "journals": len(all_journals),
            "reflections": len(reflections),
            "truth_reviews": len(truth_reviews),
            "memories": len(memories),
            "daily_reviews": len(daily_reviews),
            "rejected_news": len(rejected),
            "total_trades": total_trades,
            "total": total_data,
        },
        "warming_up": warming_up,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    _cache = result
    _cache_ts = now
    return result


def get_insight_bullets(max_bullets: int = 3) -> list[str]:
    """Get top insight bullets as simple strings for UI cards."""
    data = compute()
    if data.get("warming_up"):
        return ["Still too early for strong recurring patterns."]

    bullets = []
    for ins in data.get("insights", [])[:max_bullets]:
        bullets.append(ins["insight"])

    if not bullets:
        return ["Not enough recurring patterns detected yet."]

    return bullets


def _empty_result() -> dict:
    """Safe empty result for warm-up / error states."""
    return {
        "top_mistakes": [],
        "top_strengths": [],
        "top_rejected_narratives": [],
        "truth_accuracy": {"accuracy_pct": 0, "total_graded": 0, "verdicts": {}},
        "grade_distribution": {},
        "patience_stats": {},
        "insights": [],
        "data_depth": {"total": 0, "total_trades": 0},
        "warming_up": True,
        "message": "Still too early to detect meaningful patterns.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
