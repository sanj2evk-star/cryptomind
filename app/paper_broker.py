"""
paper_broker.py - Simulated paper trading broker.

Manages a virtual portfolio with cash balance and a single BTC position.
Executes BUY/SELL/HOLD decisions against a given market price.
Enforces no double-buy, no sell-without-position, and basic risk limits.
Persists state to data/portfolio.json.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone, date, timedelta

from config import DATA_DIR, INITIAL_BALANCE, MAX_TRADES_PER_DAY, RISK_PER_TRADE_PERCENT, SYMBOL

PORTFOLIO_FILE = DATA_DIR / "portfolio.json"
REJECTED_FILE = DATA_DIR / "rejected.csv"
EQUITY_FILE = DATA_DIR / "equity.csv"

MIN_CONFIDENCE = 0.65
FULL_SIZE_CONFIDENCE = 0.75
COOLDOWN_HOURS = 2
VOLATILITY_THRESHOLD = 0.03  # 3% price swing = volatile

# Circuit breaker thresholds
MAX_DRAWDOWN_PCT = 0.10        # 10% drawdown from peak equity → halt
MAX_CONSECUTIVE_LOSSES = 3     # 3 losses in a row → halt
CIRCUIT_BREAKER_HOURS = 24     # halt duration before auto-resume

# Dynamic sizing scales (multiplied against base risk amount)
CONFIDENCE_SCALES = {
    "high": 1.0,    # confidence >= 0.75
    "medium": 0.5,  # confidence 0.65–0.75
}
VOLATILITY_SCALES = {
    "low": 1.2,     # ATR% < 1% — calm market, slight boost
    "normal": 1.0,  # ATR% 1%–2%
    "high": 0.5,    # ATR% 2%–3% — cut size in half
}
REGIME_SCALES = {
    "trending_up": 1.2,     # strong trend, slight boost
    "trending_down": 1.2,   # strong trend (shorting opportunity)
    "sideways": 0.8,        # range-bound, reduce exposure
    "high_volatility": 0.4, # dangerous, minimal size
}

REJECTED_FIELDS = ["timestamp", "action", "confidence", "price", "reason"]


def _default_position() -> dict:
    """Return default values for a single asset position.

    Returns:
        Position dict with zero values.
    """
    return {
        "position_open": False,
        "position_size": 0.0,
        "entry_price": 0.0,
    }


def _default_portfolio() -> dict:
    """Return a fresh multi-asset portfolio.

    Shared cash pool with per-asset positions.

    Returns:
        Portfolio dict.
    """
    return {
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


def _get_position(portfolio: dict, symbol: str) -> dict:
    """Get the position for a specific asset, creating it if needed.

    Args:
        portfolio: Portfolio dict.
        symbol: Trading pair (e.g. 'BTC/USDT').

    Returns:
        Position dict for this symbol.
    """
    if "positions" not in portfolio:
        portfolio["positions"] = {}

    if symbol not in portfolio["positions"]:
        portfolio["positions"][symbol] = _default_position()

    return portfolio["positions"][symbol]


def load_portfolio() -> dict:
    """Load portfolio state from disk.

    Handles migration from old single-asset format to new multi-asset.
    Returns the default portfolio if the file is missing or corrupt.

    Returns:
        Portfolio dict with 'positions' sub-dict.
    """
    try:
        data = json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))

        # Migrate old single-asset format → multi-asset
        if "positions" not in data:
            pos = {
                "position_open": data.pop("position_open", False),
                "position_size": data.pop("position_size", 0.0),
                "entry_price": data.pop("entry_price", 0.0),
            }
            data["positions"] = {SYMBOL: pos} if pos["position_open"] else {}

        # Ensure all top-level keys exist
        default = _default_portfolio()
        for key in default:
            if key not in data:
                data[key] = default[key]

        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return _default_portfolio()


def save_portfolio(portfolio: dict) -> None:
    """Persist portfolio state to disk.

    Args:
        portfolio: Current portfolio dict.
    """
    PORTFOLIO_FILE.write_text(
        json.dumps(portfolio, indent=2) + "\n",
        encoding="utf-8",
    )


def _get_volatility_level(df) -> str:
    """Classify current volatility from the DataFrame's ATR.

    Args:
        df: OHLCV DataFrame with optional 'atr' column.

    Returns:
        One of: 'low', 'normal', 'high'.
    """
    if df is None or df.empty or "atr" not in df.columns:
        return "normal"

    last = df.iloc[-1]
    atr_pct = last["atr"] / last["close"] if last["close"] > 0 else 0

    if atr_pct < 0.01:
        return "low"
    if atr_pct > 0.02:
        return "high"
    return "normal"


def _calculate_position_size(
    cash: float,
    price: float,
    confidence: float,
    df=None,
    regime: str = "unknown",
) -> tuple[float, str]:
    """Calculate BTC quantity using dynamic position sizing.

    Base size = RISK_PER_TRADE_PERCENT of cash, then scaled by:
    1. Confidence level (high >= 0.75, medium 0.65–0.75)
    2. Volatility level (ATR-based: low/normal/high)
    3. Market regime (trending/sideways/volatile)

    Final scale is capped at 0.25x–1.5x to prevent extremes.

    Args:
        cash: Available USDT balance.
        price: Current BTC price.
        confidence: Decision confidence (0.0 to 1.0).
        df: OHLCV DataFrame with 'atr' column (optional).
        regime: Market regime string from regime_detector (optional).

    Returns:
        Tuple of (quantity in BTC, sizing breakdown string).
    """
    base_risk = cash * (RISK_PER_TRADE_PERCENT / 100)
    base_qty = base_risk / price

    # Confidence scale
    conf_level = "high" if confidence >= FULL_SIZE_CONFIDENCE else "medium"
    conf_scale = CONFIDENCE_SCALES[conf_level]

    # Volatility scale
    vol_level = _get_volatility_level(df)
    vol_scale = VOLATILITY_SCALES[vol_level]

    # Regime scale
    regime_scale = REGIME_SCALES.get(regime, 1.0)

    # Combined scale, capped to [0.25, 1.5]
    combined = conf_scale * vol_scale * regime_scale
    combined = max(0.25, min(1.5, combined))

    qty = base_qty * combined

    breakdown = (
        f"conf={conf_level}({conf_scale}x) "
        f"vol={vol_level}({vol_scale}x) "
        f"regime={regime}({regime_scale}x) "
        f"-> {combined:.2f}x"
    )

    return qty, breakdown


def _log_rejected(action: str, confidence: float, price: float, reason: str) -> None:
    """Append a rejected trade to rejected.csv.

    Args:
        action: The action that was rejected.
        confidence: The decision's confidence value.
        price: Current market price.
        reason: Why the trade was rejected.
    """
    if not REJECTED_FILE.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(REJECTED_FILE, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=REJECTED_FIELDS).writeheader()

    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "confidence": confidence,
        "price": price,
        "reason": reason,
    }

    with open(REJECTED_FILE, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=REJECTED_FIELDS).writerow(row)


def _reset_daily_counter(portfolio: dict) -> None:
    """Reset the daily trade counter if the date has changed.

    Args:
        portfolio: Current portfolio dict (mutated in place).
    """
    today = date.today().isoformat()
    if portfolio.get("last_trade_date") != today:
        portfolio["trades_today"] = 0
        portfolio["last_trade_date"] = today


def _check_cooldown(portfolio: dict) -> str | None:
    """Check if enough time has passed since the last trade.

    Args:
        portfolio: Current portfolio dict.

    Returns:
        Rejection reason string if cooldown is active, None otherwise.
    """
    last = portfolio.get("last_trade_time", "")
    if not last:
        return None

    try:
        last_dt = datetime.fromisoformat(last)
        now = datetime.now(timezone.utc)
        elapsed = (now - last_dt).total_seconds() / 3600

        if elapsed < COOLDOWN_HOURS:
            remaining = COOLDOWN_HOURS - elapsed
            return f"Cooldown active: {remaining:.1f}h remaining (min {COOLDOWN_HOURS}h between trades)."
    except (ValueError, TypeError):
        pass

    return None


def _check_circuit_breaker(portfolio: dict, current_equity: float) -> str | None:
    """Check if the circuit breaker should halt trading.

    Triggers on:
    - Drawdown exceeding MAX_DRAWDOWN_PCT from peak equity.
    - Consecutive losses exceeding MAX_CONSECUTIVE_LOSSES.

    Once triggered, trading is halted for CIRCUIT_BREAKER_HOURS.
    Auto-resumes after the cooldown expires.

    Args:
        portfolio: Current portfolio dict.
        current_equity: Current total portfolio value.

    Returns:
        Rejection reason if halted, None if trading is allowed.
    """
    # Check if an active halt is still in effect
    halt_until = portfolio.get("circuit_breaker_until", "")
    if halt_until:
        try:
            halt_dt = datetime.fromisoformat(halt_until)
            now = datetime.now(timezone.utc)
            if now < halt_dt:
                remaining = (halt_dt - now).total_seconds() / 3600
                return f"Circuit breaker active: {remaining:.1f}h remaining."
            # Cooldown expired — clear the halt
            portfolio["circuit_breaker_until"] = ""
        except (ValueError, TypeError):
            portfolio["circuit_breaker_until"] = ""

    # Check drawdown from peak
    peak = portfolio.get("peak_equity", INITIAL_BALANCE)
    if peak > 0 and current_equity < peak:
        drawdown_pct = (peak - current_equity) / peak
        if drawdown_pct >= MAX_DRAWDOWN_PCT:
            _activate_circuit_breaker(portfolio)
            return (
                f"Circuit breaker TRIGGERED: drawdown {drawdown_pct:.1%} "
                f">= {MAX_DRAWDOWN_PCT:.0%} threshold."
            )

    # Check consecutive losses
    if portfolio.get("consecutive_losses", 0) >= MAX_CONSECUTIVE_LOSSES:
        _activate_circuit_breaker(portfolio)
        return (
            f"Circuit breaker TRIGGERED: {portfolio['consecutive_losses']} "
            f"consecutive losses >= {MAX_CONSECUTIVE_LOSSES} threshold."
        )

    return None


def _activate_circuit_breaker(portfolio: dict) -> None:
    """Set the circuit breaker halt timestamp.

    Args:
        portfolio: Portfolio dict (mutated in place).
    """
    resume_at = datetime.now(timezone.utc) + timedelta(hours=CIRCUIT_BREAKER_HOURS)
    portfolio["circuit_breaker_until"] = resume_at.isoformat()


def _update_loss_streak(portfolio: dict, pnl: float) -> None:
    """Update the consecutive loss counter after a SELL.

    Args:
        portfolio: Portfolio dict (mutated in place).
        pnl: Realized P&L from the trade.
    """
    if pnl < 0:
        portfolio["consecutive_losses"] = portfolio.get("consecutive_losses", 0) + 1
    else:
        portfolio["consecutive_losses"] = 0


def _update_peak_equity(portfolio: dict, current_equity: float) -> None:
    """Update peak equity if current is a new high.

    Args:
        portfolio: Portfolio dict (mutated in place).
        current_equity: Current total equity.
    """
    peak = portfolio.get("peak_equity", INITIAL_BALANCE)
    if current_equity > peak:
        portfolio["peak_equity"] = current_equity


def _check_volatility(df) -> str | None:
    """Check if recent price action is too volatile to trade safely.

    Volatile = high-low range of the last candle exceeds VOLATILITY_THRESHOLD
    of the closing price.

    Args:
        df: OHLCV DataFrame (optional, can be None).

    Returns:
        Rejection reason string if too volatile, None otherwise.
    """
    if df is None or df.empty:
        return None

    last = df.iloc[-1]
    spread = (last["high"] - last["low"]) / last["close"]

    if spread > VOLATILITY_THRESHOLD:
        return f"Rejected: volatile market (spread {spread:.2%} > {VOLATILITY_THRESHOLD:.0%} threshold)."

    return None


def execute_trade(decision: dict, current_price: float, df=None, symbol: str = SYMBOL) -> dict:
    """Execute a paper trade for a specific asset.

    Supports multiple assets with separate positions sharing one cash pool.

    Rules enforced:
    - Confidence must be >= 65% to act.
    - Max trades per day cannot be exceeded.
    - Minimum cooldown between trades (2 hours).
    - No trading during volatile conditions (3%+ candle spread).
    - BUY: only if no position open for this asset and cash is available.
    - SELL: only if a position is open for this asset.
    - Invalid or unrecognized actions default to HOLD.

    Args:
        decision: Parsed decision dict with 'action' and 'confidence'.
        current_price: Current price for this asset.
        df: OHLCV DataFrame for volatility check (optional).
        symbol: Trading pair (default BTC/USDT).

    Returns:
        dict with trade result: action, symbol, price, quantity, pnl, portfolio snapshot.
    """
    portfolio = load_portfolio()
    _reset_daily_counter(portfolio)
    pos = _get_position(portfolio, symbol)

    action = decision.get("action", "HOLD").upper()
    confidence = float(decision.get("confidence", 0.0))
    asset = symbol.split("/")[0]

    # Compute current equity for circuit breaker check
    pos_value = sum(
        p["position_size"] * current_price
        for p in portfolio.get("positions", {}).values()
        if p.get("position_open")
    )
    current_equity = portfolio["cash"] + pos_value

    result = {
        "action": "HOLD",
        "symbol": symbol,
        "price": current_price,
        "quantity": 0.0,
        "pnl": 0.0,
        "reason": "",
    }

    # Circuit breaker — blocks ALL new trades
    if action in ("BUY", "SELL"):
        cb_reason = _check_circuit_breaker(portfolio, current_equity)
        if cb_reason:
            result["reason"] = f"HALTED {action} {symbol}: {cb_reason}"
            _log_rejected(action, confidence, current_price, result["reason"])
            save_portfolio(portfolio)  # persist halt state
            action = "HOLD"

    # Default invalid actions to HOLD
    if action not in ("BUY", "SELL", "HOLD"):
        result["reason"] = f"Invalid action '{action}', defaulting to HOLD."
        action = "HOLD"

    # Confidence gate
    if action in ("BUY", "SELL") and confidence < MIN_CONFIDENCE:
        reason = f"Rejected {action} {symbol}: confidence {confidence:.2f} < {MIN_CONFIDENCE}."
        result["reason"] = reason
        _log_rejected(action, confidence, current_price, reason)
        action = "HOLD"

    # Daily trade limit
    if action in ("BUY", "SELL") and portfolio["trades_today"] >= MAX_TRADES_PER_DAY:
        reason = f"Rejected {action} {symbol}: daily trade limit ({MAX_TRADES_PER_DAY}) reached."
        result["reason"] = reason
        _log_rejected(action, confidence, current_price, reason)
        action = "HOLD"

    # Cooldown between trades
    if action in ("BUY", "SELL"):
        cooldown_reason = _check_cooldown(portfolio)
        if cooldown_reason:
            result["reason"] = f"Rejected {action} {symbol}: {cooldown_reason}"
            _log_rejected(action, confidence, current_price, result["reason"])
            action = "HOLD"

    # Volatility guard
    if action in ("BUY", "SELL"):
        vol_reason = _check_volatility(df)
        if vol_reason:
            result["reason"] = f"Rejected {action} {symbol}: {vol_reason}"
            _log_rejected(action, confidence, current_price, result["reason"])
            action = "HOLD"

    # Extract regime from decision metadata
    regime = decision.get("market_condition", "unknown")

    if action == "BUY":
        if pos["position_open"]:
            reason = f"Rejected BUY {symbol}: position already open."
            result["reason"] = reason
            _log_rejected("BUY", confidence, current_price, reason)
        elif portfolio["cash"] <= 0:
            reason = f"Rejected BUY {symbol}: no cash available."
            result["reason"] = reason
            _log_rejected("BUY", confidence, current_price, reason)
        else:
            qty, sizing_info = _calculate_position_size(
                portfolio["cash"], current_price, confidence, df, regime,
            )
            cost = qty * current_price

            portfolio["cash"] -= cost
            pos["position_open"] = True
            pos["position_size"] = qty
            pos["entry_price"] = current_price
            portfolio["total_trades"] += 1
            portfolio["trades_today"] += 1
            portfolio["last_trade_time"] = datetime.now(timezone.utc).isoformat()

            result["action"] = "BUY"
            result["quantity"] = qty
            result["reason"] = f"Bought {qty:.6f} {asset} at ${current_price:,.2f} [{sizing_info}]"

    elif action == "SELL":
        if not pos["position_open"]:
            reason = f"Rejected SELL {symbol}: no open position."
            result["reason"] = reason
            _log_rejected("SELL", confidence, current_price, reason)
        else:
            qty = pos["position_size"]
            pnl = (current_price - pos["entry_price"]) * qty

            portfolio["cash"] += qty * current_price
            portfolio["realized_pnl"] += pnl
            pos["position_open"] = False
            pos["position_size"] = 0.0
            pos["entry_price"] = 0.0
            portfolio["total_trades"] += 1
            portfolio["trades_today"] += 1
            portfolio["last_trade_time"] = datetime.now(timezone.utc).isoformat()

            result["action"] = "SELL"
            result["quantity"] = qty
            result["pnl"] = pnl
            result["reason"] = f"Sold {qty:.6f} {asset} at ${current_price:,.2f} (P&L: ${pnl:,.2f})"

            # Track consecutive losses for circuit breaker
            _update_loss_streak(portfolio, pnl)

    else:
        if not result["reason"]:
            result["reason"] = f"Holding {symbol}, no action taken."

    # Update peak equity tracking
    unrealized = _compute_total_unrealized(portfolio, {symbol: current_price})
    total_equity = portfolio["cash"] + _compute_positions_value(portfolio, {symbol: current_price})
    _update_peak_equity(portfolio, total_equity)

    save_portfolio(portfolio)
    record_equity(current_price, portfolio, unrealized, total_equity)

    result["portfolio"] = {
        "cash": portfolio["cash"],
        "position_open": pos["position_open"],
        "position_size": pos["position_size"],
        "realized_pnl": portfolio["realized_pnl"],
        "unrealized_pnl": unrealized,
        "total_equity": total_equity,
    }

    return result


# ---------------------------------------------------------------------------
# Equity tracking
# ---------------------------------------------------------------------------

EQUITY_FIELDS = [
    "timestamp", "price", "cash", "position_size",
    "unrealized_pnl", "realized_pnl", "total_equity",
]


def _compute_total_unrealized(portfolio: dict, prices: dict) -> float:
    """Compute total unrealized P&L across all open positions.

    Args:
        portfolio: Portfolio dict with 'positions' sub-dict.
        prices: Dict mapping symbol -> current price.

    Returns:
        Total unrealized P&L in USDT.
    """
    total = 0.0
    for symbol, pos in portfolio.get("positions", {}).items():
        if pos.get("position_open") and symbol in prices:
            total += (prices[symbol] - pos["entry_price"]) * pos["position_size"]
    return total


def _compute_positions_value(portfolio: dict, prices: dict) -> float:
    """Compute total value of all open positions.

    Args:
        portfolio: Portfolio dict with 'positions' sub-dict.
        prices: Dict mapping symbol -> current price.

    Returns:
        Total positions value in USDT.
    """
    total = 0.0
    for symbol, pos in portfolio.get("positions", {}).items():
        if pos.get("position_open") and symbol in prices:
            total += pos["position_size"] * prices[symbol]
    return total


def record_equity(
    current_price: float,
    portfolio: dict,
    unrealized: float,
    total_equity: float,
) -> None:
    """Append a snapshot to the equity curve CSV.

    Called once per cycle to track portfolio value over time.

    Args:
        current_price: Current BTC/USDT price.
        portfolio: Current portfolio dict.
        unrealized: Unrealized P&L from _unrealized_pnl().
        total_equity: Total portfolio value (cash + position value).
    """
    if not EQUITY_FILE.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(EQUITY_FILE, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=EQUITY_FIELDS).writeheader()

    # Count total open positions across all assets
    open_positions = sum(
        1 for p in portfolio.get("positions", {}).values()
        if p.get("position_open")
    )

    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "price": round(current_price, 2),
        "cash": round(portfolio["cash"], 4),
        "position_size": open_positions,
        "unrealized_pnl": round(unrealized, 4),
        "realized_pnl": round(portfolio["realized_pnl"], 4),
        "total_equity": round(total_equity, 4),
    }

    with open(EQUITY_FILE, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=EQUITY_FIELDS).writerow(row)


def get_equity_curve() -> list[dict]:
    """Read the full equity curve from CSV.

    Returns:
        List of equity snapshot dicts, chronological order.
        Empty list if file is missing.
    """
    if not EQUITY_FILE.exists():
        return []

    with open(EQUITY_FILE, newline="") as f:
        return list(csv.DictReader(f))
