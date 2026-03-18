"""
research_report.py - Weekly research report generator.

Collects trading data from the past 7 days, computes metrics,
identifies best strategies and worst trades, summarizes market
behavior, and sends everything to Claude for a written report.

Usage:
    python app/research_report.py
    # or
    from research_report import generate_report
    report = generate_report()
"""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone, timedelta

import anthropic

from config import DATA_DIR, get_api_key, get_model

TRADES_FILE = DATA_DIR / "trades.csv"
EQUITY_FILE = DATA_DIR / "equity.csv"
REPORT_DIR = DATA_DIR / "reports"

REPORT_SYSTEM = (
    "You are a quantitative research analyst writing a weekly trading report "
    "for a BTC/USDT paper trading system.\n\n"
    "Write a clear, professional report in plain text (no markdown). "
    "Use sections with headers. Be concise but thorough. "
    "Focus on actionable insights, not just restating numbers.\n\n"
    "Sections:\n"
    "1. Executive Summary (2-3 sentences)\n"
    "2. Performance Overview\n"
    "3. Best Strategies\n"
    "4. Worst Trades & Lessons\n"
    "5. Market Behavior\n"
    "6. Recommendations"
)


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

def _load_csv(path) -> list[dict]:
    """Load a CSV file as a list of dicts."""
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _filter_last_n_days(rows: list[dict], days: int = 7) -> list[dict]:
    """Filter rows to the last N days by timestamp field.

    Args:
        rows: List of dicts with 'timestamp' key.
        days: Number of days to look back.

    Returns:
        Filtered list.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return [r for r in rows if r.get("timestamp", "") >= cutoff]


def collect_weekly_data(days: int = 7) -> dict:
    """Collect all trading data from the past week.

    Args:
        days: Number of days to cover.

    Returns:
        dict with trades, equity snapshots, and computed metrics.
    """
    all_trades = _load_csv(TRADES_FILE)
    all_equity = _load_csv(EQUITY_FILE)

    trades = _filter_last_n_days(all_trades, days)
    equity = _filter_last_n_days(all_equity, days)

    return {
        "period_days": days,
        "trades": trades,
        "equity": equity,
        "metrics": _compute_metrics(trades),
        "worst_trades": _find_worst_trades(trades, n=3),
        "best_trades": _find_best_trades(trades, n=3),
        "strategy_breakdown": _strategy_breakdown(trades),
        "regime_breakdown": _regime_breakdown(trades),
    }


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _safe_float(val, default: float = 0.0) -> float:
    """Safely convert to float."""
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _compute_metrics(trades: list[dict]) -> dict:
    """Compute weekly performance metrics.

    Args:
        trades: List of trade dicts.

    Returns:
        Metrics dict.
    """
    executed = [t for t in trades if t.get("action") in ("BUY", "SELL")]
    pnl_values = [_safe_float(t.get("pnl")) for t in executed]

    total = len(executed)
    wins = sum(1 for p in pnl_values if p > 0)
    losses = sum(1 for p in pnl_values if p < 0)
    total_pnl = sum(pnl_values)
    win_rate = (wins / total * 100) if total > 0 else 0.0

    # Max drawdown
    peak = 0.0
    cumulative = 0.0
    max_dd = 0.0
    for p in pnl_values:
        cumulative += p
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    return {
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 1),
        "total_pnl": round(total_pnl, 4),
        "max_drawdown": round(max_dd, 4),
    }


def _find_worst_trades(trades: list[dict], n: int = 3) -> list[dict]:
    """Find the N worst trades by P&L.

    Args:
        trades: List of trade dicts.
        n: Number of worst to return.

    Returns:
        List of trade dicts, worst first.
    """
    sells = [t for t in trades if t.get("action") == "SELL"]
    sells.sort(key=lambda t: _safe_float(t.get("pnl")))
    return sells[:n]


def _find_best_trades(trades: list[dict], n: int = 3) -> list[dict]:
    """Find the N best trades by P&L.

    Args:
        trades: List of trade dicts.
        n: Number of best to return.

    Returns:
        List of trade dicts, best first.
    """
    sells = [t for t in trades if t.get("action") == "SELL"]
    sells.sort(key=lambda t: _safe_float(t.get("pnl")), reverse=True)
    return sells[:n]


def _strategy_breakdown(trades: list[dict]) -> dict:
    """Break down performance by strategy tag.

    Args:
        trades: List of trade dicts.

    Returns:
        Dict mapping strategy name → {trades, wins, pnl}.
    """
    breakdown = {}
    for t in trades:
        strat = t.get("strategy", "unknown")
        if strat not in breakdown:
            breakdown[strat] = {"trades": 0, "wins": 0, "total_pnl": 0.0}
        breakdown[strat]["trades"] += 1
        pnl = _safe_float(t.get("pnl"))
        breakdown[strat]["total_pnl"] = round(breakdown[strat]["total_pnl"] + pnl, 4)
        if pnl > 0:
            breakdown[strat]["wins"] += 1
    return breakdown


def _regime_breakdown(trades: list[dict]) -> dict:
    """Break down performance by market condition.

    Args:
        trades: List of trade dicts.

    Returns:
        Dict mapping regime → {trades, wins, pnl}.
    """
    breakdown = {}
    for t in trades:
        regime = t.get("market_condition", "unknown")
        if regime not in breakdown:
            breakdown[regime] = {"trades": 0, "wins": 0, "total_pnl": 0.0}
        breakdown[regime]["trades"] += 1
        pnl = _safe_float(t.get("pnl"))
        breakdown[regime]["total_pnl"] = round(breakdown[regime]["total_pnl"] + pnl, 4)
        if pnl > 0:
            breakdown[regime]["wins"] += 1
    return breakdown


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def format_report_prompt(data: dict) -> str:
    """Format collected data into a prompt for Claude.

    Args:
        data: Output from collect_weekly_data().

    Returns:
        Formatted user prompt string.
    """
    m = data["metrics"]

    lines = [
        f"Weekly Trading Report Data ({data['period_days']} days)",
        "",
        "PERFORMANCE:",
        f"  Total trades: {m['total_trades']}",
        f"  Wins: {m['wins']}  Losses: {m['losses']}",
        f"  Win rate: {m['win_rate']}%",
        f"  Total P&L: ${m['total_pnl']}",
        f"  Max drawdown: ${m['max_drawdown']}",
    ]

    # Strategy breakdown
    lines.append("\nSTRATEGY BREAKDOWN:")
    for strat, stats in data["strategy_breakdown"].items():
        lines.append(f"  {strat}: {stats['trades']} trades, "
                     f"{stats['wins']} wins, PnL ${stats['total_pnl']}")

    # Regime breakdown
    lines.append("\nMARKET REGIME BREAKDOWN:")
    for regime, stats in data["regime_breakdown"].items():
        lines.append(f"  {regime}: {stats['trades']} trades, "
                     f"{stats['wins']} wins, PnL ${stats['total_pnl']}")

    # Worst trades
    lines.append("\nWORST TRADES:")
    for t in data["worst_trades"]:
        lines.append(f"  {t.get('timestamp', '?')[:16]}  "
                     f"PnL ${_safe_float(t.get('pnl')):.4f}  "
                     f"price ${_safe_float(t.get('price')):.2f}  "
                     f"regime={t.get('market_condition', '?')}  "
                     f"strategy={t.get('strategy', '?')}")
    if not data["worst_trades"]:
        lines.append("  (none)")

    # Best trades
    lines.append("\nBEST TRADES:")
    for t in data["best_trades"]:
        lines.append(f"  {t.get('timestamp', '?')[:16]}  "
                     f"PnL ${_safe_float(t.get('pnl')):.4f}  "
                     f"price ${_safe_float(t.get('price')):.2f}  "
                     f"regime={t.get('market_condition', '?')}  "
                     f"strategy={t.get('strategy', '?')}")
    if not data["best_trades"]:
        lines.append("  (none)")

    # Equity curve summary
    if data["equity"]:
        eq_start = _safe_float(data["equity"][0].get("total_equity"))
        eq_end = _safe_float(data["equity"][-1].get("total_equity"))
        lines.append(f"\nEQUITY: ${eq_start:.4f} -> ${eq_end:.4f}")
    else:
        lines.append("\nEQUITY: no data")

    lines.append("\nWrite a professional weekly research report based on this data.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Claude report generation
# ---------------------------------------------------------------------------

def generate_report(days: int = 7) -> dict:
    """Generate the full weekly research report.

    Collects data, sends to Claude for analysis, and saves the report.

    Args:
        days: Number of days to cover.

    Returns:
        dict with 'data' (raw metrics), 'report' (Claude's text),
        'saved_path' (file path if saved).
    """
    data = collect_weekly_data(days)

    if data["metrics"]["total_trades"] == 0:
        report_text = (
            "WEEKLY RESEARCH REPORT\n"
            f"Period: Last {days} days\n\n"
            "No trades were executed during this period. "
            "Nothing to analyze."
        )
        return {"data": data, "report": report_text, "saved_path": None}

    prompt = format_report_prompt(data)

    try:
        client = anthropic.Anthropic(api_key=get_api_key())
        response = client.messages.create(
            model=get_model(),
            max_tokens=2048,
            system=REPORT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        report_text = response.content[0].text
    except Exception as e:
        print(f"[research_report] Claude failed: {e}")
        report_text = _fallback_report(data)

    saved_path = _save_report(report_text, days)

    return {"data": data, "report": report_text, "saved_path": saved_path}


def _fallback_report(data: dict) -> str:
    """Generate a basic report without Claude if the API fails.

    Args:
        data: Output from collect_weekly_data().

    Returns:
        Plain text report string.
    """
    m = data["metrics"]

    lines = [
        "WEEKLY RESEARCH REPORT (auto-generated)",
        f"Period: Last {data['period_days']} days",
        "",
        "PERFORMANCE",
        f"  Trades: {m['total_trades']}  Wins: {m['wins']}  Losses: {m['losses']}",
        f"  Win rate: {m['win_rate']}%",
        f"  Total P&L: ${m['total_pnl']}",
        f"  Max drawdown: ${m['max_drawdown']}",
        "",
        "STRATEGY BREAKDOWN",
    ]
    for strat, stats in data["strategy_breakdown"].items():
        lines.append(f"  {strat}: {stats['trades']} trades, PnL ${stats['total_pnl']}")

    lines.append("")
    lines.append("MARKET REGIMES")
    for regime, stats in data["regime_breakdown"].items():
        lines.append(f"  {regime}: {stats['trades']} trades, PnL ${stats['total_pnl']}")

    lines.append("")
    lines.append("NOTE: Claude analysis unavailable. This is a data-only summary.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# File output
# ---------------------------------------------------------------------------

def _save_report(report_text: str, days: int) -> str:
    """Save the report to a timestamped file.

    Args:
        report_text: Full report text.
        days: Period covered.

    Returns:
        Path to the saved file.
    """
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename = f"report_{timestamp}_{days}d.txt"
    path = REPORT_DIR / filename
    path.write_text(report_text, encoding="utf-8")
    return str(path)


def print_report(report: dict) -> None:
    """Print the report to terminal.

    Args:
        report: Output from generate_report().
    """
    print("\n" + "=" * 60)
    print(report["report"])
    print("=" * 60)

    if report["saved_path"]:
        print(f"\nSaved to: {report['saved_path']}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Generate and print the weekly research report."""
    from config import load_env
    load_env()

    report = generate_report(days=7)
    print_report(report)


if __name__ == "__main__":
    main()
