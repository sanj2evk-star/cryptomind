"""
user_manager.py - Multi-user management.

Stores user accounts in data/users.json. Each user gets
an isolated data directory under data/users/{user_id}/ with
their own portfolio, trades, decisions, equity, and strategies.

Passwords are hashed with SHA-256 + per-user salt.

Usage:
    from user_manager import create_user, verify_user, get_user_data_dir
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from config import DATA_DIR, INITIAL_BALANCE

USERS_FILE = DATA_DIR / "users.json"
USERS_DATA_DIR = DATA_DIR / "users"


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

def _hash_password(password: str, salt: str) -> str:
    """Hash a password with salt using SHA-256.

    Args:
        password: Plain text password.
        salt: Random salt string.

    Returns:
        Hex digest of salted hash.
    """
    return hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()


# ---------------------------------------------------------------------------
# User store I/O
# ---------------------------------------------------------------------------

def _load_users() -> dict:
    """Load the users dict from disk.

    Returns:
        Dict mapping user_id -> user record.
    """
    try:
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_users(users: dict) -> None:
    """Write the users dict to disk.

    Args:
        users: Dict mapping user_id -> user record.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    USERS_FILE.write_text(
        json.dumps(users, indent=2) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# User CRUD
# ---------------------------------------------------------------------------

def create_user(user_id: str, password: str, display_name: str = "") -> bool:
    """Create a new user account.

    Sets up:
    - User record in users.json
    - Isolated data directory with default portfolio

    Args:
        user_id: Unique username (lowercase, no spaces).
        password: Plain text password (will be hashed).
        display_name: Optional display name.

    Returns:
        True if created, False if user already exists.
    """
    users = _load_users()
    user_id = user_id.strip().lower()

    if user_id in users:
        return False

    salt = os.urandom(16).hex()
    users[user_id] = {
        "display_name": display_name or user_id,
        "password_hash": _hash_password(password, salt),
        "salt": salt,
        "created_at": _now(),
    }

    _save_users(users)
    _init_user_data(user_id)
    return True


def verify_user(user_id: str, password: str) -> bool:
    """Verify a user's password.

    Args:
        user_id: Username.
        password: Plain text password.

    Returns:
        True if credentials are valid.
    """
    users = _load_users()
    user_id = user_id.strip().lower()
    user = users.get(user_id)

    if user is None:
        return False

    expected = _hash_password(password, user["salt"])
    return expected == user["password_hash"]


def list_users() -> list[dict]:
    """List all registered users (without password data).

    Returns:
        List of user summary dicts.
    """
    users = _load_users()
    return [
        {"user_id": uid, "display_name": u.get("display_name", uid), "created_at": u.get("created_at", "")}
        for uid, u in users.items()
    ]


def delete_user(user_id: str) -> bool:
    """Delete a user account. Does NOT delete their data directory.

    Args:
        user_id: Username to delete.

    Returns:
        True if deleted, False if not found.
    """
    users = _load_users()
    user_id = user_id.strip().lower()

    if user_id not in users:
        return False

    del users[user_id]
    _save_users(users)
    return True


# ---------------------------------------------------------------------------
# User data paths
# ---------------------------------------------------------------------------

def get_user_data_dir(user_id: str) -> Path:
    """Get the isolated data directory for a user.

    Args:
        user_id: Username.

    Returns:
        Path to data/users/{user_id}/.
    """
    return USERS_DATA_DIR / user_id.strip().lower()


def get_user_file(user_id: str, filename: str) -> Path:
    """Get a specific file path within a user's data directory.

    Creates the directory if it doesn't exist (safe for first-run on Render).

    Args:
        user_id: Username.
        filename: File name (e.g. 'portfolio.json').

    Returns:
        Full path to the file.
    """
    user_dir = get_user_data_dir(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir / filename


# ---------------------------------------------------------------------------
# User data initialization
# ---------------------------------------------------------------------------

def _init_user_data(user_id: str) -> None:
    """Create the default data files for a new user.

    Args:
        user_id: Username.
    """
    user_dir = get_user_data_dir(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)

    # Default portfolio
    portfolio = {
        "cash": INITIAL_BALANCE,
        "positions": {},
        "realized_pnl": 0.0,
        "total_trades": 0,
        "trades_today": 0,
        "last_trade_date": "",
        "last_trade_time": "",
        "peak_equity": INITIAL_BALANCE,
        "consecutive_losses": 0,
        "circuit_breaker_until": "",
    }
    _write_json(user_dir / "portfolio.json", portfolio)

    # Empty CSVs with headers
    _write_csv(user_dir / "trades.csv",
               ["timestamp", "action", "price", "quantity", "pnl", "cash_after",
                "strategy", "strength", "market_condition"])
    _write_csv(user_dir / "decisions.csv",
               ["timestamp", "action", "confidence", "reasoning", "signals", "risk"])
    _write_csv(user_dir / "equity.csv",
               ["timestamp", "price", "cash", "position_size",
                "unrealized_pnl", "realized_pnl", "total_equity"])

    # Empty strategies
    _write_json(user_dir / "strategies.json", [])


def _write_json(path: Path, data) -> None:
    """Write JSON to a file."""
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _write_csv(path: Path, headers: list[str]) -> None:
    """Write a CSV file with only headers."""
    import csv
    with open(path, "w", newline="") as f:
        csv.DictWriter(f, fieldnames=headers).writeheader()


def _now() -> str:
    """UTC ISO timestamp."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Default admin user
# ---------------------------------------------------------------------------

def ensure_admin() -> None:
    """Create the default admin user if no users exist.

    Uses API_USERNAME/API_PASSWORD from env, or admin/changeme.
    """
    users = _load_users()
    if users:
        return

    username = os.getenv("API_USERNAME", "admin")
    password = os.getenv("API_PASSWORD", "changeme")
    create_user(username, password, display_name="Admin")
    print(f"[user_manager] Created default admin user: {username}")
