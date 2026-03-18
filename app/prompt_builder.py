"""
prompt_builder.py - Claude prompt construction.

Builds prompts for three strategy agents:
1. Trend Bot     - EMA crossover, trades momentum
2. Mean Reversion Bot - RSI-based, buys dips / sells highs
3. Risk Manager  - validates or vetoes proposed trades

Also builds review prompts for post-trade analysis.
"""

import json
import pandas as pd

from config import PROMPTS_DIR

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

JSON_INSTRUCTION = (
    "Return ONLY valid JSON. Do not include markdown. "
    "Do not include explanation outside JSON."
)

DECISION_KEYS = "action, confidence, reasoning, signals, risk"


def _format_market_snapshot(df: pd.DataFrame, current_price: float) -> str:
    """Format market data and indicators into a text block.

    Args:
        df: OHLCV DataFrame with indicator columns.
        current_price: Latest price.

    Returns:
        Formatted string.
    """
    last = df.iloc[-1]

    return (
        "Market Snapshot:\n"
        f"  Price:    ${current_price:,.2f}\n"
        f"  EMA(9):   ${last['ema_fast']:,.2f}\n"
        f"  EMA(21):  ${last['ema_slow']:,.2f}\n"
        f"  RSI(14):  {last['rsi']:.1f}\n"
        f"  Trend:    {df.attrs.get('trend', 'unknown')}"
    )


def _format_portfolio(portfolio: dict) -> str:
    """Format portfolio state into a text block.

    Args:
        portfolio: Portfolio dict from paper_broker.

    Returns:
        Formatted string.
    """
    return (
        "Portfolio State:\n"
        f"  Cash (USDT):  ${portfolio.get('cash', 0.0):,.2f}\n"
        f"  BTC Position: {portfolio.get('position_size', 0.0):.6f}\n"
        f"  Entry Price:  ${portfolio.get('entry_price', 0.0):,.2f}\n"
        f"  Realized P&L: ${portfolio.get('realized_pnl', 0.0):,.2f}"
    )


# ---------------------------------------------------------------------------
# Strategy system prompts
# ---------------------------------------------------------------------------

TREND_SYSTEM = (
    "You are a Trend Bot for BTC/USDT paper trading.\n"
    "Strategy: EMA crossover momentum trading.\n"
    "- BUY when EMA(9) crosses above EMA(21) with confirming trend.\n"
    "- SELL when EMA(9) crosses below EMA(21) or momentum fades.\n"
    "- HOLD if no clear crossover signal.\n"
    "- Always define stop_loss and take_profit.\n"
    "- Max 2% risk per trade.\n\n"
    f"{JSON_INSTRUCTION}\n"
    f"Keys: {DECISION_KEYS}"
)

MEAN_REVERSION_SYSTEM = (
    "You are a Mean Reversion Bot for BTC/USDT paper trading.\n"
    "Strategy: RSI-based mean reversion.\n"
    "- BUY when RSI < 30 (oversold) and price is near lower range.\n"
    "- SELL when RSI > 70 (overbought) and price is near upper range.\n"
    "- HOLD if RSI is between 30 and 70.\n"
    "- Always define stop_loss and take_profit.\n"
    "- Max 2% risk per trade.\n\n"
    f"{JSON_INSTRUCTION}\n"
    f"Keys: {DECISION_KEYS}"
)

RISK_MANAGER_SYSTEM = (
    "You are a Risk Manager for BTC/USDT paper trading.\n"
    "You do NOT trade. You validate or veto trades proposed by other bots.\n\n"
    "Rules:\n"
    "- APPROVE only if at least 2 signals align across both proposals.\n"
    "- REJECT if signals conflict, confidence is low, or risk is too high.\n"
    "- Consider portfolio exposure and recent P&L.\n"
    "- Be conservative. When in doubt, REJECT.\n\n"
    f"{JSON_INSTRUCTION}\n"
    "Keys: approved (bool), reasoning, risk_notes"
)


# ---------------------------------------------------------------------------
# Strategy prompt builders
# ---------------------------------------------------------------------------

def build_trend_prompt(df: pd.DataFrame, current_price: float, portfolio: dict) -> dict:
    """Build prompt for the Trend Bot.

    Args:
        df: OHLCV DataFrame with indicators.
        current_price: Latest BTC/USDT price.
        portfolio: Current portfolio state.

    Returns:
        Prompt payload dict for Claude API.
    """
    user = (
        f"{_format_market_snapshot(df, current_price)}\n\n"
        f"{_format_portfolio(portfolio)}\n\n"
        "Focus on EMA crossover signals and trend direction.\n"
        f"Return only valid JSON with keys: {DECISION_KEYS}."
    )

    return {
        "system": TREND_SYSTEM,
        "messages": [{"role": "user", "content": user}],
    }


