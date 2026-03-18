"""
main.py - Application entry point.

Executes one full regime-adaptive trading cycle with RL integration:
 1. Load strategy params + RL agent
 2. Fetch BTC/USDT OHLCV data and current price
 3. Compute technical indicators + ATR
 4. Detect market regime → select strategy
 5. Build discrete state for RL agent
 6. Get decisions from Claude bots (trend + mean rev)
 7. Risk Manager approves or rejects
 8. Decision engine resolves final action
 9. RL agent advises (can nudge confidence or veto)
10. Execute paper trade
11. Compute reward → update RL agent → store experience
12. Log, alert, print summary
"""

from config import load_env, SYMBOLS
from data_fetcher import fetch_ohlcv, fetch_current_price
from indicators import compute_indicators
from regime_detector import add_atr, detect_regime
from prompt_builder import (
    build_trend_prompt,
    build_mean_reversion_prompt,
    build_risk_manager_prompt,
)
from claude_client import get_trading_decision, get_risk_verdict, DEFAULT_HOLD
from decision_engine import resolve
from paper_broker import load_portfolio, execute_trade
from logger import log_decision, log_trade
from strategy_store import load_best
from alerts import alert_on_trade, notify_regime_change, notify_anomaly
from anomaly_detector import check_anomalies
from rl_agent import (
    QLearningAgent, discretize_state, compute_reward,
    ACTIONS, ACTION_BUY, ACTION_SELL, ACTION_HOLD,
)
import experience_store


# ---------------------------------------------------------------------------
# RL integration
# ---------------------------------------------------------------------------

# How much the RL agent can influence decisions (0.0 = none, 1.0 = full override)
# Starts low and can be increased as the agent learns more
RL_INFLUENCE = 0.3

# Minimum Q-table entries before the agent's opinion matters
RL_MIN_EXPERIENCE = 20


def _action_to_index(action: str) -> int:
    """Convert action string to RL action index."""
    return {"BUY": ACTION_BUY, "SELL": ACTION_SELL}.get(action, ACTION_HOLD)


def apply_rl_influence(
    decision: dict,
    rl_action: int,
    rl_q_values: list[float],
    agent_ready: bool,
) -> dict:
    """Let the RL agent influence the final decision.

    The rule-based system remains the base layer. The RL agent can:
    1. Boost confidence if it agrees with the rule-based decision.
    2. Reduce confidence if it disagrees.
    3. Veto a trade (force HOLD) if it strongly prefers HOLD.

    The influence is proportional to RL_INFLUENCE (default 30%).

    Args:
        decision: Final decision dict from the rule-based pipeline.
        rl_action: RL agent's preferred action index.
        rl_q_values: Q-values for [BUY, SELL, HOLD].
        agent_ready: Whether the agent has enough experience.

    Returns:
        Decision dict, potentially modified.
    """
    if not agent_ready:
        decision["rl_note"] = "RL agent not ready (insufficient experience)"
        return decision

    rule_action = decision.get("action", "HOLD")
    rule_action_idx = _action_to_index(rule_action)
    rl_action_str = ACTIONS[rl_action]
    confidence = float(decision.get("confidence", 0.0))

    # Q-value spread: how confident is the RL agent?
    max_q = max(rl_q_values)
    min_q = min(rl_q_values)
    q_spread = max_q - min_q if max_q != min_q else 0.0

    if rule_action_idx == rl_action:
        # Agreement: boost confidence
        boost = RL_INFLUENCE * min(q_spread * 10, 0.15)
        decision["confidence"] = min(confidence + boost, 0.99)
        decision["rl_note"] = f"RL agrees ({rl_action_str}), confidence +{boost:.3f}"

    elif rl_action == ACTION_HOLD and rule_action in ("BUY", "SELL"):
        # RL prefers HOLD but rules want to trade — reduce confidence
        penalty = RL_INFLUENCE * min(q_spread * 10, 0.2)
        new_conf = confidence - penalty
        decision["confidence"] = max(new_conf, 0.0)
        decision["rl_note"] = f"RL prefers HOLD, confidence -{penalty:.3f}"

        # Strong veto: if RL drops confidence below minimum threshold
        if new_conf < 0.5:
            decision["action"] = "HOLD"
            decision["rl_note"] = f"RL VETOED {rule_action} (conf dropped to {new_conf:.3f})"

    else:
        # Disagreement on direction — slight confidence reduction
        penalty = RL_INFLUENCE * 0.05
        decision["confidence"] = max(confidence - penalty, 0.0)
        decision["rl_note"] = f"RL suggests {rl_action_str} (disagree), confidence -{penalty:.3f}"

    return decision


