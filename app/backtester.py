"""
backtester.py - Historical backtesting engine.

Loads 3–6 months of BTC/USDT OHLCV data, computes indicators,
generates deterministic signals (same rules as the live bots),
runs them through the decision engine, and simulates trades
using the same broker logic. No Claude calls — pure rule-based.

Usage:
    python app/backtester.py
"""

from __future__ import annotations

import pandas as pd

from config import INITIAL_BALANCE, RISK_PER_TRADE_PERCENT
from data_fetcher import fetch_historical_cached
from indicators import add_ema, add_rsi, detect_trend, EMA_SLOW_PERIOD, RSI_PERIOD, TREND_LOOKBACK
from paper_broker import MIN_CONFIDENCE, FULL_SIZE_CONFIDENCE, CONFIDENCE_SCALES, VOLATILITY_THRESHOLD

# Minimum indicator warmup rows before trading
WARMUP = max(EMA_SLOW_PERIOD, RSI_PERIOD, TREND_LOOKBACK) + 1

# How many 1h candles to fetch (≈6 months)
TOTAL_CANDLES = 4380


# ---------------------------------------------------------------------------
# Rule-based signal generators (mirror the live bot prompts)
# ---------------------------------------------------------------------------

def trend_signal(row: pd.Series, prev_row: pd.Series, ema_col_fast: str = "ema_fast", ema_col_slow: str = "ema_slow") -> dict:
    """Generate a Trend Bot decision from EMA crossover rules.

    BUY when fast EMA crosses above slow EMA.
    SELL when fast EMA crosses below slow EMA.
    HOLD otherwise.

    Args:
        row: Current candle with indicator columns.
        prev_row: Previous candle with indicator columns.
        ema_col_fast: Column name for the fast EMA.
        ema_col_slow: Column name for the slow EMA.

    Returns:
        Decision dict with action, confidence, signals.
    """
    crossed_up = prev_row[ema_col_fast] <= prev_row[ema_col_slow] and row[ema_col_fast] > row[ema_col_slow]
    crossed_down = prev_row[ema_col_fast] >= prev_row[ema_col_slow] and row[ema_col_fast] < row[ema_col_slow]

    if crossed_up:
        gap = (row[ema_col_fast] - row[ema_col_slow]) / row["close"]
        conf = min(0.5 + gap * 100, 0.95)
        return {"action": "BUY", "confidence": round(conf, 4), "signals": ["EMA_crossover_up"]}

    if crossed_down:
        gap = (row[ema_col_slow] - row[ema_col_fast]) / row["close"]
        conf = min(0.5 + gap * 100, 0.95)
        return {"action": "SELL", "confidence": round(conf, 4), "signals": ["EMA_crossover_down"]}

    return {"action": "HOLD", "confidence": 0.3, "signals": []}


def mean_reversion_signal(row: pd.Series, rsi_buy: float = 30, rsi_sell: float = 70) -> dict:
    """Generate a Mean Reversion Bot decision from RSI levels.

    BUY when RSI < rsi_buy (oversold).
    SELL when RSI > rsi_sell (overbought).
    HOLD otherwise.

    Args:
        row: Current candle with indicator columns.
        rsi_buy: RSI threshold for oversold (default 30).
        rsi_sell: RSI threshold for overbought (default 70).

    Returns:
        Decision dict with action, confidence, signals.
    """
    rsi = row["rsi"]

    if pd.isna(rsi):
        return {"action": "HOLD", "confidence": 0.0, "signals": []}

    if rsi < rsi_buy:
        conf = min(0.5 + (rsi_buy - rsi) / rsi_buy, 0.95)
        return {"action": "BUY", "confidence": round(conf, 4), "signals": ["RSI_oversold"]}

    if rsi > rsi_sell:
        conf = min(0.5 + (rsi - rsi_sell) / (100 - rsi_sell), 0.95)
        return {"action": "SELL", "confidence": round(conf, 4), "signals": ["RSI_overbought"]}

    return {"action": "HOLD", "confidence": 0.3, "signals": []}


# ---------------------------------------------------------------------------
# Simulated broker (in-memory, no file I/O)
# ---------------------------------------------------------------------------

def _sim_position_size(cash: float, price: float, confidence: float) -> float:
    """Calculate position size using the same rules as paper_broker."""
    risk_amount = cash * (RISK_PER_TRADE_PERCENT / 100)
    qty = risk_amount / price
    if confidence < FULL_SIZE_CONFIDENCE:
        qty *= CONFIDENCE_SCALES["medium"]
    return qty


