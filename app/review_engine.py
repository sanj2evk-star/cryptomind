"""
review_engine.py - Post-trade review via Claude.

After every completed trade (SELL), sends the trade details
and market context to Claude for analysis. Returns a structured
review with verdict, strengths, mistakes, and improvements.
"""

import json
import re

import anthropic

from config import get_api_key, get_model

REVIEW_SYSTEM_PROMPT = (
    "You are a trading review analyst. You review completed BTC/USDT paper trades "
    "and evaluate whether the trade followed the strategy rules.\n\n"
    "Strategy rules:\n"
    "- EMA crossover and RSI signals must align (at least 2 signals).\n"
    "- Max 2% risk per trade.\n"
    "- Default to HOLD if uncertain.\n\n"
    "Return ONLY valid JSON with keys: verdict, strengths, mistakes, improvement.\n"
    "Do not include markdown. Do not include explanation outside JSON."
)

REQUIRED_FIELDS = {"verdict", "strengths", "mistakes", "improvement"}

DEFAULT_REVIEW = {
    "verdict": "unknown",
    "strengths": [],
    "mistakes": [],
    "improvement": "Review could not be completed.",
}


def compute_trade_metrics(entry_price: float, exit_price: float, duration_hours: float) -> dict:
    """Compute basic trade performance metrics.

    Args:
        entry_price: Price at BUY.
        exit_price: Price at SELL.
        duration_hours: Hours between entry and exit.

    Returns:
        dict with pnl_percent and duration_hours.
    """
    pnl_percent = ((exit_price - entry_price) / entry_price) * 100

    return {
        "pnl_percent": round(pnl_percent, 4),
        "duration_hours": round(duration_hours, 2),
    }


def _build_review_prompt(
    entry_price: float,
    exit_price: float,
    metrics: dict,
    entry_indicators: dict,
    action_history: list[str],
) -> str:
    """Build the user prompt for Claude's trade review.

    Args:
        entry_price: Price at BUY.
        exit_price: Price at SELL.
        metrics: Output from compute_trade_metrics().
        entry_indicators: Indicator values at time of entry (ema_fast, ema_slow, rsi, trend).
        action_history: List of recent actions leading up to this trade.

    Returns:
        Formatted user prompt string.
    """
    return (
        "Trade Summary:\n"
        f"  Entry Price:  ${entry_price:,.2f}\n"
        f"  Exit Price:   ${exit_price:,.2f}\n"
        f"  P&L:          {metrics['pnl_percent']:+.4f}%\n"
        f"  Duration:     {metrics['duration_hours']:.2f} hours\n"
        "\n"
        "Indicators at Entry:\n"
        f"  EMA(9):  {entry_indicators.get('ema_fast', 'N/A')}\n"
        f"  EMA(21): {entry_indicators.get('ema_slow', 'N/A')}\n"
        f"  RSI(14): {entry_indicators.get('rsi', 'N/A')}\n"
        f"  Trend:   {entry_indicators.get('trend', 'N/A')}\n"
        "\n"
        f"Action History: {', '.join(action_history)}\n"
        "\n"
        "Questions:\n"
        "1. Was this trade valid per the strategy rules?\n"
        "2. What signals were strongest?\n"
        "3. What mistake (if any) occurred?\n"
        "4. Should this type of trade be repeated?\n"
        "\n"
        "Return only valid JSON with keys: verdict, strengths, mistakes, improvement."
    )


def _extract_json(text: str) -> dict:
    """Extract a JSON object from Claude's response text.

    Args:
        text: Raw response string.

    Returns:
        Parsed dict.

    Raises:
        ValueError: If no valid JSON found.
    """
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group(0))

    raise ValueError("No JSON object found in review response")


def review_trade(
    entry_price: float,
    exit_price: float,
    duration_hours: float,
    entry_indicators: dict,
    action_history: list[str],
) -> dict:
    """Send a completed trade to Claude for review.

    Args:
        entry_price: Price at BUY.
        exit_price: Price at SELL.
        duration_hours: Hours between entry and exit.
        entry_indicators: dict with ema_fast, ema_slow, rsi, trend at entry.
        action_history: List of recent action strings (e.g. ["HOLD", "BUY", "HOLD", "SELL"]).

    Returns:
        dict with keys: verdict, strengths, mistakes, improvement.
        Returns DEFAULT_REVIEW on any failure.
    """
    metrics = compute_trade_metrics(entry_price, exit_price, duration_hours)
    user_prompt = _build_review_prompt(
        entry_price, exit_price, metrics, entry_indicators, action_history,
    )

    try:
        client = anthropic.Anthropic(api_key=get_api_key())
        response = client.messages.create(
            model=get_model(),
            max_tokens=512,
            system=REVIEW_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw_text = response.content[0].text
        data = _extract_json(raw_text)

        missing = REQUIRED_FIELDS - data.keys()
        if missing:
            raise ValueError(f"Missing fields: {missing}")

        return data

    except Exception as e:
        print(f"[review_engine] Review failed: {e}")
        return DEFAULT_REVIEW.copy()
