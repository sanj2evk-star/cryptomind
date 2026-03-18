"""
regime_detector.py - Market regime detection.

Classifies the current market into one of four regimes
based on price direction and volatility (ATR):

- trending_up:      strong directional move upward, normal volatility
- trending_down:    strong directional move downward, normal volatility
- sideways:         no clear direction, low volatility
- high_volatility:  large price swings regardless of direction

Uses:
- ATR (Average True Range) for volatility measurement
- Directional movement over a lookback window for trend detection
"""

from __future__ import annotations

import pandas as pd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ATR_PERIOD = 14
LOOKBACK = 20

# ATR as % of price — above this = high volatility
VOLATILITY_THRESHOLD = 0.02  # 2%

# Price move as % over lookback — above this = trending
TREND_THRESHOLD = 0.03  # 3%


# ---------------------------------------------------------------------------
# ATR computation
# ---------------------------------------------------------------------------

def add_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.DataFrame:
    """Add Average True Range column to the DataFrame.

    True Range = max(high-low, |high-prev_close|, |low-prev_close|)
    ATR = smoothed average of True Range over `period` candles.

    Args:
        df: OHLCV DataFrame.
        period: ATR smoothing period.

    Returns:
        DataFrame with 'atr' column added.
    """
    prev_close = df["close"].shift(1)

    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - prev_close).abs()
    tr3 = (df["low"] - prev_close).abs()

    df["true_range"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["atr"] = df["true_range"].ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    return df


# ---------------------------------------------------------------------------
# Regime detection
# ---------------------------------------------------------------------------

def detect_regime(df: pd.DataFrame, lookback: int = LOOKBACK) -> dict:
    """Detect the current market regime.

    Combines ATR-based volatility measurement with directional
    price movement to classify the market.

    Args:
        df: OHLCV DataFrame with 'atr' column (call add_atr first).
        lookback: Number of candles to measure direction over.

    Returns:
        dict with:
            - regime: 'trending_up', 'trending_down', 'sideways', or 'high_volatility'
            - atr: current ATR value
            - atr_pct: ATR as percentage of current price
            - direction_pct: price change over lookback as percentage
            - details: human-readable summary
    """
    if len(df) < lookback + 1:
        return _result("sideways", 0.0, 0.0, 0.0, "Insufficient data.")

    current = df.iloc[-1]
    past = df.iloc[-lookback]
    price = current["close"]

    # Volatility: ATR as % of price
    atr = current["atr"] if "atr" in df.columns and pd.notna(current.get("atr")) else 0.0
    atr_pct = atr / price if price > 0 else 0.0

    # Direction: price change over lookback window
    direction_pct = (price - past["close"]) / past["close"] if past["close"] > 0 else 0.0

    # Classification
    is_volatile = atr_pct > VOLATILITY_THRESHOLD
    is_trending_up = direction_pct > TREND_THRESHOLD
    is_trending_down = direction_pct < -TREND_THRESHOLD

    if is_volatile and not (is_trending_up or is_trending_down):
        regime = "high_volatility"
        details = f"High volatility (ATR {atr_pct:.2%}) with no clear direction ({direction_pct:+.2%})."

    elif is_trending_up:
        regime = "trending_up"
        details = f"Uptrend ({direction_pct:+.2%} over {lookback} candles), ATR {atr_pct:.2%}."

    elif is_trending_down:
        regime = "trending_down"
        details = f"Downtrend ({direction_pct:+.2%} over {lookback} candles), ATR {atr_pct:.2%}."

    else:
        regime = "sideways"
        details = f"Sideways ({direction_pct:+.2%}), low volatility (ATR {atr_pct:.2%})."

    return _result(regime, atr, atr_pct, direction_pct, details)


def _result(regime: str, atr: float, atr_pct: float, direction_pct: float, details: str) -> dict:
    """Build a regime result dict.

    Args:
        regime: Regime label.
        atr: Raw ATR value.
        atr_pct: ATR as percentage of price.
        direction_pct: Price direction over lookback.
        details: Human-readable summary.

    Returns:
        Regime result dict.
    """
    return {
        "regime": regime,
        "atr": round(atr, 2),
        "atr_pct": round(atr_pct, 6),
        "direction_pct": round(direction_pct, 6),
        "details": details,
    }


def get_regime_label(df: pd.DataFrame) -> str:
    """Convenience function: return just the regime string.

    Adds ATR if not present, then detects the regime.

    Args:
        df: OHLCV DataFrame (atr column added automatically if missing).

    Returns:
        One of: 'trending_up', 'trending_down', 'sideways', 'high_volatility'.
    """
    if "atr" not in df.columns:
        df = add_atr(df)

    return detect_regime(df)["regime"]
