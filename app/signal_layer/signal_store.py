"""
signal_store.py — Persistent storage for signal events.

Handles insert/query for the signal_events table in db.py.
Thread-safe, deduplication-aware.

Observer-only — NEVER influences trades.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone


def insert_signal_event(
    source: str,
    signal_type: str,
    direction: str,
    strength: float,
    confidence: float,
    raw_value: float = 0.0,
    context: str = "",
    meta: dict | None = None,
    session_id: int = None,
) -> int:
    """Persist a normalized signal event. Returns the row ID."""
    import db
    import session_manager

    sid = session_id or session_manager.get_session_id()
    if not sid:
        return 0

    return db.insert_signal_event(
        session_id=sid,
        source=source,
        signal_type=signal_type,
        direction=direction,
        strength=strength,
        confidence=confidence,
        raw_value=raw_value,
        context=context,
        meta_json=json.dumps(meta) if meta else None,
    )


def get_latest(limit: int = 20, source: str = None) -> list[dict]:
    """Get recent signal events, newest first."""
    import db
    return db.get_signal_events(limit=limit, source=source)


def get_history(limit: int = 100, session_id: int = None) -> list[dict]:
    """Get signal event history for a session."""
    import db
    import session_manager
    sid = session_id or session_manager.get_session_id()
    return db.get_signal_events(limit=limit, session_id=sid)
