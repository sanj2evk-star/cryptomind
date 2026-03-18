"""
seed_data.py - Generate demo data for a user.

Populates a user's data directory with realistic sample trades,
decisions, equity curve, and portfolio state so the app is
usable immediately before any live trading is configured.

Usage:
    from seed_data import seed_user
    seed_user("admin")
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from config import INITIAL_BALANCE
from user_manager import get_user_file

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

_NOW = datetime.now(timezone.utc)


def _ts(hours_ago: float) -> str:
    """ISO timestamp for N hours ago."""
    return (_NOW - timedelta(hours=hours_ago)).isoformat()


SAMPLE_TRADES = [
    {"timestamp": _ts(72), "action": "BUY",  "price": "68500.00", "quantity": "0.000029", "pnl": "0.0",    "cash_after": "98.01", "strategy": "trend",           "strength": "strong", "market_condition": "trending_up"},
    {"timestamp": _ts(65), "action": "SELL", "price": "69800.00", "quantity": "0.000029", "pnl": "0.0377", "cash_after": "100.05", "strategy": "trend",          "strength": "strong", "market_condition": "trending_up"},
    {"timestamp": _ts(48), "action": "BUY",  "price": "70200.00", "quantity": "0.000028", "pnl": "0.0",    "cash_after": "98.03", "strategy": "both",            "strength": "strong", "market_condition": "trending_up"},
    {"timestamp": _ts(40), "action": "SELL", "price": "69100.00", "quantity": "0.000028", "pnl": "-0.0308","cash_after": "99.96", "strategy": "both",            "strength": "weak",   "market_condition": "sideways"},
    {"timestamp": _ts(30), "action": "BUY",  "price": "69500.00", "quantity": "0.000029", "pnl": "0.0",    "cash_after": "97.98", "strategy": "mean_reversion",  "strength": "strong", "market_condition": "sideways"},
    {"timestamp": _ts(22), "action": "SELL", "price": "71200.00", "quantity": "0.000029", "pnl": "0.0493", "cash_after": "100.04", "strategy": "mean_reversion", "strength": "strong", "market_condition": "trending_up"},
    {"timestamp": _ts(10), "action": "BUY",  "price": "71800.00", "quantity": "0.000028", "pnl": "0.0",    "cash_after": "98.03", "strategy": "trend",           "strength": "weak",   "market_condition": "trending_up"},
    {"timestamp": _ts(5),  "action": "SELL", "price": "72400.00", "quantity": "0.000028", "pnl": "0.0168", "cash_after": "100.07", "strategy": "trend",          "strength": "strong", "market_condition": "trending_up"},
]

SAMPLE_DECISIONS = [
    {"timestamp": _ts(72), "action": "BUY",  "confidence": "0.82", "reasoning": "Both bots agree on BUY. Risk Manager: APPROVED.", "signals": "EMA_crossover_up|RSI_oversold", "risk": '{"stop_loss": 67000, "take_profit": 71000}'},
    {"timestamp": _ts(65), "action": "SELL", "confidence": "0.78", "reasoning": "Only Trend Bot suggests SELL; Mean Rev is neutral.", "signals": "EMA_crossover_down", "risk": '{"stop_loss": 70500, "take_profit": 68500}'},
    {"timestamp": _ts(48), "action": "BUY",  "confidence": "0.85", "reasoning": "Both bots agree on BUY. Risk Manager: APPROVED.", "signals": "EMA_crossover_up|RSI_oversold", "risk": '{"stop_loss": 69000, "take_profit": 72000}'},
    {"timestamp": _ts(40), "action": "SELL", "confidence": "0.70", "reasoning": "Risk Manager VETOED: signals conflicting.", "signals": "EMA_crossover_down", "risk": "N/A"},
    {"timestamp": _ts(30), "action": "BUY",  "confidence": "0.88", "reasoning": "Only Mean Rev Bot suggests BUY; Trend is neutral.", "signals": "RSI_oversold", "risk": '{"stop_loss": 68500, "take_profit": 71500}'},
    {"timestamp": _ts(22), "action": "SELL", "confidence": "0.80", "reasoning": "Both bots agree on SELL. Risk Manager: APPROVED.", "signals": "EMA_crossover_down|RSI_overbought", "risk": '{"stop_loss": 72000, "take_profit": 70000}'},
    {"timestamp": _ts(10), "action": "BUY",  "confidence": "0.72", "reasoning": "Only Trend Bot suggests BUY; Mean Rev is neutral.", "signals": "EMA_crossover_up", "risk": '{"stop_loss": 71000, "take_profit": 73500}'},
    {"timestamp": _ts(5),  "action": "SELL", "confidence": "0.83", "reasoning": "Both bots agree on SELL. Risk Manager: APPROVED.", "signals": "EMA_crossover_down|RSI_overbought", "risk": '{"stop_loss": 73000, "take_profit": 71500}'},
]


def _build_equity() -> list[dict]:
    """Generate an equity curve from the sample trades."""
    equity = INITIAL_BALANCE
    points = []
    base_price = 68000.0

    for i in range(80, -1, -1):
        ts = _ts(i)
        price = base_price + (80 - i) * 50 + ((-1) ** i) * 30
        # Apply P&L from trades that occurred at this time
        for t in SAMPLE_TRADES:
            if t["action"] == "SELL" and abs(i - _hours_ago(t["timestamp"])) < 1:
                equity += float(t["pnl"])

        points.append({
            "timestamp": ts,
            "price": f"{price:.2f}",
            "cash": f"{equity:.4f}",
            "position_size": "0",
            "unrealized_pnl": "0.0",
            "realized_pnl": f"{equity - INITIAL_BALANCE:.4f}",
            "total_equity": f"{equity:.4f}",
        })

    return points


def _hours_ago(ts: str) -> float:
    """Convert an ISO timestamp to hours ago."""
    try:
        dt = datetime.fromisoformat(ts)
        return (_NOW - dt).total_seconds() / 3600
    except Exception:
        return 0


def _build_portfolio() -> dict:
    """Build the portfolio state after all sample trades."""
    cash = float(SAMPLE_TRADES[-1]["cash_after"])
    realized = sum(float(t["pnl"]) for t in SAMPLE_TRADES if t["action"] == "SELL")

    return {
        "cash": round(cash, 4),
        "positions": {},
        "realized_pnl": round(realized, 4),
        "total_trades": len(SAMPLE_TRADES),
        "trades_today": 2,
        "last_trade_date": _NOW.date().isoformat(),
        "last_trade_time": _ts(5),
        "peak_equity": round(cash, 4),
        "consecutive_losses": 0,
        "circuit_breaker_until": "",
    }


SAMPLE_STRATEGIES = [
    {
        "name": "EMA 8/21 RSI 35/65",
        "parameters": {"ema_fast": 8, "ema_slow": 21, "rsi_buy": 35, "rsi_sell": 65},
        "metrics": {"return_pct": 0.14, "total_pnl": 0.14, "win_rate": 100.0, "max_drawdown": 0.05, "total_trades": 3},
        "fitness": 2.8, "live_score": 0.50, "history": [], "regime_stats": {},
        "updated_at": _ts(2),
    },
    {
        "name": "EMA 9/21 RSI 30/70",
        "parameters": {"ema_fast": 9, "ema_slow": 21, "rsi_buy": 30, "rsi_sell": 70},
        "metrics": {"return_pct": 0.09, "total_pnl": 0.09, "win_rate": 66.7, "max_drawdown": 0.08, "total_trades": 3},
        "fitness": 1.5, "live_score": 0.35, "history": [], "regime_stats": {},
        "updated_at": _ts(2),
    },
]


# ---------------------------------------------------------------------------
# Seed function
# ---------------------------------------------------------------------------

TRADE_FIELDS = ["timestamp", "action", "price", "quantity", "pnl", "cash_after", "strategy", "strength", "market_condition"]
DECISION_FIELDS = ["timestamp", "action", "confidence", "reasoning", "signals", "risk"]
EQUITY_FIELDS = ["timestamp", "price", "cash", "position_size", "unrealized_pnl", "realized_pnl", "total_equity"]


def is_seeded(user_id: str) -> bool:
    """Check if a user already has trade data (skip seeding if so)."""
    path = get_user_file(user_id, "trades.csv")
    if not path.exists():
        return False
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        return any(True for _ in reader)


def seed_user(user_id: str) -> dict:
    """Populate a user's data directory with sample data.

    Only seeds if the user has no existing trades (won't overwrite real data).

    Args:
        user_id: Username to seed.

    Returns:
        dict with counts of seeded items.
    """
    if is_seeded(user_id):
        return {"seeded": False, "reason": "User already has trade data."}

    # Trades
    _write_csv(get_user_file(user_id, "trades.csv"), TRADE_FIELDS, SAMPLE_TRADES)

    # Decisions
    _write_csv(get_user_file(user_id, "decisions.csv"), DECISION_FIELDS, SAMPLE_DECISIONS)

    # Equity
    equity_data = _build_equity()
    _write_csv(get_user_file(user_id, "equity.csv"), EQUITY_FIELDS, equity_data)

    # Portfolio
    portfolio = _build_portfolio()
    path = get_user_file(user_id, "portfolio.json")
    path.write_text(json.dumps(portfolio, indent=2) + "\n", encoding="utf-8")

    # Strategies
    path = get_user_file(user_id, "strategies.json")
    path.write_text(json.dumps(SAMPLE_STRATEGIES, indent=2) + "\n", encoding="utf-8")

    return {
        "seeded": True,
        "trades": len(SAMPLE_TRADES),
        "decisions": len(SAMPLE_DECISIONS),
        "equity_points": len(equity_data),
        "strategies": len(SAMPLE_STRATEGIES),
    }


def _write_csv(path: Path, fields: list, rows: list[dict]) -> None:
    """Write rows to a CSV file with headers."""
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
