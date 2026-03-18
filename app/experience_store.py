"""
experience_store.py - Persistent experience buffer.

Saves and loads RL experiences (state, action, reward, outcome)
to data/experience_buffer.json. Supports appending, bulk loading,
random sampling, and summary stats.

JSON format:
[
  {
    "state": ["ema_signal", "rsi_zone", "regime", "position"],
    "action": "BUY",
    "reward": 0.05,
    "outcome": {
      "next_state": ["ema_signal", "rsi_zone", "regime", "position"],
      "pnl": 0.03,
      "equity_after": 100.03
    },
    "timestamp": "2026-03-18T..."
  }
]
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from pathlib import Path

from config import DATA_DIR

BUFFER_FILE = DATA_DIR / "experience_buffer.json"
ACTIONS = ["BUY", "SELL", "HOLD"]
MAX_BUFFER_SIZE = 10000


# ---------------------------------------------------------------------------
# Core I/O
# ---------------------------------------------------------------------------

def _load_raw() -> list[dict]:
    """Load the raw experience list from disk.

    Returns:
        List of experience dicts, or empty list if missing/corrupt.
    """
    try:
        return json.loads(BUFFER_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_raw(experiences: list[dict]) -> None:
    """Write the experience list to disk.

    Args:
        experiences: List of experience dicts.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BUFFER_FILE.write_text(
        json.dumps(experiences, indent=2) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def save_experience(
    state: tuple | list,
    action: int | str,
    reward: float,
    next_state: tuple | list = None,
    pnl: float = 0.0,
    equity_after: float = 0.0,
) -> None:
    """Append a single experience to the buffer.

    Args:
        state: Current state (tuple or list of strings).
        action: Action taken (int index or string name).
        reward: Reward received.
        next_state: Resulting state (optional).
        pnl: Realized P&L from this action.
        equity_after: Portfolio equity after this action.
    """
    experiences = _load_raw()

    # Normalize action to string
    if isinstance(action, int) and 0 <= action < len(ACTIONS):
        action = ACTIONS[action]

    entry = {
        "state": list(state),
        "action": str(action),
        "reward": round(reward, 6),
        "outcome": {
            "next_state": list(next_state) if next_state else None,
            "pnl": round(pnl, 6),
            "equity_after": round(equity_after, 4),
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    experiences.append(entry)

    # Trim to max size (keep most recent)
    if len(experiences) > MAX_BUFFER_SIZE:
        experiences = experiences[-MAX_BUFFER_SIZE:]

    _save_raw(experiences)


def save_batch(entries: list[dict]) -> int:
    """Append multiple experiences at once.

    Args:
        entries: List of dicts, each with state, action, reward, outcome keys.

    Returns:
        Number of experiences saved.
    """
    experiences = _load_raw()
    experiences.extend(entries)

    if len(experiences) > MAX_BUFFER_SIZE:
        experiences = experiences[-MAX_BUFFER_SIZE:]

    _save_raw(experiences)
    return len(entries)


def load_experiences() -> list[dict]:
    """Load all experiences from the buffer.

    Returns:
        List of experience dicts, chronological order.
    """
    return _load_raw()


def sample_experiences(n: int) -> list[dict]:
    """Randomly sample N experiences from the buffer.

    Args:
        n: Number of experiences to sample.

    Returns:
        List of sampled experience dicts.
    """
    experiences = _load_raw()
    return random.sample(experiences, min(n, len(experiences)))


def get_stats() -> dict:
    """Compute summary statistics for the experience buffer.

    Returns:
        dict with total, action counts, avg reward, reward range.
    """
    experiences = _load_raw()
    total = len(experiences)

    if total == 0:
        return {"total": 0, "actions": {}, "avg_reward": 0.0, "min_reward": 0.0, "max_reward": 0.0}

    rewards = [e.get("reward", 0.0) for e in experiences]
    actions = {}
    for e in experiences:
        a = e.get("action", "UNKNOWN")
        actions[a] = actions.get(a, 0) + 1

    return {
        "total": total,
        "actions": actions,
        "avg_reward": round(sum(rewards) / total, 6),
        "min_reward": round(min(rewards), 6),
        "max_reward": round(max(rewards), 6),
    }


def clear() -> None:
    """Clear all experiences from the buffer."""
    _save_raw([])


def count() -> int:
    """Return the number of stored experiences."""
    return len(_load_raw())
