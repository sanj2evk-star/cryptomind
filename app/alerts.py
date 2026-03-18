"""
alerts.py - Real-time notification system.

Sends formatted alerts via Telegram for:
- Trade opened (BUY) with sizing details
- Trade closed (SELL) with P&L and win/loss streak
- Trade rejected with reason
- Circuit breaker activation
- Regime change
- Anomaly detection
- Daily performance summary
- Weekly evaluation summary

Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env.
Silently skips if credentials are not configured.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import quote
from urllib.error import URLError

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _get_credentials() -> tuple[str, str] | None:
    """Load Telegram credentials from environment."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return None
    return token, chat_id


# ---------------------------------------------------------------------------
# Core sender
# ---------------------------------------------------------------------------

def _send(message: str) -> bool:
    """Send an HTML-formatted message via Telegram Bot API.

    Args:
        message: HTML-formatted text.

    Returns:
        True if sent successfully, False otherwise.
    """
    creds = _get_credentials()
    if creds is None:
        return False

    token, chat_id = creds
    url = TELEGRAM_API.format(token=token)

    payload = json.dumps({
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode()

    try:
        req = Request(url, data=payload, method="POST",
                      headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except (URLError, OSError) as e:
        print(f"[alerts] Telegram send failed: {e}")
        return False


def _timestamp() -> str:
    """Return a short UTC timestamp for messages."""
    return datetime.now(timezone.utc).strftime("%H:%M UTC")


# ---------------------------------------------------------------------------
# Trade alerts
# ---------------------------------------------------------------------------

def notify_trade_opened(result: dict, decision: dict = None) -> bool:
    """Alert when a new position is opened (BUY).

    Args:
        result: Trade result from paper_broker.
        decision: Final decision dict (optional, for extra context).

    Returns:
        True if sent.
    """
    symbol = result.get("symbol", "BTC/USDT")
    asset = symbol.split("/")[0]
    price = result.get("price", 0.0)
    qty = result.get("quantity", 0.0)
    portfolio = result.get("portfolio", {})
    cash = portfolio.get("cash", 0.0)
    equity = portfolio.get("total_equity", 0.0)

    confidence = decision.get("confidence", 0.0) if decision else 0.0
    strength = decision.get("strength", "?") if decision else "?"
    regime = decision.get("market_condition", "?") if decision else "?"

    msg = (
        f"<b>BUY {symbol}</b>\n"
        f"\n"
        f"Price:      ${price:,.2f}\n"
        f"Size:       {qty:.6f} {asset}\n"
        f"Confidence: {confidence:.0%}\n"
        f"Signal:     {strength}\n"
        f"Regime:     {regime}\n"
        f"\n"
        f"Cash:   ${cash:,.2f}\n"
        f"Equity: ${equity:,.4f}\n"
        f"\n"
        f"<i>{_timestamp()}</i>"
    )
    return _send(msg)


def notify_trade_closed(result: dict, decision: dict = None) -> bool:
    """Alert when a position is closed (SELL).

    Args:
        result: Trade result from paper_broker.
        decision: Final decision dict (optional).

    Returns:
        True if sent.
    """
    symbol = result.get("symbol", "BTC/USDT")
    asset = symbol.split("/")[0]
    price = result.get("price", 0.0)
    qty = result.get("quantity", 0.0)
    pnl = result.get("pnl", 0.0)
    portfolio = result.get("portfolio", {})
    cash = portfolio.get("cash", 0.0)
    equity = portfolio.get("total_equity", 0.0)
    total_pnl = portfolio.get("realized_pnl", 0.0)

    outcome = "WIN" if pnl >= 0 else "LOSS"
    sign = "+" if pnl >= 0 else ""

    msg = (
        f"<b>SELL {symbol} — {outcome}</b>\n"
        f"\n"
        f"Price:       ${price:,.2f}\n"
        f"Size:        {qty:.6f} {asset}\n"
        f"Trade P&L:   {sign}${pnl:,.4f}\n"
        f"Total P&L:   ${total_pnl:,.4f}\n"
        f"\n"
        f"Cash:   ${cash:,.2f}\n"
        f"Equity: ${equity:,.4f}\n"
        f"\n"
        f"<i>{_timestamp()}</i>"
    )
    return _send(msg)


def notify_rejected(action: str, symbol: str, reason: str) -> bool:
    """Alert when a trade is rejected by guards.

    Args:
        action: BUY or SELL.
        symbol: Trading pair.
        reason: Rejection reason.

    Returns:
        True if sent.
    """
    msg = (
        f"<b>REJECTED {action} {symbol}</b>\n"
        f"\n"
        f"{reason}\n"
        f"\n"
        f"<i>{_timestamp()}</i>"
    )
    return _send(msg)


# ---------------------------------------------------------------------------
# System alerts
# ---------------------------------------------------------------------------

def notify_circuit_breaker(trigger: str, resume_at: str) -> bool:
    """Alert when the circuit breaker activates.

    Args:
        trigger: What caused it (drawdown / consecutive losses).
        resume_at: ISO timestamp when trading resumes.

    Returns:
        True if sent.
    """
    resume_short = resume_at[:16].replace("T", " ") if resume_at else "?"

    msg = (
        f"<b>CIRCUIT BREAKER ACTIVATED</b>\n"
        f"\n"
        f"Trigger:    {trigger}\n"
        f"Resumes at: {resume_short} UTC\n"
        f"\n"
        f"All trading halted until cooldown expires.\n"
        f"\n"
        f"<i>{_timestamp()}</i>"
    )
    return _send(msg)


def notify_regime_change(old_regime: str, new_regime: str, strategy: str) -> bool:
    """Alert when the market regime changes.

    Args:
        old_regime: Previous regime.
        new_regime: New regime.
        strategy: Selected strategy for the new regime.

    Returns:
        True if sent.
    """
    msg = (
        f"<b>REGIME CHANGE</b>\n"
        f"\n"
        f"{old_regime} -> {new_regime}\n"
        f"Strategy: {strategy}\n"
        f"\n"
        f"<i>{_timestamp()}</i>"
    )
    return _send(msg)


def notify_anomaly(reasons: list[str]) -> bool:
    """Alert when market anomalies are detected.

    Args:
        reasons: List of anomaly descriptions.

    Returns:
        True if sent.
    """
    detail = "\n".join(f"  - {r}" for r in reasons)

    msg = (
        f"<b>ANOMALY DETECTED</b>\n"
        f"\n"
        f"{detail}\n"
        f"\n"
        f"Trading paused until conditions normalize.\n"
        f"\n"
        f"<i>{_timestamp()}</i>"
    )
    return _send(msg)


# ---------------------------------------------------------------------------
# Summary alerts
# ---------------------------------------------------------------------------

def notify_daily_summary(metrics: dict, portfolio: dict = None) -> bool:
    """Send end-of-day performance summary.

    Args:
        metrics: Metrics from performance.compute_metrics().
        portfolio: Current portfolio state (optional).

    Returns:
        True if sent.
    """
    trades = metrics.get("total_trades", 0)
    wins = metrics.get("wins", 0)
    losses = metrics.get("losses", 0)
    wr = metrics.get("win_rate", 0.0)
    pnl = metrics.get("total_pnl", 0.0)
    dd = metrics.get("max_drawdown", 0.0)

    pnl_icon = "+" if pnl >= 0 else ""

    lines = [
        "<b>DAILY SUMMARY</b>",
        "",
        f"Trades: {trades}",
        f"Wins:   {wins} | Losses: {losses}",
        f"Win Rate: {wr:.1f}%",
        f"P&L:     {pnl_icon}${pnl:,.4f}",
        f"Max DD:  ${dd:,.4f}",
    ]

    if portfolio:
        equity = portfolio.get("total_equity", portfolio.get("cash", 0.0))
        streak = portfolio.get("consecutive_losses", 0)
        lines.append("")
        lines.append(f"Equity: ${equity:,.4f}")
        if streak > 0:
            lines.append(f"Loss streak: {streak}")

    lines.append("")
    lines.append(f"<i>{_timestamp()}</i>")

    return _send("\n".join(lines))


def notify_weekly_evaluation(evaluation: dict) -> bool:
    """Send weekly system evaluation summary.

    Args:
        evaluation: Evaluation dict from evaluator.

    Returns:
        True if sent.
    """
    status = "IMPROVING" if evaluation.get("improving") else "NEEDS WORK"
    score = evaluation.get("score", 0)

    strengths = evaluation.get("strengths", [])
    failures = evaluation.get("failures", [])
    adjustments = evaluation.get("adjustments", [])

    lines = [
        f"<b>WEEKLY EVALUATION — {status}</b>",
        f"Score: {score}/10",
        "",
    ]

    if strengths:
        lines.append("Strengths:")
        for s in strengths[:3]:
            lines.append(f"  + {s}")

    if failures:
        lines.append("Issues:")
        for f in failures[:3]:
            lines.append(f"  - {f}")

    if adjustments:
        lines.append("Adjustments:")
        for a in adjustments[:3]:
            lines.append(f"  > {a}")

    summary = evaluation.get("summary", "")
    if summary:
        lines.append("")
        lines.append(f"<i>{summary[:200]}</i>")

    lines.append("")
    lines.append(f"<i>{_timestamp()}</i>")

    return _send("\n".join(lines))


# ---------------------------------------------------------------------------
# Dispatchers
# ---------------------------------------------------------------------------

def alert_on_trade(result: dict, decision: dict = None) -> bool:
    """Dispatch the right alert based on trade action.

    Args:
        result: Trade result from paper_broker.
        decision: Final decision dict (optional).

    Returns:
        True if an alert was sent.
    """
    action = result.get("action", "HOLD")

    if action == "BUY":
        return notify_trade_opened(result, decision)
    elif action == "SELL":
        return notify_trade_closed(result, decision)

    return False


def notify(message: str) -> bool:
    """Send a plain text alert.

    Args:
        message: Message text.

    Returns:
        True if sent.
    """
    return _send(message)
