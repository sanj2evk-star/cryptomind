"""
strategy_advisor.py - Claude-powered strategy analysis.

Feeds backtest results to Claude and asks for structured insights:
- Which strategy is most robust?
- Which one is likely overfitting?
- Which should be deployed live?

Returns validated JSON with actionable recommendations.

Usage:
    from strategy_advisor import analyze_strategies
    insights = analyze_strategies(results)
"""

from __future__ import annotations

import json
import re

import anthropic

from config import get_api_key, get_model

ADVISOR_SYSTEM = (
    "You are a quantitative trading strategy advisor.\n"
    "You analyze backtest results and identify robust strategies vs overfitting.\n\n"
    "Signs of robustness:\n"
    "- Consistent win rate across many trades\n"
    "- Low drawdown relative to returns\n"
    "- Moderate trade frequency (not too few, not too many)\n"
    "- Parameters not at extreme values\n\n"
    "Signs of overfitting:\n"
    "- Very high win rate with very few trades\n"
    "- Extreme parameter values (very tight or very wide thresholds)\n"
    "- High returns with high drawdown\n"
    "- Performance that seems too good for the strategy complexity\n\n"
    "Return ONLY valid JSON. No markdown. No extra text.\n"
    "Keys: most_robust, likely_overfitting, deploy_live, reasoning"
)

REQUIRED_FIELDS = {"most_robust", "likely_overfitting", "deploy_live", "reasoning"}

DEFAULT_INSIGHTS = {
    "most_robust": None,
    "likely_overfitting": [],
    "deploy_live": None,
    "reasoning": "Analysis could not be completed.",
}


def _format_results(results: list[dict]) -> str:
    """Format backtest results into a compact text table for Claude.

    Args:
        results: List of dicts with 'config' and 'metrics' keys.

    Returns:
        Formatted string.
    """
    lines = ["Strategy Results:"]
    lines.append(f"{'#':>2}  {'Strategy':<28} {'Return':>8} {'PnL':>10} "
                 f"{'WinRate':>8} {'Trades':>7} {'MaxDD':>10}")
    lines.append("-" * 80)

    for i, r in enumerate(results, 1):
        c = r["config"]
        m = r["metrics"]
        lines.append(
            f"{i:>2}  {c['name']:<28} {m['return_pct']:>+7.4f}% "
            f"${m['total_pnl']:>9.4f} {m['win_rate']:>7.1f}% "
            f"{m['total_trades']:>7} ${m['max_drawdown']:>9.4f}"
        )

    return "\n".join(lines)


def _format_params(results: list[dict]) -> str:
    """Format the parameter ranges across all strategies.

    Args:
        results: List of result dicts.

    Returns:
        Formatted string summarizing parameter ranges.
    """
    configs = [r["config"] for r in results]
    if not configs:
        return "No parameters to analyze."

    ema_fasts = [c["ema_fast"] for c in configs]
    ema_slows = [c["ema_slow"] for c in configs]
    rsi_buys = [c["rsi_buy"] for c in configs]
    rsi_sells = [c["rsi_sell"] for c in configs]

    return (
        "Parameter Ranges:\n"
        f"  EMA Fast:  {min(ema_fasts)} to {max(ema_fasts)}\n"
        f"  EMA Slow:  {min(ema_slows)} to {max(ema_slows)}\n"
        f"  RSI Buy:   {min(rsi_buys)} to {max(rsi_buys)}\n"
        f"  RSI Sell:  {min(rsi_sells)} to {max(rsi_sells)}"
    )


def build_advisor_prompt(results: list[dict]) -> dict:
    """Build the prompt payload for Claude strategy analysis.

    Args:
        results: Backtest results from strategy_runner or optimizer.

    Returns:
        Prompt payload dict for Claude API.
    """
    table = _format_results(results)
    params = _format_params(results)

    user = (
        f"{table}\n\n"
        f"{params}\n\n"
        "Analyze these backtest results and answer:\n"
        "1. Which strategy is most robust and why?\n"
        "2. Which strategies are likely overfitting and why?\n"
        "3. Which single strategy should be deployed live?\n\n"
        "Return only valid JSON with keys:\n"
        "  most_robust: {name, reason}\n"
        "  likely_overfitting: [{name, reason}, ...]\n"
        "  deploy_live: {name, reason}\n"
        "  reasoning: overall analysis summary"
    )

    return {
        "system": ADVISOR_SYSTEM,
        "messages": [{"role": "user", "content": user}],
    }


def analyze_strategies(results: list[dict]) -> dict:
    """Send backtest results to Claude for strategy analysis.

    Args:
        results: List of dicts with 'config' and 'metrics' keys,
            as returned by strategy_runner.run_all() or optimizer.evolve().

    Returns:
        dict with keys: most_robust, likely_overfitting, deploy_live, reasoning.
        Returns DEFAULT_INSIGHTS on any failure.
    """
    if not results:
        return DEFAULT_INSIGHTS.copy()

    payload = build_advisor_prompt(results)

    try:
        client = anthropic.Anthropic(api_key=get_api_key())
        response = client.messages.create(
            model=get_model(),
            max_tokens=1024,
            system=payload["system"],
            messages=payload["messages"],
        )
        raw = response.content[0].text

        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError("No JSON found in response")

        data = json.loads(match.group(0))

        missing = REQUIRED_FIELDS - data.keys()
        if missing:
            raise ValueError(f"Missing fields: {missing}")

        return data

    except Exception as e:
        print(f"[strategy_advisor] Analysis failed: {e}")
        return DEFAULT_INSIGHTS.copy()


def print_insights(insights: dict) -> None:
    """Print formatted strategy insights.

    Args:
        insights: Output from analyze_strategies().
    """
    print("\n" + "=" * 60)
    print("  Claude Strategy Analysis")
    print("=" * 60)

    robust = insights.get("most_robust")
    if isinstance(robust, dict):
        print(f"  Most Robust:    {robust.get('name', 'N/A')}")
        print(f"    Reason:       {robust.get('reason', 'N/A')}")
    else:
        print(f"  Most Robust:    {robust or 'N/A'}")

    print("-" * 60)

    overfit = insights.get("likely_overfitting", [])
    if isinstance(overfit, list) and overfit:
        print(f"  Overfitting ({len(overfit)}):")
        for item in overfit:
            if isinstance(item, dict):
                print(f"    - {item.get('name', '?')}: {item.get('reason', '?')}")
            else:
                print(f"    - {item}")
    else:
        print("  Overfitting:    None detected")

    print("-" * 60)

    deploy = insights.get("deploy_live")
    if isinstance(deploy, dict):
        print(f"  Deploy Live:    {deploy.get('name', 'N/A')}")
        print(f"    Reason:       {deploy.get('reason', 'N/A')}")
    else:
        print(f"  Deploy Live:    {deploy or 'N/A'}")

    print("-" * 60)
    print(f"  Summary:        {insights.get('reasoning', 'N/A')}")
    print("=" * 60)
    print()
