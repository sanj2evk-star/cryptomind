"""
lifetime_rehydration_engine.py — CryptoMind v7.7.0

Builds live lifetime summaries from all available historical data sources.
Runs on startup, version transition, and on-demand.

Rehydration sources (in priority order):
  1. trade_ledger        — v7 trades (authoritative for v7+)
  2. auto_trades.csv     — pre-v7 historical trades
  3. cycle_snapshots     — v7 cycle data
  4. experience_memory   — learned patterns
  5. daily_reviews       — daily summaries
  6. evolution_snapshots — growth milestones
  7. milestones          — achievement records
  8. lifetime_identity   — persistent identity
  9. lifetime_portfolio  — persistent capital state
 10. capital_ledger      — financial event log
 11. version_sessions    — version history

Output (cached in _cache):
  - identity_summary     — who the system is, continuity story
  - capital_summary      — full capital story
  - performance_summary  — trading statistics (all-time)
  - memory_summary       — learning state
  - rehydration_status   — good / partial / empty
  - sources_used         — list of sources that contributed data
  - sources_empty        — list of sources that were empty
  - rehydrated_at        — ISO timestamp

Safety rules:
  - NEVER fabricate data
  - NEVER reduce counters
  - Report honestly when sources are empty
  - "partial" if some but not all key sources have data
"""

from __future__ import annotations

import csv
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import DATA_DIR, INITIAL_BALANCE

# ---------------------------------------------------------------------------
# Module cache — rebuilt on startup and on demand
# ---------------------------------------------------------------------------

_cache: dict = {}
_cache_time: float = 0.0
_CACHE_TTL: float = 300.0  # 5 minutes between full rebuilds


def get_rehydration_summary() -> dict:
    """Return cached rehydration summary, rebuilding if stale."""
    global _cache, _cache_time
    if not _cache or (time.time() - _cache_time) > _CACHE_TTL:
        _cache = rehydrate()
        _cache_time = time.time()
    return _cache


def force_rehydrate() -> dict:
    """Force a full rehydration, bypassing the cache. Called on startup."""
    global _cache, _cache_time
    _cache = rehydrate()
    _cache_time = time.time()
    return _cache


# ---------------------------------------------------------------------------
# Main rehydration function
# ---------------------------------------------------------------------------

def rehydrate() -> dict:
    """
    Rebuild live lifetime summaries from all available historical data.
    Returns a complete rehydration result dict.
    Does NOT modify data if nothing useful is found — reports empty honestly.
    """
    sources_used: list[str] = []
    sources_empty: list[str] = []

    # 1. Load v7 DB trades
    db_trades = _load_db_trades()
    if db_trades:
        sources_used.append("trade_ledger")
    else:
        sources_empty.append("trade_ledger")

    # 2. Load pre-v7 CSV trades (BUY/SELL only)
    csv_trades = _load_csv_trades()
    if csv_trades:
        sources_used.append("auto_trades.csv")
    else:
        sources_empty.append("auto_trades.csv")

    # 3. Merge all trades (DB authoritative, CSV fills gaps)
    all_trades = _merge_trades(db_trades, csv_trades)

    # 4. Build summaries
    perf = _build_performance_summary(all_trades)

    capital = _build_capital_summary()
    if capital.get("total_events", 0) > 0:
        sources_used.append("capital_ledger")
    else:
        sources_empty.append("capital_ledger")

    identity = _build_identity_summary()
    if identity.get("total_sessions", 0) > 0:
        sources_used.append("version_sessions")
    if identity.get("total_cycles", 0) > 0:
        sources_used.append("cycle_snapshots")

    memory = _build_memory_summary()
    if memory.get("memory_count", 0) > 0:
        sources_used.append("experience_memory")
    else:
        sources_empty.append("experience_memory")
    if memory.get("journal_count", 0) > 0:
        sources_used.append("daily_reviews")
    else:
        sources_empty.append("daily_reviews")

    # 5. Compute date-windowed summaries
    date_summaries = _build_date_summaries(all_trades)

    # 6. Non-destructive update of lifetime tables from rehydrated data
    if all_trades:
        _update_lifetime_tables_from_trades(perf, all_trades)

    # 7. Determine rehydration status
    status = _compute_status(sources_used, all_trades)

    print(f"[rehydration] status={status}  sources_used={sources_used}  "
          f"total_trades={len(all_trades)}")

    return {
        "rehydration_status": status,
        "sources_used": sources_used,
        "sources_empty": sources_empty,
        "identity_summary": identity,
        "capital_summary": capital,
        "performance_summary": perf,
        "memory_summary": memory,
        "date_summaries": date_summaries,
        "total_trades_found": len(all_trades),
        "rehydrated_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def _load_db_trades() -> list[dict]:
    """Load all trades from trade_ledger (v7 authoritative store)."""
    try:
        import db as v7db
        with v7db.get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM trade_ledger ORDER BY trade_id"
            ).fetchall()
            return v7db.rows_to_dicts(rows)
    except Exception as e:
        print(f"[rehydration] Could not load trade_ledger: {e}")
        return []


