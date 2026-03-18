"""
optimizer.py - Evolutionary strategy optimizer with walk-forward validation.

Generates random strategy configurations, backtests them,
keeps the top performers, mutates their parameters, and
repeats for multiple generations.

Anti-overfitting:
- Walk-forward validation: train on one window, validate on another.
- Only strategies that perform well on BOTH windows survive.
- Periodic re-optimization replaces weak strategies automatically.

Usage:
    python app/optimizer.py
"""

from __future__ import annotations

import random

import pandas as pd

from data_fetcher import fetch_historical_cached
from indicators import add_rsi
from backtester import run_backtest, TOTAL_CANDLES

# ---------------------------------------------------------------------------
# Optimizer settings
# ---------------------------------------------------------------------------

POPULATION_SIZE = 12
TOP_K = 4
GENERATIONS = 5

# Walk-forward validation split
TRAIN_RATIO = 0.65    # 65% train
VALIDATE_RATIO = 0.35  # 35% validate

# Overfit detection: if train fitness >> validate fitness, penalize
OVERFIT_THRESHOLD = 2.0  # train/validate ratio above this = likely overfit
OVERFIT_PENALTY = 0.5    # multiply fitness by this

# Minimum fitness to keep in strategy store
MIN_FITNESS_TO_KEEP = -5.0

# Parameter bounds
EMA_FAST_RANGE = (3, 15)
EMA_SLOW_RANGE = (15, 50)
RSI_BUY_RANGE = (15, 40)
RSI_SELL_RANGE = (60, 85)


# ---------------------------------------------------------------------------
# Parameter generation
# ---------------------------------------------------------------------------

def random_config() -> dict:
    """Generate a random strategy configuration within bounds."""
    ema_fast = random.randint(*EMA_FAST_RANGE)
    ema_slow = random.randint(max(EMA_SLOW_RANGE[0], ema_fast + 3), EMA_SLOW_RANGE[1])
    rsi_buy = random.randint(*RSI_BUY_RANGE)
    rsi_sell = random.randint(max(RSI_SELL_RANGE[0], rsi_buy + 25), RSI_SELL_RANGE[1])
    return _label(ema_fast, ema_slow, rsi_buy, rsi_sell)


def _label(ema_fast: int, ema_slow: int, rsi_buy: int, rsi_sell: int) -> dict:
    """Create a labeled config dict."""
    return {
        "name": f"EMA {ema_fast}/{ema_slow} RSI {rsi_buy}/{rsi_sell}",
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "rsi_buy": rsi_buy,
        "rsi_sell": rsi_sell,
    }


def mutate(config: dict) -> dict:
    """Create a mutated copy of a strategy config."""
    def nudge(val: int, low: int, high: int, step: int = 2) -> int:
        return max(low, min(high, val + random.randint(-step, step)))

    ema_fast = nudge(config["ema_fast"], *EMA_FAST_RANGE)
    ema_slow = nudge(config["ema_slow"], *EMA_SLOW_RANGE)
    rsi_buy = nudge(config["rsi_buy"], *RSI_BUY_RANGE)
    rsi_sell = nudge(config["rsi_sell"], *RSI_SELL_RANGE)

    if ema_slow <= ema_fast + 2:
        ema_slow = ema_fast + 3
    if rsi_sell <= rsi_buy + 20:
        rsi_sell = rsi_buy + 25

    return _label(ema_fast, ema_slow, rsi_buy, rsi_sell)


def generate_initial_population(size: int = POPULATION_SIZE) -> list[dict]:
    """Generate a diverse initial population of configs."""
    population = []
    seen = set()
    while len(population) < size:
        cfg = random_config()
        key = (cfg["ema_fast"], cfg["ema_slow"], cfg["rsi_buy"], cfg["rsi_sell"])
        if key not in seen:
            seen.add(key)
            population.append(cfg)
    return population


# ---------------------------------------------------------------------------
# Data splitting
# ---------------------------------------------------------------------------

