"""
strategy_store.py - Persistent strategy storage with performance tracking.

Saves and loads optimized strategies to/from data/strategies.json.
Tracks long-term performance, win rate over time, and regime-specific
success rates. Uses a composite score to prioritize strategies.

Enhanced schema per strategy:
    - parameters: EMA/RSI config
    - metrics: latest backtest results
    - fitness: optimizer fitness score
    - history: list of recorded outcomes over time
    - regime_stats: win/loss counts per regime
    - live_score: composite ranking from all tracked data
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from config import DATA_DIR

STRATEGIES_FILE = DATA_DIR / "strategies.json"

# Weights for the composite live_score
FITNESS_WEIGHT = 0.30
WIN_RATE_WEIGHT = 0.25
REGIME_WEIGHT = 0.25
CONSISTENCY_WEIGHT = 0.20


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

def _load_file() -> list[dict]:
    """Load the raw strategies list from disk."""
    try:
        return json.loads(STRATEGIES_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_file(strategies: list[dict]) -> None:
    """Write the strategies list to disk."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STRATEGIES_FILE.write_text(
        json.dumps(strategies, indent=2) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Save / update
# ---------------------------------------------------------------------------

def save_strategy(config: dict, metrics: dict, fitness: float) -> None:
    """Save a single strategy to the store.

    Deduplicates by parameter key — if the same params exist,
    updates metrics and fitness only if the new fitness is higher.
    Preserves history and regime_stats across updates.

    Args:
        config: Strategy config dict (ema_fast, ema_slow, rsi_buy, rsi_sell).
        metrics: Backtest metrics dict.
        fitness: Computed fitness score.
    """
    strategies = _load_file()
    key = _param_key(config)

    entry = _build_entry(config, metrics, fitness)

    for i, s in enumerate(strategies):
        if _param_key_from_entry(s) == key:
            if fitness > s.get("fitness", float("-inf")):
                # Preserve tracked data
                entry["history"] = s.get("history", [])
                entry["regime_stats"] = s.get("regime_stats", {})
                entry["live_score"] = compute_live_score(entry)
                strategies[i] = entry
            _save_file(_sort(strategies))
            return

    entry["live_score"] = compute_live_score(entry)
    strategies.append(entry)
    _save_file(_sort(strategies))


def save_top_strategies(results: list[dict], n: int = 10) -> int:
    """Save the top N strategies from an optimizer run.

    Args:
        results: Sorted output from optimizer.evolve() or strategy_runner.
        n: Max number of strategies to save.

    Returns:
        Number of strategies saved or updated.
    """
    count = 0
    for r in results[:n]:
        save_strategy(r["config"], r["metrics"], r["fitness"])
        count += 1
    return count


# ---------------------------------------------------------------------------
# Performance tracking
# ---------------------------------------------------------------------------