def _load_csv_trades(user_id: str = "admin") -> list[dict]:
    """Load BUY/SELL trades from auto_trades.csv (pre-v7 era)."""
    csv_path = DATA_DIR / "users" / user_id / "auto_trades.csv"
    if not csv_path.exists():
        return []

    trades: list[dict] = []
    try:
        with open(csv_path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                action = (row.get("action") or "").strip().upper()
                if action not in ("BUY", "SELL"):
                    continue
                trades.append({
                    "source": "csv",
                    "timestamp": row.get("timestamp", ""),
                    "action": action,
                    "price": _safe_float(row.get("price", 0)),
                    "qty": _safe_float(row.get("quantity", 0)),
                    "pnl": _safe_float(row.get("pnl", 0)),
                    "confidence": _safe_float(row.get("confidence", 0)),
                    "strategy": "legacy",
                    "regime": "unknown",
                    "version_tag": "pre-v7",
                })
    except Exception as e:
        print(f"[rehydration] Could not load auto_trades.csv: {e}")
    return trades


def _merge_trades(db_trades: list[dict], csv_trades: list[dict]) -> list[dict]:
    """Merge DB and CSV trades. DB trades are authoritative — CSV fills pre-v7 gaps."""
    # Index DB trades by truncated-second timestamp + action to detect dups
    db_keys: set[str] = set()
    for t in db_trades:
        ts = (t.get("timestamp") or "")[:19]
        db_keys.add(f"{ts}:{t.get('action', '')}")

    merged = list(db_trades)
    for t in csv_trades:
        ts = (t.get("timestamp") or "")[:19]
        key = f"{ts}:{t.get('action', '')}"
        if key not in db_keys:
            merged.append(t)

    merged.sort(key=lambda x: x.get("timestamp") or "")
    return merged


# ---------------------------------------------------------------------------
# Summary builders
# ---------------------------------------------------------------------------

def _build_performance_summary(trades: list[dict]) -> dict:
    """Compute lifetime performance stats from all available trades."""
    if not trades:
        return {
            "total_trades": 0, "buys": 0, "sells": 0,
            "wins": 0, "losses": 0, "win_rate": 0,
            "total_pnl": 0.0, "avg_pnl": 0.0,
            "best_trade": 0.0, "worst_trade": 0.0,
            "strategies": {}, "data_available": False,
        }

    buys = [t for t in trades if t.get("action") == "BUY"]
    sells = [t for t in trades if t.get("action") == "SELL"]
    wins = [t for t in sells if _safe_float(t.get("pnl", 0)) > 0]
    losses = [t for t in sells if _safe_float(t.get("pnl", 0)) <= 0]

    pnls = [_safe_float(t.get("pnl", 0)) for t in sells]
    total_pnl = sum(pnls)
    avg_pnl = total_pnl / len(pnls) if pnls else 0.0

    # Strategy breakdown
    strategies: dict[str, dict] = {}
    for t in trades:
        s = t.get("strategy") or "unknown"
        if s not in strategies:
            strategies[s] = {"trades": 0, "wins": 0, "pnl": 0.0}
        strategies[s]["trades"] += 1
        if t.get("action") == "SELL":
            p = _safe_float(t.get("pnl", 0))
            strategies[s]["pnl"] = round(strategies[s]["pnl"] + p, 6)
            if p > 0:
                strategies[s]["wins"] += 1

    return {
        "total_trades": len(trades),
        "buys": len(buys),
        "sells": len(sells),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(sells) * 100, 1) if sells else 0,
        "total_pnl": round(total_pnl, 6),
        "avg_pnl": round(avg_pnl, 6),
        "best_trade": round(max(pnls), 6) if pnls else 0.0,
        "worst_trade": round(min(pnls), 6) if pnls else 0.0,
        "strategies": strategies,
        "data_available": len(trades) > 0,
    }


