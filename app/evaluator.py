"""
evaluator.py - Weekly system evaluation via Claude.

Collects multi-week performance data, compares current vs previous
weeks, and asks Claude three questions:
1. Is the system improving?
2. Where is it failing?
3. What should be adjusted?

Stores insights to data/evaluations.json for tracking over time.

Usage:
    python app/evaluator.py
    # or
    from evaluator import run_evaluation
    result = run_evaluation()
"""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone, timedelta

import anthropic

from config import DATA_DIR, get_api_key, get_model
from strategy_store import load_strategies

TRADES_FILE = DATA_DIR / "trades.csv"
EQUITY_FILE = DATA_DIR / "equity.csv"
EVALUATIONS_FILE = DATA_DIR / "evaluations.json"

EVAL_SYSTEM = (
    "You are a system evaluator for an automated BTC/USDT paper trading platform.\n"
    "You compare current performance against previous periods and assess whether "
    "the system is improving, stable, or degrading.\n\n"
    "Be specific and actionable. Reference actual numbers.\n\n"
    "Return ONLY valid JSON. No markdown. No extra text.\n"
    "Keys:\n"
    "  improving: bool\n"
    "  score: 1-10 (overall system health)\n"
    "  strengths: [list of what's working]\n"
    "  failures: [list of what's failing]\n"
    "  adjustments: [list of specific changes to make]\n"
    "  summary: one-paragraph assessment"
)


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

def _load_csv(path) -> list[dict]:
    """Load a CSV as a list of dicts."""
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _safe_float(val, default: float = 0.0) -> float:
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _filter_window(rows: list[dict], start_days_ago: int, end_days_ago: int) -> list[dict]:
    """Filter rows to a specific time window.

    Args:
        rows: List of dicts with 'timestamp' key.
        start_days_ago: Beginning of window (e.g. 14 = two weeks ago).
        end_days_ago: End of window (e.g. 7 = one week ago).

    Returns:
        Filtered list.
    """
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=start_days_ago)).isoformat()
    end = (now - timedelta(days=end_days_ago)).isoformat()
    return [r for r in rows if start <= r.get("timestamp", "") <= end]


def _compute_window_metrics(trades: list[dict]) -> dict:
    """Compute metrics for a time window.

    Args:
        trades: Filtered trade list.

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

    peak = cumulative = max_dd = 0.0
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


def collect_evaluation_data() -> dict:
    """Collect current week vs previous week data.

    Returns:
        dict with current_week, previous_week metrics, strategy info,
        and prior evaluation for context.
    """
    all_trades = _load_csv(TRADES_FILE)

    current = _filter_window(all_trades, 7, 0)
    previous = _filter_window(all_trades, 14, 7)

    strategies = load_strategies()
    top_strategies = [
        {"name": s["name"], "live_score": s.get("live_score", 0), "fitness": s.get("fitness", 0)}
        for s in strategies[:5]
    ]

    prior = _load_prior_evaluation()

    return {
        "current_week": _compute_window_metrics(current),
        "previous_week": _compute_window_metrics(previous),
        "top_strategies": top_strategies,
        "prior_evaluation": prior,
    }


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

def _format_eval_prompt(data: dict) -> str:
    """Format evaluation data into a prompt for Claude.

    Args:
        data: Output from collect_evaluation_data().

    Returns:
        Formatted user prompt.
    """
    cw = data["current_week"]
    pw = data["previous_week"]

    lines = [
        "SYSTEM EVALUATION DATA",
        "",
        "CURRENT WEEK:",
        f"  Trades: {cw['total_trades']}  Wins: {cw['wins']}  Losses: {cw['losses']}",
        f"  Win Rate: {cw['win_rate']}%",
        f"  P&L: ${cw['total_pnl']}",
        f"  Max Drawdown: ${cw['max_drawdown']}",
        "",
        "PREVIOUS WEEK:",
        f"  Trades: {pw['total_trades']}  Wins: {pw['wins']}  Losses: {pw['losses']}",
        f"  Win Rate: {pw['win_rate']}%",
        f"  P&L: ${pw['total_pnl']}",
        f"  Max Drawdown: ${pw['max_drawdown']}",
    ]

    # Deltas
    if pw["total_trades"] > 0:
        pnl_delta = cw["total_pnl"] - pw["total_pnl"]
        wr_delta = cw["win_rate"] - pw["win_rate"]
        lines.append("")
        lines.append("WEEK-OVER-WEEK CHANGE:")
        lines.append(f"  P&L: {'+' if pnl_delta >= 0 else ''}${pnl_delta:.4f}")
        lines.append(f"  Win Rate: {'+' if wr_delta >= 0 else ''}{wr_delta:.1f}%")

    # Strategies
    if data["top_strategies"]:
        lines.append("")
        lines.append("TOP STRATEGIES:")
        for s in data["top_strategies"]:
            lines.append(f"  {s['name']}  live_score={s['live_score']}  fitness={s['fitness']}")

    # Prior evaluation context
    prior = data.get("prior_evaluation")
    if prior and prior.get("summary"):
        lines.append("")
        lines.append("PRIOR EVALUATION SUMMARY:")
        lines.append(f"  Score: {prior.get('score', '?')}/10")
        lines.append(f"  {prior['summary'][:200]}")

    lines.append("")
    lines.append("Answer:")
    lines.append("1. Is the system improving compared to last week?")
    lines.append("2. Where is it failing?")
    lines.append("3. What specific adjustments should be made?")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Claude evaluation
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = {"improving", "score", "strengths", "failures", "adjustments", "summary"}

DEFAULT_EVAL = {
    "improving": False,
    "score": 0,
    "strengths": [],
    "failures": [],
    "adjustments": [],
    "summary": "Evaluation could not be completed.",
}


def ask_claude(data: dict) -> dict:
    """Send evaluation data to Claude and return structured insights.

    Args:
        data: Output from collect_evaluation_data().

    Returns:
        Evaluation dict with improving, score, strengths, failures,
        adjustments, summary. Returns DEFAULT_EVAL on failure.
    """
    prompt = _format_eval_prompt(data)

    try:
        client = anthropic.Anthropic(api_key=get_api_key())
        response = client.messages.create(
            model=get_model(),
            max_tokens=1024,
            system=EVAL_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text

        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError("No JSON found in response")

        result = json.loads(match.group(0))

        missing = REQUIRED_FIELDS - result.keys()
        if missing:
            raise ValueError(f"Missing fields: {missing}")

        return result

    except Exception as e:
        print(f"[evaluator] Claude failed: {e}")
        return DEFAULT_EVAL.copy()


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _load_evaluations() -> list[dict]:
    """Load all past evaluations."""
    try:
        return json.loads(EVALUATIONS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_evaluations(evals: list[dict]) -> None:
    """Save evaluations list to disk."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    EVALUATIONS_FILE.write_text(
        json.dumps(evals, indent=2) + "\n",
        encoding="utf-8",
    )


