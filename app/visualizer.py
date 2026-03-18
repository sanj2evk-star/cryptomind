"""
visualizer.py - Strategy performance visualization.

Generates charts comparing strategy performance across
different EMA settings and RSI thresholds. Saves as PNG.

Usage:
    from visualizer import plot_all
    plot_all(results)           # generates all charts
    plot_all(results, show=True) # also opens matplotlib window
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # non-interactive backend for saving
import matplotlib.pyplot as plt
import pandas as pd

from config import DATA_DIR

OUTPUT_DIR = DATA_DIR / "charts"


def _ensure_output_dir() -> None:
    """Create the charts output directory if needed."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _results_to_df(results: list[dict]) -> pd.DataFrame:
    """Convert strategy results to a flat DataFrame.

    Args:
        results: List of dicts with 'config' and 'metrics' keys.

    Returns:
        DataFrame with one row per strategy.
    """
    rows = []
    for r in results:
        c = r["config"]
        m = r["metrics"]
        rows.append({
            "name": c["name"],
            "ema_fast": c["ema_fast"],
            "ema_slow": c["ema_slow"],
            "ema_pair": f"{c['ema_fast']}/{c['ema_slow']}",
            "rsi_buy": c["rsi_buy"],
            "rsi_sell": c["rsi_sell"],
            "rsi_range": f"{c['rsi_buy']}/{c['rsi_sell']}",
            "return_pct": m.get("return_pct", 0.0),
            "total_pnl": m.get("total_pnl", 0.0),
            "win_rate": m.get("win_rate", 0.0),
            "max_drawdown": m.get("max_drawdown", 0.0),
            "total_trades": m.get("total_trades", 0),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def plot_ema_performance(df: pd.DataFrame, save: bool = True, show: bool = False) -> Path:
    """Bar chart: return % grouped by EMA pair.

    Args:
        df: Strategy DataFrame from _results_to_df().
        save: Save to disk.
        show: Display matplotlib window.

    Returns:
        Path to saved image.
    """
    grouped = df.groupby("ema_pair").agg(
        avg_return=("return_pct", "mean"),
        avg_drawdown=("max_drawdown", "mean"),
        avg_winrate=("win_rate", "mean"),
    ).reset_index().sort_values("avg_return", ascending=False)

    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    fig.suptitle("Performance by EMA Settings", fontsize=14, fontweight="bold")

    # Return %
    colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in grouped["avg_return"]]
    axes[0].barh(grouped["ema_pair"], grouped["avg_return"], color=colors)
    axes[0].set_xlabel("Avg Return %")
    axes[0].set_title("Return")
    axes[0].invert_yaxis()

    # Max Drawdown
    axes[1].barh(grouped["ema_pair"], grouped["avg_drawdown"], color="#e67e22")
    axes[1].set_xlabel("Avg Max Drawdown ($)")
    axes[1].set_title("Drawdown")
    axes[1].invert_yaxis()

    # Win Rate
    axes[2].barh(grouped["ema_pair"], grouped["avg_winrate"], color="#3498db")
    axes[2].set_xlabel("Avg Win Rate %")
    axes[2].set_title("Win Rate")
    axes[2].invert_yaxis()

    plt.tight_layout()

    path = OUTPUT_DIR / "ema_performance.png"
    if save:
        _ensure_output_dir()
        fig.savefig(path, dpi=150, bbox_inches="tight")

    if show:
        plt.show()
    else:
        plt.close(fig)

    return path


def plot_rsi_performance(df: pd.DataFrame, save: bool = True, show: bool = False) -> Path:
    """Bar chart: return % grouped by RSI threshold range.

    Args:
        df: Strategy DataFrame from _results_to_df().
        save: Save to disk.
        show: Display matplotlib window.

    Returns:
        Path to saved image.
    """
    grouped = df.groupby("rsi_range").agg(
        avg_return=("return_pct", "mean"),
        avg_drawdown=("max_drawdown", "mean"),
        avg_winrate=("win_rate", "mean"),
    ).reset_index().sort_values("avg_return", ascending=False)

    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    fig.suptitle("Performance by RSI Thresholds", fontsize=14, fontweight="bold")

    # Return %
    colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in grouped["avg_return"]]
    axes[0].barh(grouped["rsi_range"], grouped["avg_return"], color=colors)
    axes[0].set_xlabel("Avg Return %")
    axes[0].set_title("Return")
    axes[0].invert_yaxis()

    # Max Drawdown
    axes[1].barh(grouped["rsi_range"], grouped["avg_drawdown"], color="#e67e22")
    axes[1].set_xlabel("Avg Max Drawdown ($)")
    axes[1].set_title("Drawdown")
    axes[1].invert_yaxis()

    # Win Rate
    axes[2].barh(grouped["rsi_range"], grouped["avg_winrate"], color="#3498db")
    axes[2].set_xlabel("Avg Win Rate %")
    axes[2].set_title("Win Rate")
    axes[2].invert_yaxis()

    plt.tight_layout()

    path = OUTPUT_DIR / "rsi_performance.png"
    if save:
        _ensure_output_dir()
        fig.savefig(path, dpi=150, bbox_inches="tight")

    if show:
        plt.show()
    else:
        plt.close(fig)

    return path


def plot_strategy_comparison(df: pd.DataFrame, save: bool = True, show: bool = False) -> Path:
    """Scatter plot: return % vs max drawdown per strategy.

    Bubble size = number of trades. Color = win rate.

    Args:
        df: Strategy DataFrame from _results_to_df().
        save: Save to disk.
        show: Display matplotlib window.

    Returns:
        Path to saved image.
    """
    fig, ax = plt.subplots(figsize=(10, 6))
    fig.suptitle("Strategy Comparison: Return vs Drawdown", fontsize=14, fontweight="bold")

    sizes = (df["total_trades"].clip(lower=1) * 50).tolist()
    scatter = ax.scatter(
        df["max_drawdown"],
        df["return_pct"],
        s=sizes,
        c=df["win_rate"],
        cmap="RdYlGn",
        vmin=0,
        vmax=100,
        edgecolors="black",
        linewidths=0.5,
        alpha=0.8,
    )

    for _, row in df.iterrows():
        ax.annotate(
            row["name"],
            (row["max_drawdown"], row["return_pct"]),
            fontsize=7,
            ha="left",
            va="bottom",
        )

    ax.set_xlabel("Max Drawdown ($)")
    ax.set_ylabel("Return %")
    ax.axhline(y=0, color="gray", linestyle="--", linewidth=0.5)
    plt.colorbar(scatter, label="Win Rate %")

    plt.tight_layout()

    path = OUTPUT_DIR / "strategy_comparison.png"
    if save:
        _ensure_output_dir()
        fig.savefig(path, dpi=150, bbox_inches="tight")

    if show:
        plt.show()
    else:
        plt.close(fig)

    return path


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def plot_all(results: list[dict], show: bool = False) -> list[Path]:
    """Generate all visualization charts.

    Args:
        results: List of dicts with 'config' and 'metrics' keys.
        show: Display charts interactively.

    Returns:
        List of paths to saved PNG files.
    """
    df = _results_to_df(results)

    if df.empty:
        print("No results to visualize.")
        return []

    paths = [
        plot_ema_performance(df, show=show),
        plot_rsi_performance(df, show=show),
        plot_strategy_comparison(df, show=show),
    ]

    for p in paths:
        print(f"  Saved: {p}")

    return paths