def _build_capital_summary() -> dict:
    """Build full capital story from lifetime_portfolio + capital_ledger."""
    try:
        import db as v7db
        portfolio = v7db.get_lifetime_portfolio() or {}
        cap_summary = v7db.get_capital_summary() or {}
        recent_events = v7db.get_capital_events(limit=5) or []

        initial = cap_summary.get("initial_funding") or INITIAL_BALANCE
        equity = portfolio.get("total_equity") or INITIAL_BALANCE
        refill_total = portfolio.get("total_refill_amount") or 0.0
        net_pnl = round(equity - initial + refill_total, 4) if initial else 0.0

        return {
            "current_cash": portfolio.get("cash", INITIAL_BALANCE),
            "total_equity": equity,
            "peak_equity": portfolio.get("peak_equity", INITIAL_BALANCE),
            "realized_pnl": portfolio.get("realized_pnl", 0.0),
            "total_refills": portfolio.get("total_refills", 0),
            "total_refill_amount": refill_total,
            "initial_funding": initial,
            "total_events": cap_summary.get("total_events", 0),
            "net_pnl_vs_funding": net_pnl,
            "recent_events": recent_events,
        }
    except Exception as e:
        print(f"[rehydration] Could not build capital summary: {e}")
        return {
            "current_cash": INITIAL_BALANCE, "total_equity": INITIAL_BALANCE,
            "peak_equity": INITIAL_BALANCE, "realized_pnl": 0.0,
            "total_refills": 0, "total_refill_amount": 0.0,
            "initial_funding": INITIAL_BALANCE, "total_events": 0,
            "net_pnl_vs_funding": 0.0, "recent_events": [],
        }


def _build_identity_summary() -> dict:
    """Build identity from lifetime_identity + version_sessions + cycle data."""
    try:
        import db as v7db
        identity = v7db.get_lifetime_identity() or {}
        sessions = v7db.get_all_sessions() or []
        system = v7db.get_system_state() or {}

        total_cycles = system.get("total_lifetime_cycles", 0) or 0
        versions_seen = sorted(set(s.get("app_version", "?") for s in sessions))

        # Time since first seen
        first_seen = identity.get("first_seen_at")
        if not first_seen and sessions:
            first_seen = sessions[0].get("started_at")
        age_days = 0
        if first_seen:
            try:
                first_dt = datetime.fromisoformat(first_seen.replace("Z", "+00:00"))
                age_days = (datetime.now(timezone.utc) - first_dt).days
            except Exception:
                pass

        return {
            "total_sessions": len(sessions),
            "total_cycles": total_cycles,
            "total_trades": identity.get("total_trades", 0) or 0,
            "versions_seen": versions_seen,
            "current_version": system.get("current_version", "?"),
            "first_seen_at": first_seen,
            "age_days": age_days,
            "continuity_score": identity.get("continuity_score", 0.0),
            "memory_depth_score": identity.get("memory_depth_score", 0.0),
            "last_version": identity.get("last_version", "?"),
            "has_history": total_cycles > 0 or len(sessions) > 1,
        }
    except Exception as e:
        print(f"[rehydration] Could not build identity summary: {e}")
        return {
            "total_sessions": 0, "total_cycles": 0, "total_trades": 0,
            "versions_seen": [], "current_version": "?", "first_seen_at": None,
            "age_days": 0, "continuity_score": 0.0, "memory_depth_score": 0.0,
            "last_version": "?", "has_history": False,
        }


