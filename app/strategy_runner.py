"""
strategy_runner.py - Multi-configuration backtesting.

Runs backtests across multiple EMA/RSI parameter combinations,
stores results, and ranks strategies by P&L, drawdown, and consistency.

Usage:
    python app/strategy_runner.py
"""

from __future__ import annotations

import pandas as pd

from data_fetcher import fetch_historical_cached
from indicators import add_rsi
from backtester import run_backtest, TOTAL_CANDLES

# ---------------------------------------------------------------------------
# Strategy configurations to test
# ---------------------------------------------------------------------------

CONFIGS = [
    {"name": "EMA 9/21  RSI 30/70",  "ema_fast": 9,  "ema_slow": 21, "rsi_buy": 30, "rsi_sell": 70},
    {"name": "EMA 9/21  RSI 25/75",  "ema_fast": 9,  "ema_slow": 21, "rsi_buy": 25, "rsi_sell": 75},
    {"name": "EMA 12/26 RSI 30/70",  "ema_fast": 12, "ema_slow": 26, "rsi_buy": 30, "rsi_sell": 70},
    {"name": "EMA 12/26 RSI 25/75",  "ema_fast": 12, "ema_slow": 26, "rsi_buy": 25, "rsi_sell": 75},
    {"name": "EMA 5/13  RSI 30/70",  "ema_fast": 5,  "ema_slow": 13, "rsi_buy": 30, "rsi_sell": 70},
    {"name": "EMA 5/13  RSI 20/80",  "ema_fast": 5,  "ema_slow": 13, "rsi_buy": 20, "rsi_sell": 80},
    {"name": "EMA 8/21  RSI 35/65",  "ema_fast": 8,  "ema_slow": 21, "rsi_buy": 35, "rsi_sell": 65},
    {"name": "EMA 10/30 RSI 30/70",  "ema_fast": 10, "ema_slow": 30, "rsi_buy": 30, "rsi_sell": 70},
]


# ---------------------------------------------------------------------------
# Indicator preparation
# ---------------------------------------------------------------------------

def prepare_data(df: pd.DataFrame, ema_fast: int, ema_slow: int) -> pd.DataFrame:
    """Add EMA and RSI columns for a specific configuration.

    Creates columns named 'ema_{fast}' and 'ema_{slow}' so multiple
    configs can coexist on the same DataFrame.

    Args:
        df: Raw OHLCV DataFrame.
        ema_fast: Fast EMA period.
        ema_slow: Slow EMA period.

    Returns:
        DataFrame with the EMA columns and 'rsi' added.
    """
    fast_col = f"ema_{ema_fast}"
    slow_col = f"ema_{ema_slow}"

    if fast_col not in df.columns:
        df[fast_col] = df["close"].ewm(span=ema_fast, adjust=False).mean()
    if slow_col not in df.columns:
        df[slow_col] = df["close"].ewm(span=ema_slow, adjust=False).mean()
    if "rsi" not in df.columns:
        df = add_rsi(df)

    return df


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_all(df_raw: pd.DataFrame, configs: list[dict] = None) -> list[dict]:
    """Run backtests for all configurations.

    Args:
        df_raw: Raw OHLCV DataFrame (indicators will be added per config).
        configs: List of config dicts. Defaults to CONFIGS.

    Returns:
        List of result dicts, each containing 'config' and 'metrics'.
    """
    if configs is None:
        configs = CONFIGS

    df = df_raw.copy()
    results = []

    for cfg in configs:
        name = cfg["name"]
        ema_fast = cfg["ema_fast"]
        ema_slow = cfg["ema_slow"]

        print(f"  Running: {name} ...", end=" ")

        df = prepare_data(df, ema_fast, ema_slow)

        backtest_cfg = {
            "ema_col_fast": f"ema_{ema_fast}",
            "ema_col_slow": f"ema_{ema_slow}",
            "rsi_buy": cfg["rsi_buy"],
            "rsi_sell": cfg["rsi_sell"],
        }

        bt = run_backtest(df, config=backtest_cfg)
        m = bt["metrics"]

        print(f"trades={m['total_trades']:>3}  "
              f"pnl=${m['total_pnl']:>8.4f}  "
              f"wr={m['win_rate']:>5.1f}%  "
              f"dd=${m['max_drawdown']:>.4f}")

        results.append({
            "config": cfg,
            "metrics": m,
        })

    return results


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

def rank_strategies(results: list[dict]) -> pd.DataFrame:
    """Rank strategies by P&L, drawdown, and consistency.

    Scoring:
    - pnl_rank: higher P&L is better (ascending rank)
    - dd_rank: lower drawdown is better (ascending rank)
    - consistency_rank: higher win rate with more trades is better

    Final score = average of all three ranks (lower is better).

    Args:
        results: Output from run_all().

    Returns:
        DataFrame sorted by final score, best strategy first.
    """
    rows = []
    for r in results:
        m = r["metrics"]
        rows.append({
            "strategy": r["config"]["name"],
            "ema_fast": r["config"]["ema_fast"],
            "ema_slow": r["config"]["ema_slow"],
            "rsi_buy": r["config"]["rsi_buy"],
            "rsi_sell": r["config"]["rsi_sell"],
            "total_pnl": m["total_pnl"],
            "return_pct": m["return_pct"],
            "max_drawdown": m["max_drawdown"],
            "win_rate": m["win_rate"],
            "total_trades": m["total_trades"],
        })

    df = pd.DataFrame(rows)

    if df.empty:
        return df

    # Rank each metric (1 = best)
    df["pnl_rank"] = df["total_pnl"].rank(ascending=False)
    df["dd_rank"] = df["max_drawdown"].rank(ascending=True)

    # Consistency = win_rate weighted by trade count (avoid rewarding 100% on 1 trade)
    df["consistency"] = df["win_rate"] * df["total_trades"].clip(lower=1).apply(lambda x: min(x, 20) / 20)
    df["consistency_rank"] = df["consistency"].rank(ascending=False)

    df["score"] = (df["pnl_rank"] + df["dd_rank"] + df["consistency_rank"]) / 3
    df = df.sort_values("score").reset_index(drop=True)
    df.index += 1  # 1-based rank

    return df


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_rankings(df: pd.DataFrame) -> None:
    """Print the strategy ranking table.

    Args:
        df: Ranked DataFrame from rank_strategies().
    """
    if df.empty:
        print("No results to rank.")
        return

    print("\n" + "=" * 80)
    print("  Strategy Rankings (best first)")
    print("=" * 80)

    display_cols = [
        "strategy", "total_pnl", "return_pct",
        "max_drawdown", "win_rate", "total_trades", "score",
    ]
    print(df[display_cols].to_string(
        index=True,
        float_format=lambda x: f"{x:.4f}",
    ))
    print("=" * 80)

    best = df.iloc[0]
    print(f"\n  Best strategy: {best['strategy']}")
    print(f"  Return: {best['return_pct']:+.4f}%  |  "
          f"Win rate: {best['win_rate']:.1f}%  |  "
          f"Max DD: ${best['max_drawdown']:.4f}  |  "
          f"Score: {best['score']:.2f}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Fetch data, run all strategies, and print rankings."""
    df = fetch_historical_cached(total=TOTAL_CANDLES)
    print(f"Dataset: {len(df)} candles\n")

    print("Running strategy sweep...")
    results = run_all(df)

    rankings = rank_strategies(results)
    print_rankings(rankings)


if __name__ == "__main__":
    main()