def build_mean_reversion_prompt(df: pd.DataFrame, current_price: float, portfolio: dict) -> dict:
    """Build prompt for the Mean Reversion Bot.

    Args:
        df: OHLCV DataFrame with indicators.
        current_price: Latest BTC/USDT price.
        portfolio: Current portfolio state.

    Returns:
        Prompt payload dict for Claude API.
    """
    user = (
        f"{_format_market_snapshot(df, current_price)}\n\n"
        f"{_format_portfolio(portfolio)}\n\n"
        "Focus on RSI levels and mean reversion signals.\n"
        f"Return only valid JSON with keys: {DECISION_KEYS}."
    )

    return {
        "system": MEAN_REVERSION_SYSTEM,
        "messages": [{"role": "user", "content": user}],
    }


def build_risk_manager_prompt(
    trend_decision: dict,
    mean_reversion_decision: dict,
    portfolio: dict,
) -> dict:
    """Build prompt for the Risk Manager to validate or veto.

    Args:
        trend_decision: Decision dict from Trend Bot.
        mean_reversion_decision: Decision dict from Mean Reversion Bot.
        portfolio: Current portfolio state.

    Returns:
        Prompt payload dict for Claude API.
    """
    user = (
        "Trend Bot Decision:\n"
        f"  {json.dumps(trend_decision, default=str)}\n\n"
        "Mean Reversion Bot Decision:\n"
        f"  {json.dumps(mean_reversion_decision, default=str)}\n\n"
        f"{_format_portfolio(portfolio)}\n\n"
        "Should this trade be approved or rejected?\n"
        "Return only valid JSON with keys: approved (bool), reasoning, risk_notes."
    )

    return {
        "system": RISK_MANAGER_SYSTEM,
        "messages": [{"role": "user", "content": user}],
    }


# ---------------------------------------------------------------------------
# Legacy single-prompt builder (kept for backward compatibility)
# ---------------------------------------------------------------------------

def load_system_prompt() -> str:
    """Load the system prompt from prompts/system_prompt.txt.

    Returns:
        System prompt string.
    """
    path = PROMPTS_DIR / "system_prompt.txt"
    return path.read_text(encoding="utf-8").strip()


def build_messages(df: pd.DataFrame, current_price: float, portfolio: dict) -> dict:
    """Build prompt payload using the generic system prompt.

    Args:
        df: OHLCV DataFrame with indicators.
        current_price: Latest BTC/USDT price.
        portfolio: Current portfolio state dict.

    Returns:
        dict with 'system' and 'messages' keys for the Anthropic API.
    """
    system = load_system_prompt()
    user = (
        f"{_format_market_snapshot(df, current_price)}\n\n"
        f"{_format_portfolio(portfolio)}\n\n"
        f"Return only valid JSON with keys: {DECISION_KEYS}."
    )

    return {
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }


# ---------------------------------------------------------------------------
# Review prompt
# ---------------------------------------------------------------------------

def build_review_prompt(
    entry_price: float,
    exit_price: float,
    pnl_percent: float,
    duration_hours: float,
    entry_indicators: dict,
    action_history: list[str],
) -> dict:
    """Build a prompt payload for Claude to review a completed trade.

    Args:
        entry_price: Price at BUY.
        exit_price: Price at SELL.
        pnl_percent: Realized profit/loss as a percentage.
        duration_hours: Hours between entry and exit.
        entry_indicators: dict with ema_fast, ema_slow, rsi, trend at entry.
        action_history: Recent actions leading to this trade.

    Returns:
        dict with 'system' and 'messages' keys for the Anthropic API.
    """
    system = (
        "You are a trading review analyst for BTC/USDT paper trades.\n"
        "Strategy rules: EMA crossover + RSI must align (min 2 signals), "
        "max 2% risk, HOLD if uncertain.\n"
        f"{JSON_INSTRUCTION}"
    )

    user = (
        "Trade Details:\n"
        f"  Entry:    ${entry_price:,.2f}\n"
        f"  Exit:     ${exit_price:,.2f}\n"
        f"  P&L:      {pnl_percent:+.2f}%\n"
        f"  Duration: {duration_hours:.1f}h\n\n"
        "Indicators at Entry:\n"
        f"  EMA(9):  {entry_indicators.get('ema_fast', 'N/A')}\n"
        f"  EMA(21): {entry_indicators.get('ema_slow', 'N/A')}\n"
        f"  RSI(14): {entry_indicators.get('rsi', 'N/A')}\n"
        f"  Trend:   {entry_indicators.get('trend', 'N/A')}\n\n"
        f"Action History: {', '.join(action_history)}\n\n"
        "Return JSON with keys: verdict, strengths, mistakes, improvement."
    )

    return {
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
