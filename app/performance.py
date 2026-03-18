"""
performance.py - End-of-day performance analysis.

Computes daily trading metrics from trades.csv and sends
a summary to Claude for strategic insights.
"""

import csv
import json
import re
from datetime import date

import anthropic

from config import DATA_DIR, get_api_key, get_model

TRADES_FILE = DATA_DIR / "trades.csv"

ANALYSIS_SYSTEM = (
    "You are a trading performance analyst for a BTC/USDT paper trading system.\n"
    "You review end-of-day metrics and provide actionable insights.\n\n"
    "Return ONLY valid JSON. No markdown. No extra text.\n"
    "Keys: what_worked (list), what_failed (list), "
    "should_change_strategy (bool), suggestions (list)"
)

DEFAULT_INSIGHTS = {
    "what_worked": [],
    "what_failed": [],
    "should_change_strategy": False,
    "suggestions": ["Analysis could not be completed."],
}


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _load_todays_trades() -> list[dict]:
    """Read trades from CSV and filter to today's date.

    Returns:
        List of trade dicts from today, chronological order.
    """
    if not TRADES_FILE.exists():
        return []

    today = date.today().isoformat()

    with open(TRADES_FILE, newline="") as f:
        rows = list(csv.DictReader(f))

    return [r for r in rows if r.get("timestamp", "").startswith(today)]


def compute_metrics(trades: list[dict]) -> dict:
    """Compute daily performance metrics from a list of trade dicts.

    Args:
        trades: List of trade dicts with 'action', 'pnl', 'cash_after'.

    Returns:
        dict with total_trades, wins, losses, win_rate, total_pnl,
        max_drawdown.
    """
    executed = [t for t in trades if t.get("action") in ("BUY", "SELL")]
    pnl_values = [float(t.get("pnl", 0.0)) for t in executed]

    total = len(executed)
    wins = sum(1 for p in pnl_values if p > 0)
    losses = sum(1 for p in pnl_values if p < 0)
    total_pnl = sum(pnl_values)
    win_rate = (wins / total * 100) if total > 0 else 0.0

    # Max drawdown: largest peak-to-trough decline in cumulative P&L
    max_drawdown = 0.0
    peak = 0.0
    cumulative = 0.0
    for p in pnl_values:
        cumulative += p
        if cumulative > peak:
            peak = cumulative
        drawdown = peak - cumulative
        if drawdown > max_drawdown:
            max_drawdown = drawdown

    return {
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 2),
        "total_pnl": round(total_pnl, 4),
        "max_drawdown": round(max_drawdown, 4),
    }


# ---------------------------------------------------------------------------
# Claude analysis
# ---------------------------------------------------------------------------

def _build_analysis_prompt(metrics: dict) -> dict:
    """Build the prompt payload for Claude performance analysis.

    Args:
        metrics: Output from compute_metrics().

    Returns:
        Prompt payload dict for Claude API.
    """
    user = (
        "End-of-Day Performance:\n"
        f"  Total Trades:  {metrics['total_trades']}\n"
        f"  Wins:          {metrics['wins']}\n"
        f"  Losses:        {metrics['losses']}\n"
        f"  Win Rate:      {metrics['win_rate']}%\n"
        f"  Total P&L:     ${metrics['total_pnl']:,.4f}\n"
        f"  Max Drawdown:  ${metrics['max_drawdown']:,.4f}\n"
        "\n"
        "Questions:\n"
        "1. What worked today?\n"
        "2. What failed?\n"
        "3. Should the strategy change?\n"
        "\n"
        "Return only valid JSON with keys: "
        "what_worked, what_failed, should_change_strategy, suggestions."
    )

    return {
        "system": ANALYSIS_SYSTEM,
        "messages": [{"role": "user", "content": user}],
    }


def _call_claude(payload: dict) -> str:
    """Send prompt to Claude and return raw text.

    Args:
        payload: Prompt payload dict.

    Returns:
        Raw response text.
    """
    client = anthropic.Anthropic(api_key=get_api_key())
    response = client.messages.create(
        model=get_model(),
        max_tokens=512,
        system=payload["system"],
        messages=payload["messages"],
    )
    return response.content[0].text


def get_daily_insights(metrics: dict) -> dict:
    """Send daily metrics to Claude and return structured insights.

    Args:
        metrics: Output from compute_metrics().

    Returns:
        dict with what_worked, what_failed, should_change_strategy, suggestions.
        Returns DEFAULT_INSIGHTS on any failure.
    """
    try:
        payload = _build_analysis_prompt(metrics)
        raw = _call_claude(payload)

        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError("No JSON found in response")

        data = json.loads(match.group(0))

        required = {"what_worked", "what_failed", "should_change_strategy", "suggestions"}
        missing = required - data.keys()
        if missing:
            raise ValueError(f"Missing fields: {missing}")

        return data

    except Exception as e:
        print(f"[performance] Insights failed: {e}")
        return DEFAULT_INSIGHTS.copy()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def daily_report() -> dict:
    """Run the full end-of-day performance report.

    Loads today's trades, computes metrics, sends to Claude for
    analysis, and returns a combined report.

    Returns:
        dict with 'metrics' and 'insights' keys.
    """
    trades = _load_todays_trades()
    metrics = compute_metrics(trades)

    if metrics["total_trades"] == 0:
        return {
            "metrics": metrics,
            "insights": {
                "what_worked": [],
                "what_failed": [],
                "should_change_strategy": False,
                "suggestions": ["No trades today. Nothing to analyze."],
            },
        }

    insights = get_daily_insights(metrics)

    return {
        "metrics": metrics,
        "insights": insights,
    }


def print_report(report: dict) -> None:
    """Print a formatted daily performance report.

    Args:
        report: Output from daily_report().
    """
    m = report["metrics"]
    i = report["insights"]

    print("\n" + "=" * 55)
    print("  End-of-Day Performance Report")
    print("=" * 55)
    print(f"  Total Trades:  {m['total_trades']}")
    print(f"  Win Rate:      {m['win_rate']}%")
    print(f"  Total P&L:     ${m['total_pnl']:,.4f}")
    print(f"  Max Drawdown:  ${m['max_drawdown']:,.4f}")
    print("-" * 55)
    print(f"  What Worked:   {', '.join(i.get('what_worked', [])) or 'N/A'}")
    print(f"  What Failed:   {', '.join(i.get('what_failed', [])) or 'N/A'}")
    print(f"  Change Strat:  {'Yes' if i.get('should_change_strategy') else 'No'}")
    print(f"  Suggestions:   {'; '.join(i.get('suggestions', []))}")
    print("=" * 55)
    print()
