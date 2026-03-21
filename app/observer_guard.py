"""
observer_guard.py — CryptoMind v7.4 Observer Isolation Guard.

Ensures observer modules remain strictly read-only:
  - No writes to trading tables (trade_ledger, cycle_snapshots, etc.)
  - No imports of execution-side modules from observer code
  - Runtime verification of observer boundaries

Called once at startup. Logs results. Does NOT block — just warns loudly.
"""

from __future__ import annotations

import importlib
import inspect
import sys
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Observer module whitelist — only these are observer modules
# ---------------------------------------------------------------------------

OBSERVER_MODULES = {
    "news_ingestor",
    "news_classifier",
    "bullshit_radar",
    "mind_state_engine",
    "mind_feed_engine",
    "action_narrator",
    "observer_guard",
    "personality_engine",
    "session_intent_engine",
    "milestone_engine",
    "lifetime_mind_aggregator",
    "news_truth_validator",
    "contextual_summary_engine",
    "mind_journal_engine",
    "action_reflection_engine",
    "replay_engine",
}

# Execution-side modules that observers must NEVER import
FORBIDDEN_IMPORTS = {
    "auto_trader",
    "multi_strategy",
    "paper_broker",
    "decision_engine",
    "feedback",
    "discipline_guard",
}

# Trading tables that observers must NEVER write to
PROTECTED_TABLES = {
    "trade_ledger",
    "cycle_snapshots",
    "version_sessions",
    "system_state",
    "behavior_profiles",
    "behavior_states",
    "adaptation_events",
    "adaptation_journal",
    "experience_memory",
    "experience_outcomes",
    "missed_opportunities",
    "regime_profiles",
    "daily_bias",
    "evolution_snapshots",
    "milestones",
}

# Observer-owned tables (these are OK to write to)
OBSERVER_TABLES = {
    "news_events",
    "news_event_analysis",
    "mind_feed_events",
    "mind_state_snapshots",
    "news_truth_reviews",
    "mind_journal_entries",
    "action_reflections",
    "replay_markers",
}

# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

_results: list[dict] = []


def verify_imports() -> list[dict]:
    """Check that loaded observer modules don't import forbidden modules.

    Returns list of violations (empty = clean).
    """
    violations = []
    for mod_name in OBSERVER_MODULES:
        if mod_name not in sys.modules:
            continue
        mod = sys.modules[mod_name]
        source = ""
        try:
            source = inspect.getsource(mod)
        except (TypeError, OSError):
            continue

        # Split into actual code lines (skip comments and docstrings)
        code_lines = []
        in_docstring = False
        for line in source.split("\n"):
            stripped = line.strip()
            if stripped.startswith('"""') or stripped.startswith("'''"):
                if in_docstring:
                    in_docstring = False
                    continue
                # Single-line docstring
                if stripped.count('"""') >= 2 or stripped.count("'''") >= 2:
                    continue
                in_docstring = True
                continue
            if in_docstring:
                continue
            if stripped.startswith("#"):
                continue
            code_lines.append(stripped)

        code_text = "\n".join(code_lines)

        for forbidden in FORBIDDEN_IMPORTS:
            # Check for actual import statements (not mentions in strings)
            patterns = [
                f"import {forbidden}",
                f"from {forbidden}",
            ]
            for pat in patterns:
                if pat in code_text:
                    violations.append({
                        "module":    mod_name,
                        "violation": f"imports '{forbidden}' — execution-side module",
                        "severity":  "critical",
                        "pattern":   pat,
                    })

    return violations


def verify_table_access() -> list[dict]:
    """Scan observer module source for INSERT/UPDATE/DELETE on protected tables.

    Returns list of violations (empty = clean).
    """
    violations = []
    danger_patterns = ["INSERT INTO", "UPDATE ", "DELETE FROM", "DROP TABLE"]

    for mod_name in OBSERVER_MODULES:
        if mod_name == "observer_guard":
            continue  # skip self — we reference table names in config sets
        if mod_name not in sys.modules:
            continue
        mod = sys.modules[mod_name]
        try:
            source = inspect.getsource(mod)
        except (TypeError, OSError):
            continue

        source_upper = source.upper()
        for table in PROTECTED_TABLES:
            for danger in danger_patterns:
                # Look for "INSERT INTO trade_ledger" etc.
                check = f"{danger} {table}".upper()
                if check in source_upper:
                    violations.append({
                        "module":    mod_name,
                        "violation": f"writes to protected table '{table}' ({danger})",
                        "severity":  "critical",
                        "table":     table,
                    })

    return violations


def run_all_checks() -> dict:
    """Run full isolation verification. Call at startup."""
    global _results

    import_violations = verify_imports()
    table_violations  = verify_table_access()
    all_violations    = import_violations + table_violations

    clean = len(all_violations) == 0

    result = {
        "clean":      clean,
        "violations": all_violations,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "observer_modules": list(OBSERVER_MODULES),
        "modules_loaded":   [m for m in OBSERVER_MODULES if m in sys.modules],
    }

    _results = all_violations

    if clean:
        print("[observer_guard] ✓ All observer modules are clean — no isolation violations.")
    else:
        print(f"[observer_guard] ✗ {len(all_violations)} ISOLATION VIOLATION(S) DETECTED:")
        for v in all_violations:
            print(f"  [{v['severity'].upper()}] {v['module']}: {v['violation']}")

    return result


def get_status() -> dict:
    """Get last verification result for API."""
    return {
        "clean":      len(_results) == 0,
        "violations": _results,
        "observer_modules": list(OBSERVER_MODULES),
        "protected_tables": list(PROTECTED_TABLES),
        "observer_tables":  list(OBSERVER_TABLES),
    }
