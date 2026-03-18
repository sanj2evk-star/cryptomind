"""
rl_agent.py - Tabular Q-learning agent for BTC/USDT trading.

A simple reinforcement learning agent that learns to BUY, SELL,
or HOLD based on discretized market state. No deep learning —
uses a Q-table (dict) for fast lookup and training.

State space (discretized):
- EMA trend:    fast > slow, fast < slow, crossover_up, crossover_down
- RSI zone:     oversold (<30), neutral (30-70), overbought (>70)
- Regime:       trending_up, trending_down, sideways, high_volatility
- Position:     flat, long

Actions: BUY (0), SELL (1), HOLD (2)

Reward:
- Realized P&L on SELL
- Penalty for drawdown
- Small negative for holding too long

Usage:
    agent = QLearningAgent()
    agent.train(df, episodes=100)
    action = agent.act(state)
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path

import pandas as pd

from config import DATA_DIR, INITIAL_BALANCE, RISK_PER_TRADE_PERCENT
from indicators import add_ema, add_rsi
from regime_detector import add_atr, detect_regime

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACTIONS = ["BUY", "SELL", "HOLD"]
ACTION_BUY = 0
ACTION_SELL = 1
ACTION_HOLD = 2

Q_TABLE_FILE = DATA_DIR / "q_table.json"

# Reward shaping
DRAWDOWN_PENALTY = 2.0
HOLD_PENALTY = -0.001
INVALID_PENALTY = -0.01


# ---------------------------------------------------------------------------
# State discretization
# ---------------------------------------------------------------------------

def discretize_state(row: pd.Series, prev_row: pd.Series, regime: str, has_position: bool) -> tuple:
    """Convert continuous market data into a discrete state tuple.

    Args:
        row: Current candle with ema_fast, ema_slow, rsi columns.
        prev_row: Previous candle (for crossover detection).
        regime: Market regime string.
        has_position: Whether we currently hold BTC.

    Returns:
        Hashable state tuple: (ema_signal, rsi_zone, regime, position).
    """
    # EMA signal
    fast, slow = row["ema_fast"], row["ema_slow"]
    prev_fast, prev_slow = prev_row["ema_fast"], prev_row["ema_slow"]

    if prev_fast <= prev_slow and fast > slow:
        ema_signal = "cross_up"
    elif prev_fast >= prev_slow and fast < slow:
        ema_signal = "cross_down"
    elif fast > slow:
        ema_signal = "above"
    else:
        ema_signal = "below"

    # RSI zone
    rsi = row["rsi"]
    if pd.isna(rsi):
        rsi_zone = "neutral"
    elif rsi < 30:
        rsi_zone = "oversold"
    elif rsi > 70:
        rsi_zone = "overbought"
    else:
        rsi_zone = "neutral"

    # Position
    position = "long" if has_position else "flat"

    return (ema_signal, rsi_zone, regime, position)


# ---------------------------------------------------------------------------
# Experience buffer
# ---------------------------------------------------------------------------

class Experience:
    """Single transition: (state, action, reward, next_state)."""

    __slots__ = ("state", "action", "reward", "next_state")

    def __init__(self, state: tuple, action: int, reward: float, next_state: tuple):
        self.state = state
        self.action = action
        self.reward = reward
        self.next_state = next_state


class ReplayBuffer:
    """Simple experience storage with fixed max size."""

    def __init__(self, max_size: int = 10000):
        self.buffer: list[Experience] = []
        self.max_size = max_size

    def add(self, exp: Experience) -> None:
        """Store an experience."""
        if len(self.buffer) >= self.max_size:
            self.buffer.pop(0)
        self.buffer.append(exp)

    def sample(self, n: int) -> list[Experience]:
        """Sample n random experiences."""
        return random.sample(self.buffer, min(n, len(self.buffer)))

    def __len__(self) -> int:
        return len(self.buffer)


# ---------------------------------------------------------------------------
# Q-Learning Agent
# ---------------------------------------------------------------------------

class QLearningAgent:
    """Tabular Q-learning agent for trading decisions.

    Args:
        alpha: Learning rate (0-1).
        gamma: Discount factor (0-1).
        epsilon: Exploration rate (0-1).
        epsilon_decay: Multiply epsilon by this after each episode.
        epsilon_min: Floor for epsilon.
    """

    def __init__(
        self,
        alpha: float = 0.1,
        gamma: float = 0.95,
        epsilon: float = 1.0,
        epsilon_decay: float = 0.995,
        epsilon_min: float = 0.05,
    ):
        self.alpha = alpha
        self.gamma = gamma
        self.epsilon = epsilon
        self.epsilon_decay = epsilon_decay
        self.epsilon_min = epsilon_min

        # Q-table: state -> [Q(BUY), Q(SELL), Q(HOLD)]
        self.q_table: dict[tuple, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
        self.buffer = ReplayBuffer()

    def act(self, state: tuple) -> int:
        """Choose an action using epsilon-greedy policy.

        Args:
            state: Discretized state tuple.

        Returns:
            Action index (0=BUY, 1=SELL, 2=HOLD).
        """
        if random.random() < self.epsilon:
            return random.randint(0, 2)

        q_values = self.q_table[state]
        return q_values.index(max(q_values))

    def act_greedy(self, state: tuple) -> int:
        """Choose the best action (no exploration).

        Args:
            state: Discretized state tuple.

        Returns:
            Action index with highest Q-value.
        """
        q_values = self.q_table[state]
        return q_values.index(max(q_values))

    def learn(self, state: tuple, action: int, reward: float, next_state: tuple) -> None:
        """Update Q-value for a single transition.

        Q(s,a) += alpha * (reward + gamma * max(Q(s')) - Q(s,a))

        Args:
            state: Current state.
            action: Action taken.
            reward: Reward received.
            next_state: Resulting state.
        """
        current_q = self.q_table[state][action]
        max_next_q = max(self.q_table[next_state])
        target = reward + self.gamma * max_next_q

        self.q_table[state][action] = current_q + self.alpha * (target - current_q)

        self.buffer.add(Experience(state, action, reward, next_state))

    def replay(self, batch_size: int = 32) -> None:
        """Learn from a batch of past experiences.

        Args:
            batch_size: Number of experiences to sample.
        """
        for exp in self.buffer.sample(batch_size):
            self.learn(exp.state, exp.action, exp.reward, exp.next_state)

    def decay_epsilon(self) -> None:
        """Reduce exploration rate."""
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)

    # -------------------------------------------------------------------
    # Persistence
    # -------------------------------------------------------------------

    def save(self, path: Path = Q_TABLE_FILE) -> None:
        """Save Q-table to JSON.

        Args:
            path: File path.
        """
        serializable = {str(k): v for k, v in self.q_table.items()}
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(serializable, indent=2) + "\n", encoding="utf-8")

    def load(self, path: Path = Q_TABLE_FILE) -> None:
        """Load Q-table from JSON.

        Args:
            path: File path.
        """
        if not path.exists():
            return

        raw = json.loads(path.read_text(encoding="utf-8"))
        for k, v in raw.items():
            # Convert string key back to tuple
            state = tuple(k.strip("()").replace("'", "").split(", "))
            self.q_table[state] = v


# ---------------------------------------------------------------------------
# Training environment
# ---------------------------------------------------------------------------

def compute_reward(pnl: float, peak_equity: float, current_equity: float) -> float:
    """Compute shaped reward from trade outcome.

    Reward = realized P&L - drawdown penalty.

    Args:
        pnl: Realized P&L from this action (0 for BUY/HOLD).
        peak_equity: Highest equity seen so far.
        current_equity: Current portfolio equity.

    Returns:
        Reward value.
    """
    drawdown = (peak_equity - current_equity) / peak_equity if peak_equity > 0 else 0
    return pnl - (drawdown * DRAWDOWN_PENALTY)


def train(df: pd.DataFrame, agent: QLearningAgent, episodes: int = 50, persist: bool = True) -> dict:
    """Train the agent on historical data.

    Each episode runs through the full DataFrame, making trading
    decisions and learning from rewards. Experiences from the final
    episode are persisted to data/experience_buffer.json.

    Args:
        df: OHLCV DataFrame with ema_fast, ema_slow, rsi, atr columns.
        agent: QLearningAgent instance.
        episodes: Number of training episodes.
        persist: Save final episode experiences to experience_store.

    Returns:
        dict with training stats: episode_rewards, final_epsilon, q_table_size.
    """
    import experience_store

    warmup = 22  # enough for EMA(21) + 1
    episode_rewards = []

    for ep in range(1, episodes + 1):
        cash = INITIAL_BALANCE
        has_position = False
        position_size = 0.0
        entry_price = 0.0
        peak_equity = INITIAL_BALANCE
        total_reward = 0.0

        for i in range(warmup, len(df)):
            row = df.iloc[i]
            prev_row = df.iloc[i - 1]
            price = row["close"]

            # Detect regime for this window
            window = df.iloc[max(0, i - 20):i + 1]
            regime_info = detect_regime(window)
            regime = regime_info["regime"]

            # Build state
            state = discretize_state(row, prev_row, regime, has_position)

            # Choose action
            action = agent.act(state)

            # Execute and compute reward
            pnl = 0.0
            reward = HOLD_PENALTY  # default for HOLD

            if action == ACTION_BUY and not has_position and cash > 0:
                risk = cash * (RISK_PER_TRADE_PERCENT / 100)
                position_size = risk / price
                cash -= position_size * price
                entry_price = price
                has_position = True
                reward = 0.0  # neutral on entry

            elif action == ACTION_SELL and has_position:
                pnl = (price - entry_price) * position_size
                cash += position_size * price
                has_position = False
                position_size = 0.0
                entry_price = 0.0

                equity = cash
                reward = compute_reward(pnl, peak_equity, equity)

            elif action == ACTION_BUY and has_position:
                reward = INVALID_PENALTY  # can't double buy

            elif action == ACTION_SELL and not has_position:
                reward = INVALID_PENALTY  # can't sell without position

            # Update equity tracking
            equity = cash + (position_size * price if has_position else 0)
            if equity > peak_equity:
                peak_equity = equity

            # Build next state
            if i + 1 < len(df):
                next_row = df.iloc[i + 1] if i + 1 < len(df) else row
                next_regime = regime  # approximate
                next_state = discretize_state(
                    next_row if i + 1 < len(df) else row,
                    row, next_regime, has_position,
                )
            else:
                next_state = state

            # Learn
            agent.learn(state, action, reward, next_state)
            total_reward += reward

            # Persist experiences from the final episode
            if persist and ep == episodes:
                experience_store.save_experience(
                    state=state,
                    action=action,
                    reward=reward,
                    next_state=next_state,
                    pnl=pnl,
                    equity_after=equity,
                )

        # End of episode
        agent.replay(batch_size=32)
        agent.decay_epsilon()
        episode_rewards.append(round(total_reward, 4))

        if ep % 10 == 0 or ep == 1:
            print(f"  Episode {ep:>3}/{episodes}  "
                  f"reward={total_reward:>8.4f}  "
                  f"epsilon={agent.epsilon:.4f}  "
                  f"states={len(agent.q_table)}")

    return {
        "episode_rewards": episode_rewards,
        "final_epsilon": agent.epsilon,
        "q_table_size": len(agent.q_table),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Train the RL agent on cached historical data."""
    from data_fetcher import fetch_historical_cached

    df = fetch_historical_cached(total=500, label="rl_training")
    print(f"Dataset: {len(df)} candles")

    print("Computing indicators...")
    df = add_ema(df)
    df = add_rsi(df)
    df = add_atr(df)

    agent = QLearningAgent()
    agent.load()

    print(f"Training ({50} episodes)...")
    stats = train(df, agent, episodes=50)

    agent.save()
    print(f"\nQ-table saved: {len(agent.q_table)} states")
    print(f"Final epsilon: {stats['final_epsilon']:.4f}")

    # Show learned policy for key states
    print("\n--- Learned Policy (sample) ---")
    sample_states = [
        ("cross_up", "oversold", "trending_up", "flat"),
        ("cross_down", "overbought", "trending_down", "long"),
        ("above", "neutral", "sideways", "flat"),
        ("below", "neutral", "high_volatility", "long"),
        ("cross_up", "neutral", "trending_up", "flat"),
    ]
    for s in sample_states:
        q = agent.q_table[s]
        best = ACTIONS[q.index(max(q))]
        print(f"  {str(s):60s} -> {best:4s}  Q={[round(v,4) for v in q]}")


if __name__ == "__main__":
    main()