def store_evaluation(evaluation: dict, data: dict) -> None:
    """Store an evaluation result with timestamp and context.

    Args:
        evaluation: Claude's evaluation dict.
        data: The raw data that was evaluated.
    """
    evals = _load_evaluations()

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "evaluation": evaluation,
        "current_week": data["current_week"],
        "previous_week": data["previous_week"],
    }

    evals.append(entry)

    # Keep last 52 evaluations (1 year of weekly)
    if len(evals) > 52:
        evals = evals[-52:]

    _save_evaluations(evals)


def _load_prior_evaluation() -> dict | None:
    """Load the most recent evaluation for context.

    Returns:
        The evaluation dict, or None.
    """
    evals = _load_evaluations()
    if not evals:
        return None
    return evals[-1].get("evaluation")


def get_evaluation_history() -> list[dict]:
    """Load all stored evaluations.

    Returns:
        List of evaluation entries, most recent last.
    """
    return _load_evaluations()


def get_trend(n: int = 4) -> dict:
    """Compute the evaluation trend over the last N weeks.

    Args:
        n: Number of recent evaluations to consider.

    Returns:
        dict with avg_score, improving_count, scores list.
    """
    evals = _load_evaluations()[-n:]

    if not evals:
        return {"avg_score": 0, "improving_count": 0, "scores": []}

    scores = [e.get("evaluation", {}).get("score", 0) for e in evals]
    improving = sum(1 for e in evals if e.get("evaluation", {}).get("improving", False))

    return {
        "avg_score": round(sum(scores) / len(scores), 1),
        "improving_count": improving,
        "scores": scores,
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_evaluation(evaluation: dict) -> None:
    """Print a formatted evaluation."""
    print("\n" + "=" * 60)
    print("  Weekly System Evaluation")
    print("=" * 60)

    status = "IMPROVING" if evaluation.get("improving") else "NOT IMPROVING"
    print(f"  Status:       {status}")
    print(f"  Score:        {evaluation.get('score', '?')}/10")
    print("-" * 60)

    print("  Strengths:")
    for s in evaluation.get("strengths", []):
        print(f"    + {s}")

    print("  Failures:")
    for f in evaluation.get("failures", []):
        print(f"    - {f}")

    print("  Adjustments:")
    for a in evaluation.get("adjustments", []):
        print(f"    > {a}")

    print("-" * 60)
    print(f"  Summary: {evaluation.get('summary', 'N/A')}")
    print("=" * 60)
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_evaluation() -> dict:
    """Run the full weekly evaluation pipeline.

    Collects data, asks Claude, stores result.

    Returns:
        dict with 'data', 'evaluation', 'trend'.
    """
    data = collect_evaluation_data()
    evaluation = ask_claude(data)
    store_evaluation(evaluation, data)
    trend = get_trend()

    return {
        "data": data,
        "evaluation": evaluation,
        "trend": trend,
    }


def main() -> None:
    """Run and print the weekly evaluation."""
    from config import load_env
    load_env()

    result = run_evaluation()
    print_evaluation(result["evaluation"])

    trend = result["trend"]
    print(f"  Trend (last {len(trend['scores'])} weeks): "
          f"avg score={trend['avg_score']}/10, "
          f"improving {trend['improving_count']}/{len(trend['scores'])} weeks")
    print(f"  Scores: {trend['scores']}")
    print()


if __name__ == "__main__":
    main()
