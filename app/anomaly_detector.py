"""
anomaly_detector.py - Unusual market behavior detection.

Detects anomalies that should pause trading:
- Price spikes: single-candle move exceeding a threshold
- Extreme volatility: ATR far above its recent average
- Volume spikes: abnormal volume relative to recent average

Returns a boolean flag and details for each check.
All thresholds are configurable as module constants.

Usage:
    from anomaly_detector import check_anomalies
    result = check_anomalies(df)
    if result["is_anomaly"]:
        # pause trading
"""

from __future__ import annotations

import pandas as pd

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

# Price spike: single candle move > this % of close
PRICE_SPIKE_PCT = 0.04  # 4%

# Volume spike: current volume > this multiple of recent average
VOLUME_SPIKE_MULT = 5.0

# ATR spike: current ATR > this multiple of its rolling average
ATR_SPIKE_MULT = 2.5

# Lookback for computing rolling averages
ROLLING_WINDOW = 20


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_price_spike(df: pd.DataFrame) -> dict:
    """Detect if the latest candle has an abnormal price move.

    A spike is when |close - open| / close exceeds PRICE_SPIKE_PCT.

    Args:
        df: OHLCV DataFrame.

    Returns:
        dict with triggered (bool), value, threshold, detail.
    """
    if df.empty:
        return _result(False, 0.0, PRICE_SPIKE_PCT, "No data.")

    last = df.iloc[-1]
    move = abs(last["close"] - last["open"]) / last["close"]

    triggered = move > PRICE_SPIKE_PCT
    detail = f"Candle move {move:.2%} {'>' if triggered else '<='} {PRICE_SPIKE_PCT:.0%} threshold."

    return _result(triggered, round(move, 6), PRICE_SPIKE_PCT, detail)


def check_volume_spike(df: pd.DataFrame) -> dict:
    """Detect if the latest candle has abnormal volume.

    A spike is when current volume > VOLUME_SPIKE_MULT * rolling average.

    Args:
        df: OHLCV DataFrame.

    Returns:
        dict with triggered (bool), value, threshold, detail.
    """
    if len(df) < ROLLING_WINDOW + 1:
        return _result(False, 0.0, VOLUME_SPIKE_MULT, "Insufficient data for volume check.")

    avg_vol = df["volume"].iloc[-(ROLLING_WINDOW + 1):-1].mean()
    current_vol = df.iloc[-1]["volume"]

    if avg_vol == 0:
        return _result(False, 0.0, VOLUME_SPIKE_MULT, "Zero average volume.")

    ratio = current_vol / avg_vol
    triggered = ratio > VOLUME_SPIKE_MULT
    detail = f"Volume {ratio:.1f}x average {'>' if triggered else '<='} {VOLUME_SPIKE_MULT}x threshold."

    return _result(triggered, round(ratio, 4), VOLUME_SPIKE_MULT, detail)


def check_atr_spike(df: pd.DataFrame) -> dict:
    """Detect if current ATR is far above its recent average.

    A spike is when ATR > ATR_SPIKE_MULT * rolling ATR average.

    Args:
        df: OHLCV DataFrame with 'atr' column.

    Returns:
        dict with triggered (bool), value, threshold, detail.
    """
    if "atr" not in df.columns or len(df) < ROLLING_WINDOW + 1:
        return _result(False, 0.0, ATR_SPIKE_MULT, "No ATR data available.")

    avg_atr = df["atr"].iloc[-(ROLLING_WINDOW + 1):-1].mean()
    current_atr = df.iloc[-1]["atr"]

    if avg_atr == 0 or pd.isna(avg_atr):
        return _result(False, 0.0, ATR_SPIKE_MULT, "Zero average ATR.")

    ratio = current_atr / avg_atr
    triggered = ratio > ATR_SPIKE_MULT
    detail = f"ATR {ratio:.1f}x average {'>' if triggered else '<='} {ATR_SPIKE_MULT}x threshold."

    return _result(triggered, round(ratio, 4), ATR_SPIKE_MULT, detail)


# ---------------------------------------------------------------------------
# Combined check
# ---------------------------------------------------------------------------

def check_anomalies(df: pd.DataFrame) -> dict:
    """Run all anomaly checks and return a combined result.

    Trading should be paused if any check triggers.

    Args:
        df: OHLCV DataFrame (with optional 'atr' column).

    Returns:
        dict with:
            is_anomaly (bool): True if any check triggered.
            checks: dict of individual check results.
            reasons: list of triggered check descriptions.
    """
    checks = {
        "price_spike": check_price_spike(df),
        "volume_spike": check_volume_spike(df),
        "atr_spike": check_atr_spike(df),
    }

    reasons = [
        f"{name}: {c['detail']}"
        for name, c in checks.items()
        if c["triggered"]
    ]

    return {
        "is_anomaly": len(reasons) > 0,
        "checks": checks,
        "reasons": reasons,
    }


def is_anomaly(df: pd.DataFrame) -> bool:
    """Convenience function: return just the boolean flag.

    Args:
        df: OHLCV DataFrame.

    Returns:
        True if any anomaly detected.
    """
    return check_anomalies(df)["is_anomaly"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _result(triggered: bool, value: float, threshold: float, detail: str) -> dict:
    """Build a standardized check result dict."""
    return {
        "triggered": triggered,
        "value": value,
        "threshold": threshold,
        "detail": detail,
    }