def _is_volatile(row: pd.Series) -> bool:
    """Check if a candle exceeds the volatility threshold."""
    spread = (row["high"] - row["low"]) / row["close"]
    return spread > VOLATILITY_THRESHOLD


def _combine_signals(trend: dict, mean_rev: dict) -> dict:
    """Combine two bot signals for backtesting.

    Same logic as decision_engine.combine_decisions, but without the
    weak-signal penalty since there is no risk manager in backtest.

    - Both agree → strong, average confidence.
    - One acts, other HOLDs → weak, use actor's full confidence.
    - Conflict (BUY vs SELL) → HOLD.
    - Both HOLD → HOLD.

    Args:
        trend: Trend Bot decision dict.
        mean_rev: Mean Reversion Bot decision dict.

    Returns:
        Combined decision dict.
    """
    t_action = trend.get("action", "HOLD")
    m_action = mean_rev.get("action", "HOLD")
    t_conf = float(trend.get("confidence", 0.0))
    m_conf = float(mean_rev.get("confidence", 0.0))

    t_signals = trend.get("signals", [])
    m_signals = mean_rev.get("signals", [])
    all_signals = list(set(t_signals + m_signals))

    if t_action == "HOLD" and m_action == "HOLD":
        return {"action": "HOLD", "confidence": 0.0, "signals": [], "strength": "none"}

    if t_action == m_action:
        return {
            "action": t_action,
            "confidence": round((t_conf + m_conf) / 2, 4),
            "signals": all_signals,
            "strength": "strong",
        }

    if t_action != "HOLD" and m_action == "HOLD":
        return {"action": t_action, "confidence": t_conf, "signals": all_signals, "strength": "weak"}

    if m_action != "HOLD" and t_action == "HOLD":
        return {"action": m_action, "confidence": m_conf, "signals": all_signals, "strength": "weak"}

    # Conflict
    return {"action": "HOLD", "confidence": 0.0, "signals": all_signals, "strength": "conflict"}


# ---------------------------------------------------------------------------
# Backtest runner
# ---------------------------------------------------------------------------

def run_backtest(df: pd.DataFrame, config: dict = None) -> dict:
    """Run the full backtest simulation.

    Iterates through each candle after warmup, generates signals,
    combines them via the decision engine, and simulates trades.

    Args:
        df: Full OHLCV DataFrame with indicator columns.
            Must contain the EMA/RSI columns named in config.
        config: Optional overrides for signal parameters:
            - ema_col_fast: column name for fast EMA (default 'ema_fast')
            - ema_col_slow: column name for slow EMA (default 'ema_slow')
            - rsi_buy: RSI buy threshold (default 30)
            - rsi_sell: RSI sell threshold (default 70)

    Returns:
        dict with metrics and trade log.
    """
    if config is None:
        config = {}

    ema_col_fast = config.get("ema_col_fast", "ema_fast")
    ema_col_slow = config.get("ema_col_slow", "ema_slow")
    rsi_buy = config.get("rsi_buy", 30)
    rsi_sell = config.get("rsi_sell", 70)

    cash = INITIAL_BALANCE
    position_open = False
    position_size = 0.0
    entry_price = 0.0
    last_trade_idx = -WARMUP

    trades = []
    equity_curve = []

    for i in range(WARMUP, len(df)):
        row = df.iloc[i]
        prev_row = df.iloc[i - 1]
        price = row["close"]

        # Compute trend for this window
        window = df.iloc[max(0, i - TREND_LOOKBACK + 1):i + 1]
        trend_dir = detect_trend(window, lookback=min(len(window), TREND_LOOKBACK))

        # Generate signals with configurable params
        t_decision = trend_signal(row, prev_row, ema_col_fast, ema_col_slow)
        m_decision = mean_reversion_signal(row, rsi_buy, rsi_sell)

        # Combine signals (no risk manager in backtest — use full confidence)
        combined = _combine_signals(t_decision, m_decision)
        action = combined["action"]
        confidence = combined["confidence"]

        # Apply guards
        if action in ("BUY", "SELL"):
            if confidence < MIN_CONFIDENCE:
                action = "HOLD"
            elif _is_volatile(row):
                action = "HOLD"
            elif (i - last_trade_idx) < 2:  # cooldown: 2 candles (2h)
                action = "HOLD"

        # Execute
        pnl = 0.0

        if action == "BUY" and not position_open and cash > 0:
            qty = _sim_position_size(cash, price, confidence)
            cost = qty * price
            cash -= cost
            position_open = True
            position_size = qty
            entry_price = price
            last_trade_idx = i
            trades.append({
                "index": i,
                "timestamp": str(row["timestamp"]),
                "action": "BUY",
                "price": price,
                "quantity": qty,
                "pnl": 0.0,
            })

        elif action == "SELL" and position_open:
            pnl = (price - entry_price) * position_size
            cash += position_size * price
            trades.append({
                "index": i,
                "timestamp": str(row["timestamp"]),
                "action": "SELL",
                "price": price,
                "quantity": position_size,
                "pnl": pnl,
            })
            position_open = False
            position_size = 0.0
            entry_price = 0.0
            last_trade_idx = i

        # Track equity
        unrealized = (price - entry_price) * position_size if position_open else 0.0
        total_equity = cash + (position_size * price)
        equity_curve.append({
            "timestamp": str(row["timestamp"]),
            "price": price,
            "total_equity": total_equity,
            "unrealized_pnl": unrealized,
        })

    return _compute_results(trades, equity_curve, cash, position_open, position_size, df.iloc[-1]["close"])


