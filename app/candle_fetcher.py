"""
candle_fetcher.py — Fetch BTC/USDT candle data from multiple sources.

Provides OHLCV data for charting. Falls back through multiple APIs:
1. Binance (blocked in some US regions)
2. CoinGecko (free, rate-limited)

Caches data to avoid excessive API calls.
"""

from __future__ import annotations

import json
import time
import math
from urllib.request import urlopen, Request
from urllib.error import URLError

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
_cache: dict[str, dict] = {}  # key → {"data": [...], "ts": timestamp}
CACHE_TTL = {
    "1m": 30,    # 30s cache
    "5m": 120,   # 2 min
    "15m": 300,  # 5 min
    "1h": 600,   # 10 min
    "6h": 1800,  # 30 min
    "12h": 3600, # 1 hour
    "1d": 3600,  # 1 hour
    "1w": 7200,  # 2 hours
    "1M": 14400, # 4 hours
    "3M": 14400,
    "6M": 14400,
}

# ---------------------------------------------------------------------------
# Binance intervals
# ---------------------------------------------------------------------------
BINANCE_INTERVALS = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
    "6h": "6h",
    "12h": "12h",
    "1d": "1d",
    "1w": "1w",
    "1M": "1M",
    "3M": "1M",   # Binance has no 3M — use 1M with more candles
    "6M": "1M",   # same approach
}

BINANCE_LIMITS = {
    "1m": 120,
    "5m": 100,
    "15m": 96,
    "1h": 168,
    "6h": 120,
    "12h": 120,
    "1d": 365,
    "1w": 104,
    "1M": 60,
    "3M": 60,
    "6M": 60,
}