# ---------------------------------------------------------------------------
# Regime-based strategy selection
# ---------------------------------------------------------------------------

REGIME_STRATEGY = {
    "trending_up": "trend",
    "trending_down": "trend",
    "sideways": "mean_reversion",
    "high_volatility": "hold",
}


def select_strategy(regime: str) -> str:
    """Select the primary strategy based on market regime."""
    return REGIME_STRATEGY.get(regime, "hold")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(
    symbol: str,
    regime_info: dict,
    strategy: str,
    trend: dict,
    mean_rev: dict,
    verdict: dict,
    final_decision: dict,
    result: dict,
) -> None:
    """Print a clean terminal summary of the trading cycle."""
    portfolio = result.get("portfolio", {})
    asset = symbol.split("/")[0]

    print("\n" + "=" * 60)
    print(f"  {symbol} - Adaptive Cycle + RL")
    print("=" * 60)

    print(f"  Price:          ${result['price']:,.2f}")
    print(f"  Regime:         {regime_info['regime']}")
    print(f"  Strategy:       {strategy}")
    print("-" * 60)

    print(f"  Trend Bot:      {trend.get('action', 'HOLD'):4s}  "
          f"(conf: {trend.get('confidence', 0.0)})"
          f"{'  <-- primary' if strategy == 'trend' else ''}")
    print(f"  Mean Rev Bot:   {mean_rev.get('action', 'HOLD'):4s}  "
          f"(conf: {mean_rev.get('confidence', 0.0)})"
          f"{'  <-- primary' if strategy == 'mean_reversion' else ''}")
    print(f"  Signal:         {final_decision.get('strength', 'N/A')}")
    print(f"  Risk Manager:   {'APPROVED' if verdict.get('approved') else 'REJECTED'}")
    print(f"  RL Agent:       {final_decision.get('rl_note', 'N/A')}")
    print("-" * 60)

    print(f"  Final Action:   {result['action']}")
    print(f"  Quantity:       {result['quantity']:.6f} {asset}")
    print(f"  P&L:            ${result['pnl']:,.2f}")
    print("-" * 60)

    print(f"  Cash:           ${portfolio.get('cash', 0.0):,.2f}")
    print(f"  Position:       {'Open' if portfolio.get('position_open') else 'None'}")
    print(f"  Unrealized:     ${portfolio.get('unrealized_pnl', 0.0):,.4f}")
    print(f"  Realized P&L:   ${portfolio.get('realized_pnl', 0.0):,.4f}")
    print(f"  Total Equity:   ${portfolio.get('total_equity', 0.0):,.4f}")
    print("=" * 60)
    print(f"  Reason: {result.get('reason', '')}")
    print()


# ---------------------------------------------------------------------------
# Trading cycle
# ---------------------------------------------------------------------------

