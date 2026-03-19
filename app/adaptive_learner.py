"""
Adaptive Learner — Safe self-learning system for CryptoMind.

Two learning layers:
1. Capital reallocation based on regime-specific performance
2. Small threshold tuning based on recent outcomes

Safety: gradual changes only, logged, resettable.
"""

import time
import json
from datetime import datetime, timezone

# ── Config ──────────────────────────────────────────────
LEARN_INTERVAL = 60          # cycles between learning passes (~30 min at 30s/cycle)
ALLOC_STEP = 0.01            # max 1% shift per learning pass
THRESHOLD_STEP = 1           # max 1-point threshold shift per pass
MIN_TRADES_TO_LEARN = 3      # need at least 3 trades before adjusting
MIN_ALLOC = 0.05             # 5% min
MAX_ALLOC = 0.30             # 30% max
THRESHOLD_BOUNDS = {
    "buy_threshold":  (45, 80),
    "sell_threshold":  (20, 55),
}

# ── State ───────────────────────────────────────────────
_enabled = True
_cycle_count = 0
_last_learn_cycle = 0

# Performance by strategy + regime
# { "SCALPER": { "SLEEPING": { wins: 2, losses: 1, total_pnl: 0.05 }, ... } }
_regime_performance: dict[str, dict[str, dict]] = {}

# Adaptation log (latest 50)
_adaptation_log: list[dict] = []

# Threshold adjustments applied (strategy → { field → delta })
_threshold_adjustments: dict[str, dict[str, int]] = {}

# Original thresholds (for reset)
_original_thresholds: dict[str, dict] = {}


def _log_adaptation(entry: dict):
    entry["timestamp"] = datetime.now(timezone.utc).isoformat()
    _adaptation_log.append(entry)
    if len(_adaptation_log) > 50:
        _adaptation_log[:] = _adaptation_log[-50:]


def _empty_regime_stats():
    return {"wins": 0, "losses": 0, "flat": 0, "total_pnl": 0.0, "trades": 0}


# ── Record a trade result ───────────────────────────────
def record_trade_result(strategy: str, regime: str, result: str, pnl: float):
    """Record win/loss/flat for a strategy in a specific regime."""
    if strategy not in _regime_performance:
        _regime_performance[strategy] = {}
    if regime not in _regime_performance[strategy]:
        _regime_performance[strategy][regime] = _empty_regime_stats()

    stats = _regime_performance[strategy][regime]
    stats["trades"] += 1
    stats["total_pnl"] += pnl
    if result == "win":
        stats["wins"] += 1
    elif result == "loss":
        stats["losses"] += 1
    else:
        stats["flat"] += 1


# ── Layer 1: Capital Reallocation ───────────────────────
def suggest_allocation_adjustments(strategies: dict, allocations: dict, current_regime: str) -> dict:
    """Return suggested allocation deltas based on regime-specific performance.
    Returns { strategy_name: delta } where delta is small (+/- ALLOC_STEP)."""

    if not _enabled:
        return {}

    adjustments = {}

    for name in strategies:
        if name not in _regime_performance:
            continue
        regime_stats = _regime_performance[name].get(current_regime)
        if not regime_stats or regime_stats["trades"] < MIN_TRADES_TO_LEARN:
            continue

        wins = regime_stats["wins"]
        losses = regime_stats["losses"]
        total = regime_stats["trades"]
        win_rate = wins / total if total > 0 else 0.5
        avg_pnl = regime_stats["total_pnl"] / total if total > 0 else 0

        current_alloc = allocations.get(name, 0.1)

        # Good performance in this regime → increase slightly
        if win_rate > 0.55 and avg_pnl > 0:
            delta = min(ALLOC_STEP, MAX_ALLOC - current_alloc)
            if delta > 0.001:
                adjustments[name] = delta
                _log_adaptation({
                    "type": "allocation_increase",
                    "strategy": name,
                    "regime": current_regime,
                    "from": round(current_alloc * 100, 1),
                    "to": round((current_alloc + delta) * 100, 1),
                    "reason": f"win_rate={win_rate:.0%} avg_pnl={avg_pnl:.4f} in {current_regime}",
                })

        # Poor performance → decrease slightly
        elif win_rate < 0.35 and total >= MIN_TRADES_TO_LEARN:
            delta = min(ALLOC_STEP, current_alloc - MIN_ALLOC)
            if delta > 0.001:
                adjustments[name] = -delta
                _log_adaptation({
                    "type": "allocation_decrease",
                    "strategy": name,
                    "regime": current_regime,
                    "from": round(current_alloc * 100, 1),
                    "to": round((current_alloc - delta) * 100, 1),
                    "reason": f"win_rate={win_rate:.0%} avg_pnl={avg_pnl:.4f} in {current_regime}",
                })

    return adjustments