def _fetch_json(url: str, timeout: int = 10) -> dict | list:
    """Fetch JSON from URL."""
    req = Request(url, headers={"User-Agent": "CryptoMind/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _fetch_binance(interval: str = "5m") -> list[dict]:
    """Fetch candles from Binance REST API."""
    bi = BINANCE_INTERVALS.get(interval, "5m")
    limit = BINANCE_LIMITS.get(interval, 100)
    url = f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval={bi}&limit={limit}"
    raw = _fetch_json(url)
    candles = []
    for k in raw:
        candles.append({
            "time": int(k[0] / 1000),  # Unix seconds
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
        })
    return candles


def _fetch_coingecko_line(interval: str = "5m") -> list[dict]:
    """
    Fetch price-only data from CoinGecko (no real candles).
    Returns synthetic candles from price history.
    """
    # Map intervals to CoinGecko days param
    days_map = {
        "1m": "1",     # 1 day at 5-min granularity
        "5m": "1",     # 1 day at 5-min granularity
        "15m": "7",    # 7 days, hourly
        "1h": "30",    # 30 days, hourly
        "6h": "90",    # 90 days
        "12h": "180",  # 180 days
        "1d": "365",   # 1 year
        "1w": "max",   # all history
        "1M": "max",
        "3M": "max",
        "6M": "max",
    }
    days = days_map.get(interval, "1")
    url = f"https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days={days}"
    data = _fetch_json(url, timeout=15)
    prices = data.get("prices", [])

    if not prices:
        return []

    # Convert to candle-like format
    # Group prices into interval buckets
    interval_seconds = {
        "1m": 60, "5m": 300, "15m": 900, "1h": 3600,
        "6h": 21600, "12h": 43200, "1d": 86400, "1w": 604800,
        "1M": 2592000, "3M": 7776000, "6M": 15552000,
    }
    bucket_size = interval_seconds.get(interval, 300)

    candles = []
    bucket_prices = []
    bucket_start = None

    for ts_ms, price in prices:
        ts = int(ts_ms / 1000)
        bucket = ts - (ts % bucket_size)

        if bucket_start is None:
            bucket_start = bucket

        if bucket != bucket_start:
            # Emit candle for completed bucket
            if bucket_prices:
                candles.append({
                    "time": bucket_start,
                    "open": bucket_prices[0],
                    "high": max(bucket_prices),
                    "low": min(bucket_prices),
                    "close": bucket_prices[-1],
                    "volume": 0,
                })
            bucket_prices = [price]
            bucket_start = bucket
        else:
            bucket_prices.append(price)

    # Last bucket
    if bucket_prices and bucket_start is not None:
        candles.append({
            "time": bucket_start,
            "open": bucket_prices[0],
            "high": max(bucket_prices),
            "low": min(bucket_prices),
            "close": bucket_prices[-1],
            "volume": 0,
        })

    return candles


def _fetch_coinbase(interval: str = "5m") -> list[dict]:
    """Fetch candles from Coinbase Pro (no auth needed)."""
    granularity_map = {
        "1m": 60, "5m": 300, "15m": 900, "1h": 3600,
        "6h": 21600, "12h": 43200, "1d": 86400,
    }
    gran = granularity_map.get(interval, 300)
    if interval in ("1w", "1M", "3M", "6M"):
        gran = 86400  # Coinbase max is daily
    url = f"https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity={gran}"
    raw = _fetch_json(url, timeout=15)
    # Coinbase returns [[time, low, high, open, close, volume], ...] newest first
    candles = []
    for k in reversed(raw):
        candles.append({
            "time": int(k[0]),
            "open": float(k[3]),
            "high": float(k[2]),
            "low": float(k[1]),
            "close": float(k[4]),
            "volume": float(k[5]),
        })
    return candles


def _generate_from_trader_history(interval: str = "5m") -> list[dict]:
    """Generate synthetic candles from auto_trader's in-memory price history."""
    try:
        import auto_trader
        state = auto_trader.trader_state
        history = state.get("price_history", [])
        timestamps = state.get("timestamp_history", [])
        if len(history) < 10:
            return []

        interval_seconds = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}
        bucket_size = interval_seconds.get(interval, 300)
        now = int(time.time())

        candles = []
        bucket_prices = []
        bucket_start = None

        for i, price in enumerate(history):
            # Estimate timestamp from position
            ts = now - (len(history) - i) * 30  # ~30s between readings
            bucket = ts - (ts % bucket_size)

            if bucket_start is None:
                bucket_start = bucket

            if bucket != bucket_start and bucket_prices:
                candles.append({
                    "time": bucket_start,
                    "open": bucket_prices[0],
                    "high": max(bucket_prices),
                    "low": min(bucket_prices),
                    "close": bucket_prices[-1],
                    "volume": 0,
                })
                bucket_prices = [price]
                bucket_start = bucket
            else:
                bucket_prices.append(price)

        if bucket_prices and bucket_start:
            candles.append({
                "time": bucket_start,
                "open": bucket_prices[0],
                "high": max(bucket_prices),
                "low": min(bucket_prices),
                "close": bucket_prices[-1],
                "volume": 0,
            })

        return candles if len(candles) >= 5 else []
    except Exception:
        return []


def _calc_ema(candles: list[dict], period: int) -> list[dict]:
    """Calculate EMA over candle closes. Returns list of {time, value}."""
    if len(candles) < period:
        return []

    mult = 2 / (period + 1)
    closes = [c["close"] for c in candles]

    # Seed: SMA of first `period` values
    sma = sum(closes[:period]) / period
    ema_vals = [None] * (period - 1) + [sma]

    for i in range(period, len(closes)):
        ema = (closes[i] - ema_vals[-1]) * mult + ema_vals[-1]
        ema_vals.append(round(ema, 2))

    result = []
    for i, val in enumerate(ema_vals):
        if val is not None:
            result.append({"time": candles[i]["time"], "value": val})
    return result


def fetch_candles(interval: str = "5m", with_ema: bool = True) -> dict:
    """
    Fetch BTC/USDT candles. Returns:
    {
        "candles": [...],
        "ema9": [...],
        "ema21": [...],
        "source": "binance" | "coingecko",
        "interval": "5m",
        "count": N,
    }
    """
    cache_key = f"{interval}_{with_ema}"
    ttl = CACHE_TTL.get(interval, 120)

    # Check cache
    if cache_key in _cache:
        cached = _cache[cache_key]
        if time.time() - cached["ts"] < ttl:
            return cached["data"]

    # Try sources in order
    candles = []
    source = "unknown"
    errors = []

    # 1. Binance
    try:
        candles = _fetch_binance(interval)
        source = "binance"
    except Exception as e:
        errors.append(f"binance: {e}")

    # 2. CoinGecko
    if not candles:
        try:
            candles = _fetch_coingecko_line(interval)
            source = "coingecko"
        except Exception as e:
            errors.append(f"coingecko: {e}")

    # 3. Coinbase (price history via candles endpoint)
    if not candles:
        try:
            candles = _fetch_coinbase(interval)
            source = "coinbase"
        except Exception as e:
            errors.append(f"coinbase: {e}")

    # 4. Generate synthetic candles from auto_trader price history
    if not candles:
        try:
            candles = _generate_from_trader_history(interval)
            source = "local"
        except Exception as e:
            errors.append(f"local: {e}")

    if not candles:
        return {"candles": [], "ema9": [], "ema21": [], "source": "none", "interval": interval, "count": 0, "errors": errors}

    result = {
        "candles": candles,
        "source": source,
        "interval": interval,
        "count": len(candles),
    }

    if with_ema:
        result["ema9"] = _calc_ema(candles, 9)
        result["ema21"] = _calc_ema(candles, 21)
    else:
        result["ema9"] = []
        result["ema21"] = []

    # Cache
    _cache[cache_key] = {"data": result, "ts": time.time()}
    return result
