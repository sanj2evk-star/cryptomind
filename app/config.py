"""
config.py - Configuration loader.

Reads settings from a .env file and defines trading constants.
Centralizes all configurable parameters: API keys, trading pair,
timeframe, position sizing, and risk limits.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# -- Paths --
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = PROJECT_ROOT / "prompts"
ENV_PATH = PROJECT_ROOT / ".env"

# Data directory: use Render persistent disk if mounted, otherwise project-relative.
# /var/data is the Render persistent disk mount — files here survive deploys.
_PERSISTENT_DISK = Path("/var/data")
DATA_DIR = _PERSISTENT_DISK if _PERSISTENT_DISK.exists() else PROJECT_ROOT / "data"

# -- App version (legacy — session_manager.APP_VERSION is the single source of truth)
APP_VERSION = "7.7.3"

# -- Trading constants --
SYMBOL = "BTC/USDT"  # default / legacy single-asset
SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
TIMEFRAME = "1h"
INITIAL_BALANCE = 100.0
MAX_TRADES_PER_DAY = 3
RISK_PER_TRADE_PERCENT = 2


def load_env() -> None:
    """Load environment variables from the .env file.

    Call this once at app startup before accessing any env vars.
    Silently skips if .env does not exist.
    """
    load_dotenv(dotenv_path=ENV_PATH)


def validate_env(logger=None) -> dict:
    """Check all environment variables and log their status.

    Classifies each variable as:
    - ok:       set and valid
    - fallback: missing but has a safe default, app continues
    - warning:  missing, feature disabled but app runs
    - error:    missing AND required for a core feature

    Args:
        logger: Optional logging.Logger. Falls back to print().

    Returns:
        dict with 'ok' (bool), 'errors' (list), 'warnings' (list).
    """
    def log(level, msg):
        if logger:
            getattr(logger, level)(msg)
        else:
            prefix = {"info": "INFO", "warning": "WARN", "error": "ERROR"}
            print(f"  [{prefix.get(level, '???')}] {msg}")

    errors = []
    warnings = []

    log("info", "--- Environment Check ---")

    # 1. ANTHROPIC_API_KEY — optional for UI, required for trading
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if key:
        log("info", "ANTHROPIC_API_KEY    : set (Claude features enabled)")
    else:
        warnings.append("ANTHROPIC_API_KEY")
        log("warning", "ANTHROPIC_API_KEY    : not set — Claude features disabled, UI still works")

    # 2. CLAUDE_MODEL — optional, has default
    model = os.getenv("CLAUDE_MODEL", "")
    if model:
        log("info", f"CLAUDE_MODEL         : {model}")
    else:
        log("info", "CLAUDE_MODEL         : using default (claude-sonnet-4-20250514)")

    # 3. API_USERNAME — optional, has default
    user = os.getenv("API_USERNAME", "admin")
    log("info", f"API_USERNAME         : {user}")

    # 4. API_PASSWORD — required for security
    pw = os.getenv("API_PASSWORD", "")
    if pw and pw != "changeme":
        log("info", "API_PASSWORD         : set (custom)")
    elif pw == "changeme":
        warnings.append("API_PASSWORD")
        log("warning", "API_PASSWORD         : using default 'changeme' — change in production")
    else:
        log("info", "API_PASSWORD         : using default 'changeme'")

    # 5. JWT_SECRET — optional, auto-generated if missing
    secret = os.getenv("JWT_SECRET", "")
    if secret:
        log("info", "JWT_SECRET           : set")
    else:
        log("info", "JWT_SECRET           : not set — auto-generated (tokens reset on restart)")

    # 6. CORS_ORIGINS — optional, localhost always allowed
    cors = os.getenv("CORS_ORIGINS", "")
    if cors:
        log("info", f"CORS_ORIGINS         : {cors}")
    else:
        log("info", "CORS_ORIGINS         : default (localhost:3000)")

    # 7. Telegram — fully optional
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    tg_chat = os.getenv("TELEGRAM_CHAT_ID", "")
    if tg_token and tg_chat:
        log("info", "TELEGRAM             : configured")
    else:
        log("info", "TELEGRAM             : not configured (alerts disabled)")

    # 8. .env file itself
    if ENV_PATH.exists():
        log("info", f".env file            : found at {ENV_PATH}")
    else:
        warnings.append(".env file")
        log("warning", f".env file            : not found at {ENV_PATH} — using defaults. Run: cp .env.example .env")

    # 9. Data directory
    if DATA_DIR.exists():
        log("info", f"Data directory       : {DATA_DIR}")
    else:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        log("info", f"Data directory       : created {DATA_DIR}")

    # 10. System prompt
    sys_prompt = PROMPTS_DIR / "system_prompt.txt"
    if sys_prompt.exists():
        log("info", "System prompt        : found")
    else:
        errors.append("system_prompt.txt")
        log("error", f"System prompt        : MISSING at {sys_prompt}")

    # Summary
    ok = len(errors) == 0
    if ok and not warnings:
        log("info", "--- All checks passed ---")
    elif ok:
        log("info", f"--- Startup OK with {len(warnings)} warning(s) ---")
    else:
        log("error", f"--- {len(errors)} error(s) found — some features may not work ---")

    return {"ok": ok, "errors": errors, "warnings": warnings}


def get_api_key() -> str:
    """Return the Anthropic API key from the environment.

    Returns:
        The API key string.

    Raises:
        ValueError: If ANTHROPIC_API_KEY is not set.
    """
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        raise ValueError("ANTHROPIC_API_KEY is not set. Add it to your .env file.")
    return key


def get_model() -> str:
    """Return the Claude model name from the environment.

    Returns:
        Model identifier string, defaults to claude-sonnet-4-20250514.
    """
    return os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