def split_data(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split data into train and validation windows.

    Args:
        df: Full OHLCV DataFrame.

    Returns:
        (train_df, validate_df) tuple.
    """
    split_idx = int(len(df) * TRAIN_RATIO)
    return df.iloc[:split_idx].copy(), df.iloc[split_idx:].copy()


# ---------------------------------------------------------------------------
# Fitness evaluation
# ---------------------------------------------------------------------------

def _prepare_indicators(df: pd.DataFrame, ema_fast: int, ema_slow: int) -> pd.DataFrame:
    """Add EMA columns if not already present."""
    fast_col = f"ema_{ema_fast}"
    slow_col = f"ema_{ema_slow}"
    if fast_col not in df.columns:
        df[fast_col] = df["close"].ewm(span=ema_fast, adjust=False).mean()
    if slow_col not in df.columns:
        df[slow_col] = df["close"].ewm(span=ema_slow, adjust=False).mean()
    return df


def evaluate(df: pd.DataFrame, config: dict) -> dict:
    """Run a backtest for one config and return metrics."""
    df = _prepare_indicators(df, config["ema_fast"], config["ema_slow"])
    bt_config = {
        "ema_col_fast": f"ema_{config['ema_fast']}",
        "ema_col_slow": f"ema_{config['ema_slow']}",
        "rsi_buy": config["rsi_buy"],
        "rsi_sell": config["rsi_sell"],
    }
    result = run_backtest(df, config=bt_config)
    return result["metrics"]


def fitness_score(metrics: dict) -> float:
    """Compute a single fitness score from backtest metrics."""
    ret = metrics["return_pct"]
    dd = (metrics["max_drawdown"] / max(metrics["initial_balance"], 1)) * 100
    wr = metrics["win_rate"]
    trades = metrics["total_trades"]
    trade_factor = min(trades, 20) / 20
    return ret - (dd * 2) + (wr * 0.1 * trade_factor)


def evaluate_validated(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    config: dict,
) -> dict:
    """Evaluate a config on both train and validation windows.

    Penalizes strategies that overfit (perform much better on
    train than validation).

    Args:
        train_df: Training data window.
        val_df: Validation data window.
        config: Strategy config dict.

    Returns:
        dict with train_fitness, val_fitness, combined_fitness, overfit flag.
    """
    train_metrics = evaluate(train_df, config)
    val_metrics = evaluate(val_df, config)

    train_fit = fitness_score(train_metrics)
    val_fit = fitness_score(val_metrics)

    # Detect overfitting
    overfit = False
    if val_fit != 0:
        ratio = abs(train_fit / val_fit) if val_fit != 0 else float("inf")
        if train_fit > 0 and val_fit < 0:
            overfit = True
        elif ratio > OVERFIT_THRESHOLD and train_fit > val_fit:
            overfit = True

    # Combined fitness: average of both, penalized if overfit
    combined = (train_fit + val_fit) / 2
    if overfit:
        combined *= OVERFIT_PENALTY

    return {
        "train_metrics": train_metrics,
        "val_metrics": val_metrics,
        "train_fitness": round(train_fit, 4),
        "val_fitness": round(val_fit, 4),
        "combined_fitness": round(combined, 4),
        "overfit": overfit,
    }


# ---------------------------------------------------------------------------
# Evolution loop
# ---------------------------------------------------------------------------

def evolve(
    df: pd.DataFrame,
    generations: int = GENERATIONS,
    population_size: int = POPULATION_SIZE,
    top_k: int = TOP_K,
    seed: int = None,
    validate: bool = True,
) -> list[dict]:
    """Run the evolutionary optimization loop.

    Args:
        df: OHLCV DataFrame with RSI column.
        generations: Number of generations to run.
        population_size: Configs per generation.
        top_k: Number of top performers to keep.
        seed: Optional random seed for reproducibility.
        validate: Use walk-forward validation (default True).

    Returns:
        List of all evaluated configs with metrics, sorted by fitness.
    """
    if seed is not None:
        random.seed(seed)

    if validate:
        train_df, val_df = split_data(df)
        print(f"  Walk-forward: train={len(train_df)} val={len(val_df)} candles")
    else:
        train_df = df
        val_df = None

    all_results = []
    population = generate_initial_population(population_size)

    for gen in range(1, generations + 1):
        print(f"\n--- Generation {gen}/{generations} ({len(population)} configs) ---")

        gen_results = []
        for cfg in population:
            if validate and val_df is not None:
                ev = evaluate_validated(train_df, val_df, cfg)
                score = ev["combined_fitness"]
                metrics = ev["val_metrics"]  # report validation metrics
                overfit = ev["overfit"]
            else:
                metrics = evaluate(train_df, cfg)
                score = fitness_score(metrics)
                ev = {"train_fitness": score, "val_fitness": score, "overfit": False}
                overfit = False

            gen_results.append({
                "config": cfg,
                "metrics": metrics,
                "fitness": round(score, 4),
                "train_fitness": ev["train_fitness"],
                "val_fitness": ev.get("val_fitness", score),
                "overfit": overfit,
            })

        gen_results.sort(key=lambda x: x["fitness"], reverse=True)
        all_results.extend(gen_results)

        for i, r in enumerate(gen_results[:5], 1):
            m = r["metrics"]
            of = " OVERFIT" if r["overfit"] else ""
            print(f"  #{i} {r['config']['name']:25s}  "
                  f"fit={r['fitness']:>8.4f}  "
                  f"train={r['train_fitness']:>7.4f}  "
                  f"val={r['val_fitness']:>7.4f}  "
                  f"trades={m['total_trades']}{of}")

        survivors = [r["config"] for r in gen_results[:top_k] if not r["overfit"]]
        if not survivors:
            survivors = [gen_results[0]["config"]]

        next_gen = list(survivors)
        seen = {(c["ema_fast"], c["ema_slow"], c["rsi_buy"], c["rsi_sell"]) for c in next_gen}

        while len(next_gen) < population_size:
            parent = random.choice(survivors)
            child = mutate(parent)
            key = (child["ema_fast"], child["ema_slow"], child["rsi_buy"], child["rsi_sell"])
            if key not in seen:
                seen.add(key)
                next_gen.append(child)

        population = next_gen

    best_by_config = {}
    for r in all_results:
        key = r["config"]["name"]
        if key not in best_by_config or r["fitness"] > best_by_config[key]["fitness"]:
            best_by_config[key] = r

    final = sorted(best_by_config.values(), key=lambda x: x["fitness"], reverse=True)
    return final


# ---------------------------------------------------------------------------
# Strategy store integration
# ---------------------------------------------------------------------------

def refresh_strategies(results: list[dict], n: int = 10) -> dict:
    """Update the strategy store: keep top performers, replace weak ones.

    Args:
        results: Sorted output from evolve().
        n: Max strategies to keep.

    Returns:
        dict with kept, replaced, removed counts.
    """
    from strategy_store import load_strategies, save_strategy, remove_strategy

    existing = load_strategies()
    existing_names = {s["name"] for s in existing}

    kept = 0
    replaced = 0

    # Save top N from new optimization
    for r in results[:n]:
        if r.get("overfit"):
            continue
        save_strategy(r["config"], r["metrics"], r["fitness"])
        if r["config"]["name"] in existing_names:
            replaced += 1
        else:
            kept += 1

    # Remove strategies below minimum fitness
    removed = 0
    for s in existing:
        if s.get("fitness", 0) < MIN_FITNESS_TO_KEEP:
            remove_strategy(s["name"])
            removed += 1

    return {"kept": kept, "replaced": replaced, "removed": removed}


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_top_results(results: list[dict], n: int = 10) -> None:
    """Print the top N optimized strategies."""
    print("\n" + "=" * 90)
    print(f"  Top {min(n, len(results))} Optimized Strategies")
    print("=" * 90)

    rows = []
    for r in results[:n]:
        c = r["config"]
        m = r["metrics"]
        rows.append({
            "strategy": c["name"],
            "fitness": r["fitness"],
            "train": r.get("train_fitness", r["fitness"]),
            "val": r.get("val_fitness", r["fitness"]),
            "overfit": r.get("overfit", False),
            "return_pct": m["return_pct"],
            "win_rate": m["win_rate"],
            "trades": m["total_trades"],
        })

    table = pd.DataFrame(rows)
    table.index += 1
    print(table.to_string(float_format=lambda x: f"{x:.4f}"))
    print("=" * 90)

    if results:
        best = results[0]
        c = best["config"]
        print(f"\n  Best: {c['name']}")
        print(f"  Fitness={best['fitness']:.4f}  "
              f"(train={best.get('train_fitness', '?')}  "
              f"val={best.get('val_fitness', '?')})")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Fetch data, run validated optimization, refresh strategy store."""
    df = fetch_historical_cached(total=TOTAL_CANDLES)
    print(f"Dataset: {len(df)} candles")

    df = add_rsi(df)

    results = evolve(df, seed=42, validate=True)
    print_top_results(results)

    stats = refresh_strategies(results, n=10)
    print(f"Strategy store updated: "
          f"{stats['kept']} new, {stats['replaced']} updated, {stats['removed']} removed")


if __name__ == "__main__":
    main()