def _build_memory_summary() -> dict:
    """Build memory summary from experience_memory + daily_reviews."""
    try:
        import db as v7db
        mem_summary = v7db.get_lifetime_memories_summary() or {}
        reviews = v7db.get_lifetime_daily_reviews(limit=5) or []

        latest_insight = ""
        if reviews:
            r = reviews[0]
            latest_insight = (
                r.get("behavior_observation")
                or r.get("what_worked")
                or r.get("next_day_bias")
                or ""
            )

        return {
            "memory_count": mem_summary.get("total", 0) or 0,
            "active_memories": mem_summary.get("active", 0) or 0,
            "journal_count": len(reviews),
            "latest_review_date": reviews[0].get("review_date") if reviews else None,
            "latest_insight": latest_insight[:200] if latest_insight else "",
            "has_memory": (mem_summary.get("total", 0) or 0) > 0,
        }
    except Exception as e:
        print(f"[rehydration] Could not build memory summary: {e}")
        return {
            "memory_count": 0, "active_memories": 0, "journal_count": 0,
            "latest_review_date": None, "latest_insight": "", "has_memory": False,
        }


def _build_date_summaries(all_trades: list[dict]) -> dict:
    """Build daily/weekly/monthly performance windows from merged trade history."""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    windows = {
        "daily":   now - timedelta(days=1),
        "weekly":  now - timedelta(days=7),
        "monthly": now - timedelta(days=30),
    }
    result: dict[str, dict] = {}
    for label, cutoff in windows.items():
        windowed = []
        for t in all_trades:
            ts_str = t.get("timestamp") or ""
            if not ts_str:
                continue
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts >= cutoff:
                    windowed.append(t)
            except Exception:
                continue
        result[label] = _build_performance_summary(windowed)
        result[label]["window"] = label
        result[label]["since"] = cutoff.isoformat()
    return result


# ---------------------------------------------------------------------------
# Lifetime table update (non-destructive)
# ---------------------------------------------------------------------------

def _update_lifetime_tables_from_trades(perf: dict, all_trades: list[dict]) -> None:
    """Update lifetime_portfolio with rehydrated trade stats.
    Only fires when rehydrated data > stored values (anti-reduction guardrail in db.py)."""
    try:
        import db as v7db
        sells = [t for t in all_trades if t.get("action") == "SELL"]
        wins = [t for t in sells if _safe_float(t.get("pnl", 0)) > 0]

        v7db.upsert_lifetime_portfolio(
            total_trades=len(all_trades),
            total_wins=len(wins),
            total_losses=len(sells) - len(wins),
            realized_pnl=round(perf.get("total_pnl", 0), 6),
        )
    except Exception as e:
        print(f"[rehydration] Could not update lifetime tables: {e}")


# ---------------------------------------------------------------------------
# Status computation
# ---------------------------------------------------------------------------

def _compute_status(sources_used: list[str], all_trades: list[dict]) -> str:
    """Return: good / partial / empty"""
    if not sources_used:
        return "empty"

    rich_sources = {"trade_ledger", "auto_trades.csv", "cycle_snapshots"}
    used_rich = rich_sources & set(sources_used)

    if used_rich and len(all_trades) > 0:
        return "good"
    if used_rich or len(sources_used) >= 2:
        return "partial"
    return "partial" if sources_used else "empty"


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _safe_float(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0