# ── Layer 2: Threshold Tuning ───────────────────────────
def suggest_threshold_adjustments(strategies: dict, profiles: dict) -> dict:
    """Return suggested threshold tweaks based on recent performance.
    Returns { strategy_name: { "buy_threshold": delta, "sell_threshold": delta } }."""

    if not _enabled:
        return {}

    adjustments = {}

    for name, perf in _regime_performance.items():
        # Aggregate across all regimes
        total_trades = sum(s["trades"] for s in perf.values())
        total_wins = sum(s["wins"] for s in perf.values())
        total_losses = sum(s["losses"] for s in perf.values())

        if total_trades < MIN_TRADES_TO_LEARN:
            continue

        win_rate = total_wins / total_trades if total_trades > 0 else 0.5
        profile = profiles.get(name, {})
        current_buy = profile.get("buy_threshold", 60)
        current_sell = profile.get("sell_threshold", 40)

        adj = {}

        # Overtrading + losing → tighten thresholds
        if win_rate < 0.35 and total_trades >= 5:
            buy_min, buy_max = THRESHOLD_BOUNDS["buy_threshold"]
            sell_min, sell_max = THRESHOLD_BOUNDS["sell_threshold"]

            if current_buy + THRESHOLD_STEP <= buy_max:
                adj["buy_threshold"] = THRESHOLD_STEP
            if current_sell - THRESHOLD_STEP >= sell_min:
                adj["sell_threshold"] = -THRESHOLD_STEP

            if adj:
                _log_adaptation({
                    "type": "threshold_tighten",
                    "strategy": name,
                    "adjustments": adj,
                    "reason": f"win_rate={win_rate:.0%} over {total_trades} trades — tightening",
                })

        # Missing good trades (high win rate but very few trades) → loosen slightly
        elif win_rate > 0.7 and total_trades >= MIN_TRADES_TO_LEARN and total_trades < 10:
            buy_min, buy_max = THRESHOLD_BOUNDS["buy_threshold"]
            sell_min, sell_max = THRESHOLD_BOUNDS["sell_threshold"]

            if current_buy - THRESHOLD_STEP >= buy_min:
                adj["buy_threshold"] = -THRESHOLD_STEP
            if current_sell + THRESHOLD_STEP <= sell_max:
                adj["sell_threshold"] = THRESHOLD_STEP

            if adj:
                _log_adaptation({
                    "type": "threshold_loosen",
                    "strategy": name,
                    "adjustments": adj,
                    "reason": f"win_rate={win_rate:.0%} but only {total_trades} trades — loosening",
                })

        if adj:
            adjustments[name] = adj

    return adjustments


# ── Main learning pass ──────────────────────────────────
def run_learning_pass(strategies: dict, allocations: dict, profiles: dict, current_regime: str) -> dict:
    """Run one learning pass. Called from multi_strategy every LEARN_INTERVAL cycles.
    Returns { alloc_adjustments, threshold_adjustments }."""

    global _cycle_count, _last_learn_cycle
    _cycle_count += 1

    if not _enabled:
        return {"skipped": True, "reason": "learning disabled"}

    if _cycle_count - _last_learn_cycle < LEARN_INTERVAL:
        return {"skipped": True, "reason": "not yet time"}

    _last_learn_cycle = _cycle_count

    alloc_adj = suggest_allocation_adjustments(strategies, allocations, current_regime)
    thresh_adj = suggest_threshold_adjustments(strategies, profiles)

    return {
        "skipped": False,
        "allocation_adjustments": alloc_adj,
        "threshold_adjustments": thresh_adj,
        "cycle": _cycle_count,
    }


# ── Control ─────────────────────────────────────────────
def set_enabled(enabled: bool):
    global _enabled
    _enabled = enabled
    _log_adaptation({"type": "toggle", "enabled": enabled})


def reset_all():
    """Reset all learning state to defaults."""
    global _regime_performance, _threshold_adjustments, _cycle_count, _last_learn_cycle
    _regime_performance = {}
    _threshold_adjustments = {}
    _cycle_count = 0
    _last_learn_cycle = 0
    _log_adaptation({"type": "reset", "reason": "manual reset"})


def get_status() -> dict:
    """Return current adaptive learning status."""
    # Best strategy per regime
    best_by_regime = {}
    all_regimes = set()
    for name, regimes in _regime_performance.items():
        for regime, stats in regimes.items():
            all_regimes.add(regime)
            if stats["trades"] >= MIN_TRADES_TO_LEARN:
                wr = stats["wins"] / stats["trades"] if stats["trades"] > 0 else 0
                if regime not in best_by_regime or wr > best_by_regime[regime]["win_rate"]:
                    best_by_regime[regime] = {
                        "strategy": name,
                        "win_rate": round(wr * 100, 1),
                        "trades": stats["trades"],
                        "pnl": round(stats["total_pnl"], 6),
                    }

    return {
        "enabled": _enabled,
        "cycle": _cycle_count,
        "last_learn_cycle": _last_learn_cycle,
        "next_learn_in": max(0, LEARN_INTERVAL - (_cycle_count - _last_learn_cycle)),
        "strategies_tracked": len(_regime_performance),
        "regimes_observed": list(all_regimes),
        "best_by_regime": best_by_regime,
        "recent_adaptations": _adaptation_log[-10:][::-1],
        "total_adaptations": len(_adaptation_log),
    }