def record_outcome(name: str, pnl: float, regime: str, win: bool) -> None:
    """Record a live trade outcome for a strategy.

    Appends to the strategy's history and updates regime_stats.

    Args:
        name: Strategy name.
        pnl: Realized P&L from this trade.
        regime: Market regime during the trade.
        win: Whether the trade was profitable.
    """
    strategies = _load_file()

    for s in strategies:
        if s.get("name") != name:
            continue

        # Append to history (keep last 100)
        history = s.get("history", [])
        history.append({
            "pnl": round(pnl, 6),
            "regime": regime,
            "win": win,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if len(history) > 100:
            history = history[-100:]
        s["history"] = history

        # Update regime stats
        regime_stats = s.get("regime_stats", {})
        if regime not in regime_stats:
            regime_stats[regime] = {"wins": 0, "losses": 0, "total_pnl": 0.0}

        rs = regime_stats[regime]
        if win:
            rs["wins"] += 1
        else:
            rs["losses"] += 1
        rs["total_pnl"] = round(rs["total_pnl"] + pnl, 6)
        s["regime_stats"] = regime_stats

        # Recompute live score
        s["live_score"] = compute_live_score(s)
        s["updated_at"] = datetime.now(timezone.utc).isoformat()

        _save_file(_sort(strategies))
        return


def get_history(name: str) -> list[dict]:
    """Get the outcome history for a strategy.

    Args:
        name: Strategy name.

    Returns:
        List of outcome dicts, most recent last.
    """
    for s in _load_file():
        if s.get("name") == name:
            return s.get("history", [])
    return []


def get_regime_stats(name: str) -> dict:
    """Get regime-specific performance for a strategy.

    Args:
        name: Strategy name.

    Returns:
        Dict mapping regime -> {wins, losses, total_pnl, win_rate}.
    """
    for s in _load_file():
        if s.get("name") == name:
            stats = s.get("regime_stats", {})
            # Add computed win_rate
            for regime, rs in stats.items():
                total = rs["wins"] + rs["losses"]
                rs["win_rate"] = round(rs["wins"] / total * 100, 1) if total > 0 else 0.0
            return stats
    return {}


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def compute_live_score(strategy: dict) -> float:
    """Compute a composite live score from all tracked data.

    Combines:
    - Optimizer fitness (30%)
    - Historical win rate (25%)
    - Regime consistency (25%)
    - Trade count consistency (20%)

    Higher is better.

    Args:
        strategy: Full strategy dict.

    Returns:
        Composite score (float).
    """
    fitness = strategy.get("fitness", 0.0)
    history = strategy.get("history", [])
    regime_stats = strategy.get("regime_stats", {})

    # Historical win rate (from live outcomes)
    if history:
        wins = sum(1 for h in history if h.get("win"))
        hist_win_rate = wins / len(history)
    else:
        hist_win_rate = strategy.get("metrics", {}).get("win_rate", 0.0) / 100

    # Regime consistency: average win rate across regimes
    if regime_stats:
        regime_rates = []
        for rs in regime_stats.values():
            total = rs.get("wins", 0) + rs.get("losses", 0)
            if total > 0:
                regime_rates.append(rs["wins"] / total)
        regime_score = sum(regime_rates) / len(regime_rates) if regime_rates else 0.0
    else:
        regime_score = 0.5  # neutral if no data

    # Consistency: reward strategies with more history (up to 50 trades)
    trade_count = len(history)
    consistency = min(trade_count, 50) / 50

    score = (
        FITNESS_WEIGHT * min(max(fitness / 5, 0), 1)  # normalize fitness to 0-1
        + WIN_RATE_WEIGHT * hist_win_rate
        + REGIME_WEIGHT * regime_score
        + CONSISTENCY_WEIGHT * consistency
    )

    return round(score, 4)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_strategies() -> list[dict]:
    """Load all strategies, sorted by live_score (best first).

    Returns:
        List of strategy dicts.
    """
    return _sort(_load_file())


def load_best() -> dict | None:
    """Load the single best strategy by live_score.

    Returns:
        Strategy dict, or None if empty.
    """
    strategies = load_strategies()
    return strategies[0] if strategies else None


def load_best_params() -> dict | None:
    """Load just the parameters of the best strategy.

    Returns:
        Parameters dict, or None.
    """
    best = load_best()
    if best is None:
        return None
    return dict(best["parameters"])


def load_best_for_regime(regime: str) -> dict | None:
    """Load the strategy with the best win rate for a specific regime.

    Args:
        regime: Market regime (e.g. 'trending_up', 'sideways').

    Returns:
        Strategy dict, or None if no data.
    """
    strategies = _load_file()
    best = None
    best_rate = -1.0

    for s in strategies:
        rs = s.get("regime_stats", {}).get(regime, {})
        total = rs.get("wins", 0) + rs.get("losses", 0)
        if total >= 3:  # need at least 3 trades to be meaningful
            rate = rs["wins"] / total
            if rate > best_rate:
                best_rate = rate
                best = s

    return best


# ---------------------------------------------------------------------------
# Management
# ---------------------------------------------------------------------------

def remove_strategy(name: str) -> bool:
    """Remove a strategy by name."""
    strategies = _load_file()
    filtered = [s for s in strategies if s.get("name") != name]
    if len(filtered) == len(strategies):
        return False
    _save_file(filtered)
    return True


def clear_all() -> None:
    """Remove all saved strategies."""
    _save_file([])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_entry(config: dict, metrics: dict, fitness: float) -> dict:
    """Build a full strategy entry dict."""
    return {
        "name": config.get("name", _param_key(config)),
        "parameters": {
            "ema_fast": config["ema_fast"],
            "ema_slow": config["ema_slow"],
            "rsi_buy": config["rsi_buy"],
            "rsi_sell": config["rsi_sell"],
        },
        "metrics": {
            "return_pct": metrics.get("return_pct", 0.0),
            "total_pnl": metrics.get("total_pnl", 0.0),
            "win_rate": metrics.get("win_rate", 0.0),
            "max_drawdown": metrics.get("max_drawdown", 0.0),
            "total_trades": metrics.get("total_trades", 0),
        },
        "fitness": fitness,
        "history": [],
        "regime_stats": {},
        "live_score": 0.0,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _param_key(config: dict) -> str:
    """Create a unique key from strategy parameters."""
    return (
        f"EMA_{config['ema_fast']}/{config['ema_slow']}"
        f"_RSI_{config['rsi_buy']}/{config['rsi_sell']}"
    )


def _param_key_from_entry(entry: dict) -> str:
    """Create a unique key from a stored strategy entry."""
    p = entry.get("parameters", {})
    return (
        f"EMA_{p.get('ema_fast', 0)}/{p.get('ema_slow', 0)}"
        f"_RSI_{p.get('rsi_buy', 0)}/{p.get('rsi_sell', 0)}"
    )


def _sort(strategies: list[dict]) -> list[dict]:
    """Sort strategies by live_score first, then fitness as tiebreaker."""
    return sorted(
        strategies,
        key=lambda s: (s.get("live_score", 0), s.get("fitness", 0)),
        reverse=True,
    )
