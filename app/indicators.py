"""
indicators.py - Technical indicator computation.

Computes EMA (fast/slow), RSI, and trend detection from OHLCV data.
Each function takes a DataFrame and returns it with new columns added.
"""

import pandas as pd

# Indicator periods
EMA_FAST_PERIOD = 9
EMA_SLOW_PERIOD = 21
RSI_PERIOD = 14
TREND_LOOKBACK = 5


def add_ema(df: pd.DataFrame) -> pd.DataFrame:
    """Add fast (9) and slow (21) exponential moving averages.

    Args:
        df: OHLCV DataFrame with a 'close' column.

    Returns:
        DataFrame with 'ema_fast' and 'ema_slow' columns added.
    """
    df["ema_fast"] = df["close"].ewm(span=EMA_FAST_PERIOD, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=EMA_SLOW_PERIOD, adjust=False).mean()
    return df


def add_rsi(df: pd.DataFrame, period: int = RSI_PERIOD) -> pd.DataFrame:
    """Add Relative Strength Index (14-period).

    Uses the standard Wilder smoothing method:
    RSI = 100 - (100 / (1 + avg_gain / avg_loss))

    Args:
        df: OHLCV DataFrame with a 'close' column.
        period: RSI lookback period.

    Returns:
        DataFrame with an 'rsi' column added (values 0-100).
    """
    delta = df["close"].diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss
    df["rsi"] = 100 - (100 / (1 + rs))

    return df


def detect_trend(df: pd.DataFrame, lookback: int = TREND_LOOKBACK) -> str:
    """Detect the recent price trend based on the last N closes.

    Compares each close to the previous one. If the majority move
    in one direction, that's the trend; otherwise it's sideways.

    Args:
        df: OHLCV DataFrame with a 'close' column.
        lookback: Number of recent candles to evaluate.

    Returns:
        One of: 'upward', 'downward', 'sideways'.
    """
    recent = df["close"].tail(lookback)
    changes = recent.diff().dropna()

    up = (changes > 0).sum()
    down = (changes < 0).sum()

    threshold = len(changes) * 0.6

    if up >= threshold:
        return "upward"
    if down >= threshold:
        return "downward"
    return "sideways"


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all indicators and add them to the DataFrame.

    Adds: ema_fast, ema_slow, rsi columns.
    Also stores the detected trend as a DataFrame attribute.

    Args:
        df: OHLCV DataFrame from data_fetcher.

    Returns:
        DataFrame with indicator columns added.
        Access df.attrs['trend'] for the trend string.
    """
    df = add_ema(df)
    df = add_rsi(df)
    df.attrs["trend"] = detect_trend(df)

    return df