def trade_asset(symbol: str, rl_agent: QLearningAgent, agent_ready: bool) -> None:
    """Run one full adaptive trading cycle for a single asset.

    Args:
        symbol: Trading pair (e.g. 'BTC/USDT').
        rl_agent: Shared RL agent instance.
        agent_ready: Whether the RL agent has enough experience.
    """
    asset = symbol.split("/")[0]
    print(f"\n{'#' * 60}")
    print(f"  Processing {symbol}")
    print(f"{'#' * 60}")

    # 1. Fetch market data
    print(f"  [1/8] Fetching {symbol} data...")
    df = fetch_ohlcv(symbol=symbol)
    current_price = fetch_current_price(symbol=symbol)

    # 2. Compute indicators
    print(f"  [2/8] Computing indicators...")
    df = compute_indicators(df)
    df = add_atr(df)

    # 3. Detect market regime
    regime_info = detect_regime(df)
    regime = regime_info["regime"]
    strategy = select_strategy(regime)
    print(f"  [3/9] Regime: {regime} -> Strategy: {strategy}")

    # 4. Anomaly check
    anomaly = check_anomalies(df)
    if anomaly["is_anomaly"]:
        print(f"  [4/9] ANOMALY DETECTED — pausing {symbol}")
        for r in anomaly["reasons"]:
            print(f"         {r}")
        notify_anomaly(anomaly["reasons"])
        return

    # 5. Load portfolio + build RL state
    portfolio = load_portfolio()
    pos = portfolio.get("positions", {}).get(symbol, {})
    has_position = pos.get("position_open", False)

    last_row = df.iloc[-1]
    prev_row = df.iloc[-2]
    rl_state = discretize_state(last_row, prev_row, regime, has_position)
    rl_action = rl_agent.act_greedy(rl_state)
    rl_q_values = list(rl_agent.q_table[rl_state])
    print(f"  [5/9] RL suggests: {ACTIONS[rl_action]}")

    # 6. Get Claude bot decisions
    if strategy == "hold":
        print(f"  [6/9] High volatility, forcing HOLD...")
        trend_decision = DEFAULT_HOLD.copy()
        mr_decision = DEFAULT_HOLD.copy()
        verdict = {"approved": False, "reasoning": "High volatility.", "risk_notes": ""}
    else:
        if strategy == "trend":
            print(f"  [6/9] Trend Bot leads...")
            trend_prompt = build_trend_prompt(df, current_price, portfolio)
            trend_decision = get_trading_decision(trend_prompt)
            mr_prompt = build_mean_reversion_prompt(df, current_price, portfolio)
            mr_decision = get_trading_decision(mr_prompt)
        else:
            print(f"  [6/9] Mean Rev Bot leads...")
            mr_prompt = build_mean_reversion_prompt(df, current_price, portfolio)
            mr_decision = get_trading_decision(mr_prompt)
            trend_prompt = build_trend_prompt(df, current_price, portfolio)
            trend_decision = get_trading_decision(trend_prompt)

        print(f"  [7/9] Risk Manager...")
        risk_prompt = build_risk_manager_prompt(trend_decision, mr_decision, portfolio)
        verdict = get_risk_verdict(risk_prompt)

    # 7. Resolve + RL influence
    final_decision = resolve(trend_decision, mr_decision, verdict, regime)
    final_decision = apply_rl_influence(final_decision, rl_action, rl_q_values, agent_ready)
    print(f"  [8/9] {final_decision.get('rl_note', 'No RL note')}")

    # 8. Execute
    result = execute_trade(final_decision, current_price, df=df, symbol=symbol)

    # 9. Learn + log + alert
    pnl = result.get("pnl", 0.0)
    equity = result.get("portfolio", {}).get("total_equity", 100.0)
    reward = compute_reward(pnl, equity, equity)

    new_has_position = result.get("portfolio", {}).get("position_open", False)
    next_state = discretize_state(last_row, prev_row, regime, new_has_position)

    action_idx = _action_to_index(result["action"])
    rl_agent.learn(rl_state, action_idx, reward, next_state)

    experience_store.save_experience(
        state=rl_state, action=action_idx, reward=reward,
        next_state=next_state, pnl=pnl, equity_after=equity,
    )

    log_decision(final_decision)
    log_trade(result, decision=final_decision)
    alert_on_trade(result, decision=final_decision)

    print_summary(symbol, regime_info, strategy, trend_decision, mr_decision,
                  verdict, final_decision, result)


def trading_cycle(symbols: list[str] = None) -> None:
    """Run one full cycle across all configured assets.

    Args:
        symbols: List of trading pairs (default: SYMBOLS from config).
    """
    if symbols is None:
        symbols = SYMBOLS

    # Load shared components once
    best_strat = load_best()
    if best_strat:
        print(f"Strategy: {best_strat['name']} (fitness={best_strat['fitness']:.4f})")
    else:
        print("Strategy: defaults (EMA 9/21, RSI 30/70)")

    rl_agent = QLearningAgent(epsilon=0.05, epsilon_min=0.02)
    rl_agent.load()
    agent_ready = len(rl_agent.q_table) >= RL_MIN_EXPERIENCE
    print(f"RL agent: {len(rl_agent.q_table)} states ({'active' if agent_ready else 'learning'})")
    print(f"Assets: {', '.join(symbols)}")

    # Process each asset
    for symbol in symbols:
        try:
            trade_asset(symbol, rl_agent, agent_ready)
        except Exception as e:
            print(f"\n  ERROR processing {symbol}: {e}\n")

    # Save RL agent once after all assets
    rl_agent.save()
    print(f"\nCycle complete for {len(symbols)} assets.")


def main() -> None:
    """Entry point: load env and run one multi-asset trading cycle."""
    load_env()
    trading_cycle()


if __name__ == "__main__":
    main()
