"""
data_fetcher.py - Market data retrieval.

Fetches OHLCV data from Binance via ccxt for any supported symbol.
Supports:
- Live data (recent candles, current price)
- Historical data (1000+ candles with pagination)
- CSV caching to avoid repeated API calls
- Multi-asset: pass symbol parameter (default BTC/USDT)
"""

import time
from pathlib import Path

import ccxt
import pandas as pd

from config import SYMBOL, TIMEFRAME, DATA_DIR

OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
CACHE_DIR = DATA_DIR / "cache"
BATCH_SIZE = 1000


def _create_exchange() -> ccxt.binance:
    """Create a Binance exchange client (public, no auth needed).

    Returns:
        Configured ccxt Binance instance.
    """
    return ccxt.binance({"enableRateLimit": True})


def _format_df(raw: list) -> pd.DataFrame:
    """Convert raw OHLCV list to a formatted DataFrame.

    Args:
        raw: List of [timestamp_ms, open, high, low, close, volume] lists.

    Returns:
        DataFrame with typed columns and UTC datetime timestamps.
    """
    df = pd.DataFrame(raw, columns=OHLCV_COLUMNS)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df


def _symbol_key(symbol: str) -> str:
    """Convert a symbol to a filesystem-safe key.

    Args:
        symbol: Trading pair (e.g. 'BTC/USDT').

    Returns:
        Lowercase key (e.g. 'btc_usdt').
    """
    return symbol.replace("/", "_").lower()


# ---------------------------------------------------------------------------
# Live data
# ---------------------------------------------------------------------------

def fetch_ohlcv(symbol: str = SYMBOL, limit: int = 100) -> pd.DataFrame:
    """Fetch recent OHLCV candles for a symbol.

    Args:
        symbol: Trading pair (default BTC/USDT).
        limit: Number of candles to fetch (default 100).

    Returns:
        DataFrame with columns: timestamp, open, high, low, close, volume.

    Raises:
        RuntimeError: If the API request fails.
    """
    try:
        exchange = _create_exchange()
        raw = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=limit)
    except ccxt.BaseError as e:
        raise RuntimeError(f"Failed to fetch OHLCV for {symbol}: {e}") from e

    return _format_df(raw)


def fetch_current_price(symbol: str = SYMBOL) -> float:
    """Fetch the latest price for a symbol.

    Args:
        symbol: Trading pair (default BTC/USDT).

    Returns:
        Current price as a float.

    Raises:
        RuntimeError: If the API request fails.
    """
    try:
        exchange = _create_exchange()
        ticker = exchange.fetch_ticker(symbol)
    except ccxt.BaseError as e:
        raise RuntimeError(f"Failed to fetch ticker for {symbol}: {e}") from e

    return float(ticker["last"])


# ---------------------------------------------------------------------------
# Historical data with pagination
# ---------------------------------------------------------------------------

def fetch_historical(symbol: str = SYMBOL, total: int = 4380) -> pd.DataFrame:
    """Fetch historical OHLCV data in batches from Binance.

    Args:
        symbol: Trading pair (default BTC/USDT).
        total: Total number of candles to fetch.

    Returns:
        DataFrame with columns: timestamp, open, high, low, close, volume.

    Raises:
        RuntimeError: If the API request fails.
    """
    try:
        exchange = _create_exchange()
        all_candles = []
        since = None

        while len(all_candles) < total:
            limit = min(BATCH_SIZE, total - len(all_candles))
            raw = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, since=since, limit=limit)

            if not raw:
                break

            all_candles.extend(raw)
            since = raw[-1][0] + 1
            time.sleep(exchange.rateLimit / 1000)

    except ccxt.BaseError as e:
        raise RuntimeError(f"Failed to fetch historical data for {symbol}: {e}") from e

    return _format_df(all_candles[:total])


# ---------------------------------------------------------------------------
# CSV caching
# ---------------------------------------------------------------------------

def _cache_path(label: str) -> Path:
    """Return the cache file path for a given label."""
    return CACHE_DIR / f"{label}.csv"


def save_to_csv(df: pd.DataFrame, label: str) -> Path:
    """Save a DataFrame to CSV in the cache directory.

    Args:
        df: OHLCV DataFrame to save.
        label: Descriptive name for the cache file.

    Returns:
        Path to the saved CSV file.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(label)
    df.to_csv(path, index=False)
    return path


def load_from_csv(label: str) -> pd.DataFrame:
    """Load a cached OHLCV DataFrame from CSV.

    Args:
        label: Name used when saving.

    Returns:
        DataFrame with parsed timestamps and typed columns.

    Raises:
        FileNotFoundError: If the cache file doesn't exist.
    """
    path = _cache_path(label)
    if not path.exists():
        raise FileNotFoundError(f"Cache file not found: {path}")

    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df


def fetch_historical_cached(symbol: str = SYMBOL, total: int = 4380, label: str = None) -> pd.DataFrame:
    """Fetch historical data, using CSV cache to avoid repeated API calls.

    Args:
        symbol: Trading pair (default BTC/USDT).
        total: Number of candles needed.
        label: Cache label (default: '{symbol_key}_historical_{total}').

    Returns:
        DataFrame with columns: timestamp, open, high, low, close, volume.
    """
    if label is None:
        label = f"{_symbol_key(symbol)}_historical_{total}"

    try:
        df = load_from_csv(label)
        if len(df) >= total:
            print(f"Loaded {len(df)} {symbol} candles from cache")
            return df.tail(total).reset_index(drop=True)
        print(f"Cache has {len(df)} candles but need {total}, refetching...")
    except FileNotFoundError:
        pass

    print(f"Fetching {total} {symbol} candles from Binance...")
    df = fetch_historical(symbol=symbol, total=total)
    save_to_csv(df, label)
    print(f"Saved {len(df)} {symbol} candles to cache")
    return df