def _compute_results(
    trades: list,
    equity_curve: list,
    cash: float,
    position_open: bool,
    position_size: float,
    last_price: float,
) -> dict:
    """Compute summary metrics from the backtest.

    Args:
        trades: List of executed trade dicts.
        equity_curve: List of equity snapshot dicts.
        cash: Final cash balance.
        position_open: Whether a position is still open.
        position_size: Remaining BTC position.
        last_price: Last candle's close price.

    Returns:
        dict with metrics, trades, equity_curve.
    """
    sells = [t for t in trades if t["action"] == "SELL"]
    pnl_values = [t["pnl"] for t in sells]

    total_trades = len(sells)
    wins = sum(1 for p in pnl_values if p > 0)
    losses = sum(1 for p in pnl_values if p < 0)
    total_pnl = sum(pnl_values)
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0

    # Max drawdown from equity curve
    max_drawdown = 0.0
    peak = 0.0
    for snap in equity_curve:
        eq = snap["total_equity"]
        if eq > peak:
            peak = eq
        dd = peak - eq
        if dd > max_drawdown:
            max_drawdown = dd

    final_equity = cash + (position_size * last_price if position_open else 0.0)

    return {
        "metrics": {
            "initial_balance": INITIAL_BALANCE,
            "final_equity": round(final_equity, 4),
            "total_pnl": round(total_pnl, 4),
            "return_pct": round((final_equity - INITIAL_BALANCE) / INITIAL_BALANCE * 100, 4),
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 2),
            "max_drawdown": round(max_drawdown, 4),
        },
        "trades": trades,
        "equity_curve": equity_curve,
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_results(results: dict) -> None:
    """Print a formatted backtest summary.

    Args:
        results: Output from run_backtest().
    """
    m = results["metrics"]

    print("\n" + "=" * 55)
    print("  Backtest Results")
    print("=" * 55)
    print(f"  Period:         {results['equity_curve'][0]['timestamp'][:10]}"
          f" to {results['equity_curve'][-1]['timestamp'][:10]}")
    print(f"  Candles:        {len(results['equity_curve'])}")
    print("-" * 55)
    print(f"  Initial:        ${m['initial_balance']:,.2f}")
    print(f"  Final Equity:   ${m['final_equity']:,.4f}")
    print(f"  Total P&L:      ${m['total_pnl']:,.4f}")
    print(f"  Return:         {m['return_pct']:+.4f}%")
    print("-" * 55)
    print(f"  Total Trades:   {m['total_trades']}")
    print(f"  Wins:           {m['wins']}")
    print(f"  Losses:         {m['losses']}")
    print(f"  Win Rate:       {m['win_rate']}%")
    print(f"  Max Drawdown:   ${m['max_drawdown']:,.4f}")
    print("=" * 55)
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Fetch historical data (cached), compute indicators, and run backtest."""
    df = fetch_historical_cached(total=TOTAL_CANDLES)
    print(f"Dataset: {len(df)} candles from {df.iloc[0]['timestamp']} to {df.iloc[-1]['timestamp']}")

    print("Computing indicators...")
    df = add_ema(df)
    df = add_rsi(df)

    print("Running backtest...")
    results = run_backtest(df)

    print_results(results)


if __name__ == "__main__":
    main()
