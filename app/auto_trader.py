"""
auto_trader.py — Autonomous paper trading engine (v2: adaptive).

Adaptive multi-signal scoring system:
- EMA crossover (35% weight)
- RSI momentum (25% weight)
- Trend detection via slope + momentum (25% weight)
- Momentum acceleration (15% weight)

Adaptive features:
- Dynamic thresholds that tighten/loosen with volatility
- Momentum acceleration layer (+10 score boost when confirming trend)
- Spike detection to avoid chasing sharp moves
- Early trend detection for smaller exploratory entries
- Volatility-aware confidence calculation

Decision: score 0–100 → BUY/SELL thresholds adjust with volatility.
Cooldown: 2 minutes between trades. Skips choppy/unstable markets.

NO real trading. NO exchange API keys. Simulation only.
"""

from __future__ import annotations

import csv
import json
import math
import time
import threading
from datetime import datetime, timezone
from urllib.request import urlopen
from urllib.error import URLError

from config import DATA_DIR, INITIAL_BALANCE
from user_manager import get_user_file

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Price APIs — try multiple sources (Binance blocked from US servers)
PRICE_SOURCES = [
    ("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", lambda d: float(d["price"])),
    ("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd", lambda d: float(d["bitcoin"]["usd"])),
    ("https://api.coinbase.com/v2/prices/BTC-USD/spot", lambda d: float(d["data"]["amount"])),
]
LOOP_INTERVAL = 30   # seconds between cycles
MAX_HISTORY = 200    # price history buffer
MAX_RISK_PCT = 0.50  # never risk more than 50% of capital

# Dynamic position sizing tiers (confidence → % of capital)
# Mirrors a professional trader: size up with conviction, sit out when unsure
POSITION_TIERS = [
    # (min_confidence, max_confidence, position_pct)
    (0.00, 0.40, 0.00),   # no trade — not enough conviction
    (0.40, 0.60, 0.10),   # small — toe in the water (10%)
    (0.60, 0.75, 0.25),   # medium — solid setup (25%)
    (0.75, 1.00, 0.50),   # full — high conviction (50%)
]

# Indicator periods
EMA_SHORT = 9
EMA_LONG = 21
RSI_PERIOD = 14
SLOPE_LOOKBACK = 5   # candles for trend slope
MOMENTUM_LOOKBACK = 10
ACCEL_LOOKBACK = 3   # candles for momentum acceleration

# Scoring weights (must sum to 1.0)
W_EMA = 0.35
W_RSI = 0.25
W_TREND = 0.25
W_MOMENTUM = 0.15

# Default thresholds (adjusted dynamically by volatility)
BASE_BUY_THRESHOLD = 65
BASE_SELL_THRESHOLD = 35
COOLDOWN_SECONDS = 120  # 2 minutes between trades
MIN_VOLATILITY = 0.0001 # absolute floor — below this, market is dead
MIN_CONFIDENCE = 0.40    # skip trades below 40% confidence

# Volatility regime boundaries (std dev of returns)
VOL_LOW = 0.0005   # below = low volatility regime
VOL_HIGH = 0.0020  # above = high volatility regime

# Spike detection: skip if last candle moved > this % in one tick
SPIKE_THRESHOLD_PCT = 0.35

# Early trend: score zone where we detect emerging signal
EARLY_TREND_ZONE = 5  # points before threshold

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_state = {
    "running": False,
    "thread": None,
    "price_history": [],
    "last_price": 0.0,
    "last_decision": None,
    "last_update": "",
    "last_trade_time": 0,  # unix timestamp of last executed trade
    "indicators": {},
    "market_state": {"state": "SLEEPING", "confidence_score": 0, "reason": "", "reasons": []},
    "cycle_count": 0,
    "error": None,
    # Session insight tracking
    "session_start": 0,
    "session_cycles": 0,
    "session_trades_taken": 0,
    "session_trades_avoided": 0,
    "session_holds": 0,
    "session_buys": 0,
    "session_sells": 0,
    "session_vol_regimes": [],     # last N vol regimes for dominant calc
    "session_trends": [],          # last N trends
    "session_scores": [],          # last N scores
    "session_insight": "",         # latest generated insight
    "session_insight_time": "",    # when it was generated
    "last_insight_cycle": 0,       # cycle count at last insight generation
}

INSIGHT_INTERVAL_CYCLES = 10  # generate insight every ~10 cycles (~5 min at 30s)


# ---------------------------------------------------------------------------
# Live Price
# ---------------------------------------------------------------------------

def get_live_price() -> float:
    """Fetch live BTC/USD price. Tries multiple APIs with fallback.

    Order: Binance → CoinGecko → Coinbase.
    Binance is fastest but blocked from US servers (HTTP 451).
    """
    for url, parser in PRICE_SOURCES:
        try:
            with urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
                price = parser(data)
                if price > 0:
                    _state["error"] = None
                    return price
        except Exception:
            continue
    _state["error"] = "Price fetch failed: all sources unavailable"
    return 0.0


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------

def compute_ema(prices: list[float], period: int) -> float:
    """Exponential Moving Average."""
    if len(prices) < period:
        return prices[-1] if prices else 0.0
    multiplier = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
    return round(ema, 2)


def compute_rsi(prices: list[float], period: int = RSI_PERIOD) -> float:
    """Relative Strength Index (0–100)."""
    if len(prices) < period + 1:
        return 50.0
    changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    recent = changes[-period:]
    gains = [c for c in recent if c > 0]
    losses = [-c for c in recent if c < 0]
    avg_gain = sum(gains) / period if gains else 0.0001
    avg_loss = sum(losses) / period if losses else 0.0001
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def compute_slope(prices: list[float], lookback: int = SLOPE_LOOKBACK) -> float:
    """Price slope as percentage change over lookback period.

    Positive = upward, negative = downward, near-zero = sideways.
    """
    if len(prices) < lookback + 1:
        return 0.0
    old = prices[-(lookback + 1)]
    new = prices[-1]
    if old == 0:
        return 0.0
    return round((new - old) / old * 100, 4)


def compute_momentum(prices: list[float], lookback: int = MOMENTUM_LOOKBACK) -> float:
    """Momentum: rate of change normalized to 0–100 scale.

    50 = flat, >50 = upward momentum, <50 = downward.
    """
    if len(prices) < lookback + 1:
        return 50.0
    old = prices[-(lookback + 1)]
    new = prices[-1]
    if old == 0:
        return 50.0
    pct = (new - old) / old * 100
    # Map to 0–100: -2% → 0, 0% → 50, +2% → 100
    return round(max(0, min(100, 50 + pct * 25)), 2)


def compute_volatility(prices: list[float], lookback: int = 20) -> float:
    """Recent volatility as standard deviation of returns."""
    if len(prices) < lookback + 1:
        return 0.0
    recent = prices[-lookback:]
    returns = [(recent[i] - recent[i - 1]) / recent[i - 1] for i in range(1, len(recent)) if recent[i - 1] > 0]
    if not returns:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / len(returns)
    return round(math.sqrt(variance), 6)


def classify_volatility(vol: float) -> str:
    """Classify volatility into regime: 'low', 'normal', 'high'."""
    if vol < VOL_LOW:
        return "low"
    if vol > VOL_HIGH:
        return "high"
    return "normal"


def compute_acceleration(prices: list[float], lookback: int = ACCEL_LOOKBACK) -> float:
    """Momentum acceleration: is the move speeding up or slowing down?

    Compares the slope of the most recent `lookback` candles to the prior
    `lookback` candles. Positive = accelerating upward, negative = decelerating.
    Returns a value normalized to roughly -100..+100.
    """
    needed = lookback * 2 + 1
    if len(prices) < needed:
        return 0.0
    recent_slope = (prices[-1] - prices[-(lookback + 1)]) / prices[-(lookback + 1)] * 100
    prior_slope = (prices[-(lookback + 1)] - prices[-(2 * lookback + 1)]) / prices[-(2 * lookback + 1)] * 100
    return round((recent_slope - prior_slope) * 50, 2)  # amplify to -100..+100 range


def detect_spike(prices: list[float]) -> bool:
    """Return True if the last price change was a sharp spike (> SPIKE_THRESHOLD_PCT).

    Used to avoid chasing sudden moves that often reverse.
    """
    if len(prices) < 2:
        return False
    prev = prices[-2]
    if prev == 0:
        return False
    change_pct = abs((prices[-1] - prev) / prev) * 100
    return change_pct > SPIKE_THRESHOLD_PCT


def detect_trend(slope: float, momentum: float) -> str:
    """Classify short-term trend from slope and momentum.

    Returns: 'bullish', 'bearish', or 'sideways'.
    """
    if slope > 0.05 and momentum > 55:
        return "bullish"
    if slope < -0.05 and momentum < 45:
        return "bearish"
    return "sideways"


def detect_emerging_trend(slope: float, momentum: float, acceleration: float) -> str:
    """Detect a trend that is forming but not yet confirmed.

    An emerging trend shows acceleration in one direction even though
    slope/momentum haven't crossed the full trend thresholds yet.

    Returns: 'emerging_bull', 'emerging_bear', or 'none'.
    """
    if acceleration > 15 and slope > 0.01 and momentum > 50:
        return "emerging_bull"
    if acceleration < -15 and slope < -0.01 and momentum < 50:
        return "emerging_bear"
    return "none"


def compute_indicators(prices: list[float]) -> dict:
    """Compute all indicators from price history."""
    ema_short = compute_ema(prices, EMA_SHORT)
    ema_long = compute_ema(prices, EMA_LONG)
    rsi = compute_rsi(prices, RSI_PERIOD)
    slope = compute_slope(prices, SLOPE_LOOKBACK)
    momentum = compute_momentum(prices, MOMENTUM_LOOKBACK)
    volatility = compute_volatility(prices)
    acceleration = compute_acceleration(prices, ACCEL_LOOKBACK)
    trend = detect_trend(slope, momentum)
    vol_regime = classify_volatility(volatility)
    is_spike = detect_spike(prices)
    emerging = detect_emerging_trend(slope, momentum, acceleration)

    return {
        "ema_short": ema_short,
        "ema_long": ema_long,
        "rsi": rsi,
        "slope": slope,
        "momentum": momentum,
        "volatility": volatility,
        "vol_regime": vol_regime,
        "acceleration": acceleration,
        "trend": trend,
        "emerging_trend": emerging,
        "is_spike": is_spike,
    }


# ---------------------------------------------------------------------------
# Market State Detector
# ---------------------------------------------------------------------------

def detect_market_state(indicators: dict, prev_state: str = "SLEEPING") -> dict:
    """Detect the current market state from indicators.

    States:
        SLEEPING  — dead market, no edge, don't trade
        WAKING_UP — volatility/spread rising, prepare for entries
        ACTIVE    — clear signals, strong entries
        BREAKOUT  — explosive move, aggressive entries

    Args:
        indicators: From compute_indicators().
        prev_state: Previous cycle's state (for transition detection).

    Returns:
        dict with state, confidence_score (0–100), reason, reasons list.
    """
    vol = indicators.get("volatility", 0)
    rsi = indicators.get("rsi", 50)
    ema_s = indicators.get("ema_short", 0)
    ema_l = indicators.get("ema_long", 0)
    slope = indicators.get("slope", 0)
    accel = indicators.get("acceleration", 0)
    is_spike = indicators.get("is_spike", False)

    # EMA spread as % of price
    ema_spread = abs(ema_s - ema_l) / ema_l * 100 if ema_l > 0 else 0

    # RSI range — how far from neutral
    rsi_range = abs(rsi - 50)

    reasons = []
    score = 0

    # --- BREAKOUT detection (highest priority) ---
    if is_spike or (vol > VOL_HIGH * 2 and abs(slope) > 0.3):
        state = "BREAKOUT"
        score = min(95, 70 + int(vol * 10000) + int(abs(slope) * 50))
        if is_spike:
            reasons.append("Sudden price spike detected")
        if vol > VOL_HIGH * 2:
            reasons.append(f"Extreme volatility ({vol:.4%})")
        if abs(slope) > 0.3:
            reasons.append(f"Sharp directional move ({slope:+.2f}%)")
        if rsi_range > 20:
            reasons.append(f"RSI stretched to {rsi:.0f}")

    # --- ACTIVE market ---
    elif vol > VOL_HIGH and ema_spread > 0.05:
        state = "ACTIVE"
        score = min(85, 50 + int(vol * 5000) + int(ema_spread * 200))
        reasons.append(f"Volatility elevated ({vol:.4%})")
        reasons.append(f"EMA spread widening ({ema_spread:.3f}%)")
        if rsi_range > 15:
            reasons.append(f"RSI showing conviction at {rsi:.0f}")
        if abs(accel) > 10:
            reasons.append("Momentum accelerating")

    # --- WAKING UP ---
    elif (vol > VOL_LOW and (ema_spread > 0.02 or rsi_range > 10 or abs(accel) > 5)):
        state = "WAKING_UP"
        score = min(65, 30 + int(vol * 3000) + int(ema_spread * 100) + int(rsi_range))
        if vol > VOL_LOW:
            reasons.append("Volatility rising from lows")
        if ema_spread > 0.02:
            reasons.append("EMA spread expanding")
        if rsi_range > 10:
            reasons.append(f"RSI drifting to {rsi:.0f}")
        if abs(accel) > 5:
            reasons.append("Early momentum building")

    # --- SLEEPING ---
    else:
        state = "SLEEPING"
        score = max(5, 20 - int(vol * 1000))
        reasons.append("Low volatility, no conviction")
        if rsi_range < 10:
            reasons.append(f"RSI flat at {rsi:.0f}")
        if ema_spread < 0.01:
            reasons.append("EMAs compressed — no direction")

    # Detect transitions
    if prev_state != state:
        reasons.insert(0, f"Market transitioned: {prev_state} → {state}")

    # Build summary reason
    reason_summary = ". ".join(reasons[:3]) + "." if reasons else "No data."

    return {
        "state": state,
        "confidence_score": min(100, max(0, score)),
        "reason": reason_summary,
        "reasons": reasons,
        "ema_spread": round(ema_spread, 4),
    }


# Market state → trading parameters
MARKET_STATE_CONFIG = {
    "SLEEPING": {
        "buy_threshold": 999,    # effectively no trading
        "sell_threshold": -999,
        "position_pct": 0.0,
        "allow_trade": False,
    },
    "WAKING_UP": {
        "buy_threshold": 60,
        "sell_threshold": 40,
        "position_pct": 0.20,
        "allow_trade": True,
    },
    "ACTIVE": {
        "buy_threshold": 65,
        "sell_threshold": 35,
        "position_pct": 0.50,
        "allow_trade": True,
    },
    "BREAKOUT": {
        "buy_threshold": 55,
        "sell_threshold": 45,
        "position_pct": 0.70,
        "allow_trade": True,
    },
}


# ---------------------------------------------------------------------------
# Adaptive Decision Engine v2
# ---------------------------------------------------------------------------

def _score_ema(ema_short: float, ema_long: float) -> float:
    """EMA crossover score (0–100).

    100 = strong bullish crossover, 50 = neutral, 0 = strong bearish.
    """
    if ema_long == 0:
        return 50.0
    spread_pct = (ema_short - ema_long) / ema_long * 100
    return round(max(0, min(100, 50 + spread_pct * 100)), 2)


def _score_rsi(rsi: float) -> float:
    """RSI score (0–100). Low RSI = high score (buy opportunity)."""
    return round(max(0, min(100, 100 - rsi)), 2)


def _score_trend(slope: float, momentum: float) -> float:
    """Trend score (0–100). Uptrend = high, downtrend = low."""
    slope_score = max(0, min(100, 50 + slope * 166))
    return round(slope_score * 0.6 + momentum * 0.4, 2)


def _score_acceleration(acceleration: float) -> float:
    """Momentum acceleration score (0–100).

    Positive acceleration = bullish pressure building.
    Negative acceleration = bearish pressure building.
    """
    return round(max(0, min(100, 50 + acceleration * 0.5)), 2)


def _position_size(confidence: float) -> float:
    """Determine position size as fraction of capital based on confidence.

    Professional sizing: conviction drives size.
    0–40% conf → 0% (no trade)
    40–60%     → 10% of capital
    60–75%     → 25% of capital
    75%+       → 50% of capital

    Always capped at MAX_RISK_PCT (50%).
    """
    for low, high, pct in POSITION_TIERS:
        if low <= confidence < high:
            return min(pct, MAX_RISK_PCT)
    return 0.0


def _dynamic_thresholds(vol_regime: str) -> tuple[float, float]:
    """Adjust BUY/SELL thresholds based on volatility regime.

    High volatility: tighter thresholds (60/40) — move fast, signals are strong.
    Low volatility:  wider thresholds (70/30) — require stronger conviction.
    Normal:          base thresholds (65/35).

    Returns:
        (buy_threshold, sell_threshold)
    """
    if vol_regime == "high":
        return 60.0, 40.0
    if vol_regime == "low":
        return 70.0, 30.0
    return float(BASE_BUY_THRESHOLD), float(BASE_SELL_THRESHOLD)


def _compute_confidence(
    total_score: float,
    buy_thresh: float,
    sell_thresh: float,
    ema_score: float,
    rsi_score: float,
    trend_score: float,
    accel_score: float,
    vol_regime: str,
) -> float:
    """Refined confidence that accounts for signal agreement + volatility.

    Three components blended:
    1. Distance from nearest threshold (how decisive the score is)
    2. Signal agreement (how aligned all sub-scores are)
    3. Volatility boost (high vol = signals are more meaningful)
    """
    # 1. Distance confidence: how far past the threshold
    midpoint = (buy_thresh + sell_thresh) / 2
    half_range = (buy_thresh - sell_thresh) / 2
    dist = abs(total_score - midpoint)
    dist_conf = min(dist / (half_range + 10), 1.0)

    # 2. Agreement: all scores on same side of 50 = high agreement
    scores = [ema_score, rsi_score, trend_score, accel_score]
    bullish_count = sum(1 for s in scores if s > 55)
    bearish_count = sum(1 for s in scores if s < 45)
    max_aligned = max(bullish_count, bearish_count)
    agreement = max_aligned / len(scores)  # 0.25 to 1.0

    # 3. Volatility factor: high vol signals are more trustworthy
    vol_factor = {"high": 1.15, "normal": 1.0, "low": 0.85}[vol_regime]

    raw = (dist_conf * 0.5 + agreement * 0.5) * vol_factor
    return round(max(0.0, min(0.95, raw)), 2)


def generate_decision(price: float, indicators: dict, portfolio: dict) -> dict:
    """Generate a market-state-aware trading decision.

    Uses the 4-state market detector (SLEEPING → WAKING → ACTIVE → BREAKOUT)
    to dynamically adjust thresholds, position sizing, and aggressiveness.

    Args:
        price: Current BTC price.
        indicators: From compute_indicators().
        portfolio: Current portfolio state.

    Returns:
        Decision dict with action, confidence, score, signals, reasoning,
        market_state, why_reasons list, and meta.
    """
    ema_s = indicators["ema_short"]
    ema_l = indicators["ema_long"]
    rsi = indicators["rsi"]
    slope = indicators["slope"]
    momentum = indicators["momentum"]
    volatility = indicators["volatility"]
    vol_regime = indicators.get("vol_regime", classify_volatility(volatility))
    acceleration = indicators.get("acceleration", 0.0)
    trend = indicators["trend"]
    emerging = indicators.get("emerging_trend", "none")
    is_spike = indicators.get("is_spike", False)

    # --- Market state detection ---
    prev_state = _state["market_state"].get("state", "SLEEPING")
    mkt = detect_market_state(indicators, prev_state)
    _state["market_state"] = mkt
    market_state = mkt["state"]
    mkt_config = MARKET_STATE_CONFIG[market_state]

    # "Why" reasoning array — records every factor
    why = list(mkt["reasons"])  # start with market state reasons

    # --- Compute sub-scores ---
    ema_score = _score_ema(ema_s, ema_l)
    rsi_score = _score_rsi(rsi)
    trend_score = _score_trend(slope, momentum)
    accel_score = _score_acceleration(acceleration)

    # --- Weighted total ---
    total_score = round(
        ema_score * W_EMA + rsi_score * W_RSI
        + trend_score * W_TREND + accel_score * W_MOMENTUM,
        2,
    )

    # --- Momentum confirmation boost ---
    momentum_boost = 0.0
    if trend == "bullish" and acceleration > 10:
        momentum_boost = min(10.0, acceleration * 0.3)
        total_score = round(min(100, total_score + momentum_boost), 2)
        why.append(f"Momentum confirming bullish trend (+{momentum_boost:.1f} boost)")
    elif trend == "bearish" and acceleration < -10:
        momentum_boost = min(10.0, abs(acceleration) * 0.3)
        total_score = round(max(0, total_score - momentum_boost), 2)
        why.append(f"Momentum confirming bearish trend (-{momentum_boost:.1f} drag)")

    # --- Thresholds from market state ---
    buy_thresh = float(mkt_config["buy_threshold"])
    sell_thresh = float(mkt_config["sell_threshold"])

    # --- Confidence ---
    confidence = _compute_confidence(
        total_score, buy_thresh, sell_thresh,
        ema_score, rsi_score, trend_score, accel_score, vol_regime,
    )

    # --- Position size from market state ---
    pos_size = mkt_config["position_pct"]
    # Scale by confidence within the state's range
    if confidence > 0.7:
        pos_size = min(pos_size * 1.3, MAX_RISK_PCT)

    # --- Determine raw action ---
    btc = portfolio.get("btc_holdings", 0.0)
    cash = portfolio.get("cash", 0.0)

    if not mkt_config["allow_trade"]:
        raw_action = "HOLD"
        why.append(f"Market {market_state} — trading disabled")
    elif total_score > buy_thresh and cash > 1.0:
        raw_action = "BUY"
        why.append(f"Score {total_score:.0f} > buy threshold {buy_thresh:.0f}")
    elif total_score < sell_thresh and btc > 0.0:
        raw_action = "SELL"
        why.append(f"Score {total_score:.0f} < sell threshold {sell_thresh:.0f}")
    else:
        raw_action = "HOLD"
        why.append(f"Score {total_score:.0f} in neutral zone ({sell_thresh:.0f}–{buy_thresh:.0f})")

    # --- Apply safety filters ---
    action = raw_action
    filter_reason = ""

    # Cooldown check
    now_ts = time.time()
    since_last = now_ts - _state["last_trade_time"]
    if action != "HOLD" and since_last < COOLDOWN_SECONDS:
        remaining = int(COOLDOWN_SECONDS - since_last)
        filter_reason = f"Cooldown: {remaining}s remaining"
        action = "HOLD"
        why.append(f"Filtered: cooldown active ({remaining}s left)")

    # Never trade below 20% confidence (safety rule)
    if action != "HOLD" and confidence < 0.20:
        filter_reason = f"Confidence too low ({confidence:.0%} < 20%)"
        action = "HOLD"
        why.append(f"Filtered: confidence {confidence:.0%} below safety floor")

    # Max 1 position — don't buy if already holding
    if action == "BUY" and btc > 0.0001:
        filter_reason = "Already in position — max 1 at a time"
        action = "HOLD"
        why.append("Filtered: already holding BTC")

    # --- Build trader-style reasoning ---
    parts = []

    # Market state context
    state_voice = {
        "SLEEPING": "Dead quiet. Market sleeping. No edge.",
        "WAKING_UP": "Market stirring. Volatility rising. Getting ready.",
        "ACTIVE": "Market alive. Clear signals. Time to act.",
        "BREAKOUT": "Explosive move! All signals firing. Full send.",
    }
    parts.append(state_voice.get(market_state, "Unknown state."))

    # Signal commentary
    if ema_score > 65:
        parts.append("Buyers stepping in.")
        why.append("EMA bullish crossover")
    elif ema_score < 35:
        parts.append("Sellers in control.")
        why.append("EMA bearish crossover")

    if rsi > 70:
        parts.append("Stretched thin. Pullback risk.")
        why.append(f"RSI overbought at {rsi:.0f}")
    elif rsi < 30:
        parts.append("Deeply oversold. Snapback likely.")
        why.append(f"RSI oversold at {rsi:.0f}")

    if trend == "bullish" and acceleration > 10:
        parts.append("Trend accelerating.")
    elif trend == "bearish" and acceleration < -10:
        parts.append("Selling intensifying.")

    # Decision reasoning
    if action == "BUY":
        parts.append(f"Taking the long. Score {total_score:.0f}, {market_state} mode.")
        why.append(f"BUY executed at score {total_score:.0f}")
    elif action == "SELL":
        parts.append(f"Exiting position. Score {total_score:.0f}, {market_state} mode.")
        why.append(f"SELL executed at score {total_score:.0f}")
    elif filter_reason:
        if "Cooldown" in filter_reason:
            parts.append("Signal fired but cooling off.")
        elif "position" in filter_reason.lower():
            parts.append("Already in a trade. Holding.")
        elif "Confidence" in filter_reason:
            parts.append("Not enough conviction. Passing.")
        else:
            parts.append(f"Skipped: {filter_reason}")
        why.append(f"Trade filtered: {filter_reason}")
    elif market_state == "SLEEPING":
        parts.append("Sitting out. No setups in dead market.")
        why.append("No trade: market SLEEPING")
    else:
        parts.append(f"Score {total_score:.0f}. Waiting for cleaner setup.")
        why.append(f"Score in neutral zone ({sell_thresh:.0f}–{buy_thresh:.0f})")

    # Sizing context
    if action != "HOLD" and pos_size > 0:
        parts.append(f"Size: {pos_size:.0%} of capital.")
        why.append(f"Position size: {pos_size:.0%} ({market_state} mode)")

    reasoning = " ".join(parts)

    return {
        "action": action,
        "confidence": confidence,
        "score": total_score,
        "position_size": round(pos_size, 2),
        "market_state": mkt,
        "signals": {
            "ema": round(ema_score, 1),
            "rsi": round(rsi_score, 1),
            "trend": round(trend_score, 1),
            "momentum": round(accel_score, 1),
        },
        "reasoning": reasoning,
        "why": why,
        "price": price,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "meta": {
            "vol_regime": vol_regime,
            "buy_threshold": buy_thresh,
            "sell_threshold": sell_thresh,
            "momentum_boost": round(momentum_boost, 1),
            "is_spike": is_spike,
            "emerging_trend": emerging,
        },
    }


# ---------------------------------------------------------------------------
# Trade Execution (Paper Only)
# ---------------------------------------------------------------------------

def load_auto_portfolio(user_id: str) -> dict:
    """Load the auto-trading portfolio for a user."""
    path = get_user_file(user_id, "auto_portfolio.json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "cash": INITIAL_BALANCE,
            "btc_holdings": 0.0,
            "total_trades": 0,
            "realized_pnl": 0.0,
            "avg_entry_price": 0.0,
        }


def save_auto_portfolio(user_id: str, portfolio: dict) -> None:
    """Save the auto-trading portfolio."""
    path = get_user_file(user_id, "auto_portfolio.json")
    path.write_text(json.dumps(portfolio, indent=2) + "\n", encoding="utf-8")


def execute_trade(decision: dict, portfolio: dict) -> dict:
    """Execute a paper trade. Position size driven by confidence tiers."""
    action = decision["action"]
    price = decision["price"]
    pos_size = decision.get("position_size", 0.10)
    result = {"action": "HOLD", "price": price, "quantity": 0.0, "pnl": 0.0, "reason": ""}

    if pos_size <= 0 and action != "HOLD":
        result["reason"] = "Confidence too low for any position. Standing aside."
        return result

    if action == "BUY" and portfolio["cash"] > 1.0:
        pct = min(pos_size, MAX_RISK_PCT)
        spend = portfolio["cash"] * pct
        qty = spend / price

        portfolio["cash"] -= spend
        total_btc = portfolio["btc_holdings"] + qty
        if total_btc > 0:
            old_cost = portfolio["btc_holdings"] * portfolio["avg_entry_price"]
            portfolio["avg_entry_price"] = (old_cost + qty * price) / total_btc
        portfolio["btc_holdings"] = total_btc
        portfolio["total_trades"] += 1
        _state["last_trade_time"] = time.time()

        result["action"] = "BUY"
        result["quantity"] = qty
        result["reason"] = f"Bought {qty:.6f} BTC at ${price:,.2f} (spent ${spend:.2f})"

    elif action == "SELL" and portfolio["btc_holdings"] > 0:
        pct = min(pos_size, MAX_RISK_PCT)
        qty = portfolio["btc_holdings"] * pct
        revenue = qty * price
        pnl = (price - portfolio["avg_entry_price"]) * qty

        portfolio["cash"] += revenue
        portfolio["btc_holdings"] -= qty
        portfolio["realized_pnl"] += pnl
        portfolio["total_trades"] += 1
        _state["last_trade_time"] = time.time()

        if portfolio["btc_holdings"] < 1e-10:
            portfolio["btc_holdings"] = 0.0
            portfolio["avg_entry_price"] = 0.0

        result["action"] = "SELL"
        result["quantity"] = qty
        result["pnl"] = pnl
        result["reason"] = f"Sold {qty:.6f} BTC at ${price:,.2f} (P&L ${pnl:.4f})"

    else:
        result["reason"] = "Holding — no action taken."

    return result


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

AUTO_TRADE_FIELDS = ["timestamp", "action", "price", "quantity", "pnl", "cash_after", "btc_after", "confidence", "score", "signals"]
AUTO_EQUITY_FIELDS = ["timestamp", "price", "cash", "btc_holdings", "total_equity"]


def log_auto_trade(user_id: str, decision: dict, result: dict, portfolio: dict) -> None:
    """Append a trade to auto_trades.csv."""
    path = get_user_file(user_id, "auto_trades.csv")
    if not path.exists():
        with open(path, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=AUTO_TRADE_FIELDS).writeheader()

    signals = decision.get("signals", {})
    signals_str = f"ema:{signals.get('ema',0)}|rsi:{signals.get('rsi',0)}|trend:{signals.get('trend',0)}"

    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": result["action"],
        "price": decision["price"],
        "quantity": round(result["quantity"], 8),
        "pnl": round(result["pnl"], 6),
        "cash_after": round(portfolio["cash"], 4),
        "btc_after": round(portfolio["btc_holdings"], 8),
        "confidence": decision["confidence"],
        "score": decision.get("score", 0),
        "signals": signals_str,
    }

    with open(path, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=AUTO_TRADE_FIELDS).writerow(row)


def log_auto_equity(user_id: str, price: float, portfolio: dict) -> None:
    """Append an equity snapshot."""
    path = get_user_file(user_id, "auto_equity.csv")
    if not path.exists():
        with open(path, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=AUTO_EQUITY_FIELDS).writeheader()

    equity = portfolio["cash"] + portfolio["btc_holdings"] * price
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "price": round(price, 2),
        "cash": round(portfolio["cash"], 4),
        "btc_holdings": round(portfolio["btc_holdings"], 8),
        "total_equity": round(equity, 4),
    }

    with open(path, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=AUTO_EQUITY_FIELDS).writerow(row)


# ---------------------------------------------------------------------------
# Trade Journal
# ---------------------------------------------------------------------------

JOURNAL_FILE_NAME = "trade_journal.json"


def _load_journal(user_id: str) -> list[dict]:
    """Load the trade journal from disk."""
    path = get_user_file(user_id, JOURNAL_FILE_NAME)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_journal(user_id: str, journal: list[dict]) -> None:
    """Save the trade journal. Keeps the last 500 entries."""
    if len(journal) > 500:
        journal = journal[-500:]
    path = get_user_file(user_id, JOURNAL_FILE_NAME)
    path.write_text(json.dumps(journal, indent=2) + "\n", encoding="utf-8")


def log_journal_entry(
    user_id: str,
    decision: dict,
    result: dict,
    indicators: dict,
    portfolio: dict,
    price: float,
) -> None:
    """Write one journal entry capturing the full context of a cycle.

    Every cycle is logged — BUY, SELL, and HOLD — so the journal
    records the AI's reasoning even when it chose not to act.
    For BUY/SELL entries, the outcome (pnl) is recorded immediately.
    HOLD entries get outcome=null (they didn't produce a trade).

    Args:
        user_id: User whose journal to write.
        decision: From generate_decision().
        result: From execute_trade().
        indicators: From compute_indicators().
        portfolio: Portfolio state after execution.
        price: Current BTC price.
    """
    journal = _load_journal(user_id)

    equity = portfolio["cash"] + portfolio["btc_holdings"] * price

    signals = decision.get("signals", {})
    meta = decision.get("meta", {})
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cycle": _state["cycle_count"],
        "price": round(price, 2),
        "decision": {
            "action": decision["action"],
            "score": decision.get("score", 0),
            "confidence": decision.get("confidence", 0),
            "reasoning": decision.get("reasoning", ""),
        },
        "why": decision.get("why", []),
        "signals": {
            "ema_score": signals.get("ema", 50),
            "rsi_score": signals.get("rsi", 50),
            "trend_score": signals.get("trend", 50),
            "accel_score": signals.get("momentum", 50),
        },
        "indicators": {
            "ema_short": indicators.get("ema_short", 0),
            "ema_long": indicators.get("ema_long", 0),
            "rsi": indicators.get("rsi", 50),
            "trend": indicators.get("trend", "unknown"),
            "slope": indicators.get("slope", 0),
            "momentum": indicators.get("momentum", 50),
            "volatility": indicators.get("volatility", 0),
            "acceleration": indicators.get("acceleration", 0),
            "vol_regime": indicators.get("vol_regime", "unknown"),
            "emerging_trend": indicators.get("emerging_trend", "none"),
            "is_spike": indicators.get("is_spike", False),
        },
        "adaptive": {
            "vol_regime": meta.get("vol_regime", "unknown"),
            "buy_threshold": meta.get("buy_threshold", BASE_BUY_THRESHOLD),
            "sell_threshold": meta.get("sell_threshold", BASE_SELL_THRESHOLD),
            "momentum_boost": meta.get("momentum_boost", 0),
            "is_early_entry": meta.get("is_early_entry", False),
        },
        "execution": {
            "action_taken": result["action"],
            "quantity": round(result.get("quantity", 0), 8),
            "pnl": round(result.get("pnl", 0), 6),
            "reason": result.get("reason", ""),
        },
        "portfolio_after": {
            "cash": round(portfolio["cash"], 4),
            "btc_holdings": round(portfolio["btc_holdings"], 8),
            "equity": round(equity, 4),
            "realized_pnl": round(portfolio["realized_pnl"], 4),
        },
    }

    journal.append(entry)
    _save_journal(user_id, journal)


def get_journal(user_id: str, limit: int = 50) -> list[dict]:
    """Read journal entries for analysis.

    Args:
        user_id: User whose journal to read.
        limit: Max entries to return (most recent first).

    Returns:
        List of journal entry dicts, newest first.
    """
    journal = _load_journal(user_id)
    return journal[-limit:][::-1]


def get_journal_summary(user_id: str) -> dict:
    """Compute summary stats from the journal for strategy analysis.

    Returns:
        dict with total_cycles, action counts, avg score per action,
        win/loss stats, and top signals.
    """
    journal = _load_journal(user_id)
    if not journal:
        return {"total_cycles": 0}

    actions = {"BUY": 0, "SELL": 0, "HOLD": 0}
    scores_by_action = {"BUY": [], "SELL": [], "HOLD": []}
    wins = 0
    losses = 0
    total_pnl = 0.0

    for entry in journal:
        act = entry.get("execution", {}).get("action_taken", "HOLD")
        score = entry.get("decision", {}).get("score", 50)
        pnl = entry.get("execution", {}).get("pnl", 0)

        actions[act] = actions.get(act, 0) + 1
        scores_by_action.setdefault(act, []).append(score)

        if act in ("BUY", "SELL") and pnl != 0:
            total_pnl += pnl
            if pnl > 0:
                wins += 1
            elif pnl < 0:
                losses += 1

    avg_scores = {}
    for act, scores in scores_by_action.items():
        if scores:
            avg_scores[act] = round(sum(scores) / len(scores), 1)

    return {
        "total_cycles": len(journal),
        "actions": actions,
        "avg_score_by_action": avg_scores,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / (wins + losses) * 100, 1) if (wins + losses) > 0 else 0,
        "total_pnl": round(total_pnl, 6),
        "first_entry": journal[0]["timestamp"] if journal else None,
        "last_entry": journal[-1]["timestamp"] if journal else None,
    }


# ---------------------------------------------------------------------------
# Auto Loop
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Session Insight Generator
# ---------------------------------------------------------------------------

def _dominant(items: list[str]) -> str:
    """Return the most frequent item in a list."""
    if not items:
        return "unknown"
    counts: dict[str, int] = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return max(counts, key=counts.get)  # type: ignore[arg-type]


def _generate_session_insight() -> str:
    """Generate a trader-style session summary from recent activity.

    Reads from _state session tracking fields and produces a 2–3 sentence
    commentary that sounds like an experienced trader recapping the session.
    """
    cycles = _state["session_cycles"]
    taken = _state["session_trades_taken"]
    avoided = _state["session_trades_avoided"]
    buys = _state["session_buys"]
    sells = _state["session_sells"]
    holds = _state["session_holds"]

    dom_vol = _dominant(_state["session_vol_regimes"])
    dom_trend = _dominant(_state["session_trends"])

    scores = _state["session_scores"]
    avg_score = sum(scores) / len(scores) if scores else 50.0

    parts = []

    # Market condition
    if dom_trend == "bullish" and dom_vol == "high":
        parts.append("Volatile rally in play. Sharp moves, fast decisions.")
    elif dom_trend == "bullish":
        parts.append("Market leaning bullish. Steady bid underneath.")
    elif dom_trend == "bearish" and dom_vol == "high":
        parts.append("Aggressive selling. High volatility, heavy pressure.")
    elif dom_trend == "bearish":
        parts.append("Bearish drift. Sellers in no rush but in control.")
    elif dom_vol == "low":
        parts.append("Dead quiet session. No real movement to speak of.")
    elif dom_vol == "high":
        parts.append("Choppy action. Lots of noise, no clear direction.")
    else:
        parts.append("Market ranging sideways. No dominant trend.")

    # Trade activity
    if taken == 0 and avoided == 0:
        parts.append("No signals fired. System stayed completely flat.")
    elif taken == 0 and avoided > 0:
        parts.append(
            f"Filtered {avoided} signal{'s' if avoided != 1 else ''} — "
            f"none met the bar. Discipline kept us out."
        )
    elif taken > 0 and avoided == 0:
        parts.append(
            f"Executed {taken} trade{'s' if taken != 1 else ''} "
            f"({buys}B/{sells}S). Clean setups, no filters triggered."
        )
    else:
        parts.append(
            f"{taken} trade{'s' if taken != 1 else ''} taken, "
            f"{avoided} avoided. Selective execution."
        )

    # Overall stance
    if avg_score > 60:
        parts.append("Bias leans bullish. Watching for continuation.")
    elif avg_score < 40:
        parts.append("Bearish undertone. Defensive posture.")
    elif taken == 0:
        parts.append("No edge found. Patience is the position.")
    else:
        parts.append("Mixed signals. Staying nimble, no strong conviction.")

    return " ".join(parts)


def get_session_insight() -> dict:
    """Return the current session insight for the API."""
    # If no insight generated yet, create one now
    if not _state["session_insight"] and _state["session_cycles"] > 0:
        _state["session_insight"] = _generate_session_insight()
        _state["session_insight_time"] = datetime.now(timezone.utc).isoformat()
        _state["last_insight_cycle"] = _state["cycle_count"]

    return {
        "insight": _state["session_insight"],
        "generated_at": _state["session_insight_time"],
        "session_stats": {
            "cycles": _state["session_cycles"],
            "trades_taken": _state["session_trades_taken"],
            "trades_avoided": _state["session_trades_avoided"],
            "buys": _state["session_buys"],
            "sells": _state["session_sells"],
            "holds": _state["session_holds"],
            "dominant_trend": _dominant(_state["session_trends"]),
            "dominant_vol": _dominant(_state["session_vol_regimes"]),
            "avg_score": round(
                sum(_state["session_scores"]) / len(_state["session_scores"]), 1
            ) if _state["session_scores"] else 50.0,
        },
    }


# ---------------------------------------------------------------------------
# Auto Loop
# ---------------------------------------------------------------------------

def run_cycle(user_id: str = "admin") -> dict:
    """Run one full autonomous trading cycle."""
    _state["error"] = None

    price = get_live_price()
    if price <= 0:
        return {"error": _state["error"]}

    _state["last_price"] = price
    _state["price_history"].append(price)
    if len(_state["price_history"]) > MAX_HISTORY:
        _state["price_history"] = _state["price_history"][-MAX_HISTORY:]

    indicators = compute_indicators(_state["price_history"])
    _state["indicators"] = indicators

    portfolio = load_auto_portfolio(user_id)
    decision = generate_decision(price, indicators, portfolio)
    _state["last_decision"] = decision

    result = execute_trade(decision, portfolio)

    save_auto_portfolio(user_id, portfolio)
    log_auto_trade(user_id, decision, result, portfolio)
    log_auto_equity(user_id, price, portfolio)
    log_journal_entry(user_id, decision, result, indicators, portfolio, price)

    _state["last_update"] = datetime.now(timezone.utc).isoformat()
    _state["cycle_count"] += 1

    # --- Session tracking ---
    _state["session_cycles"] += 1
    act = result["action"]
    raw_act = decision["action"]
    if act in ("BUY", "SELL"):
        _state["session_trades_taken"] += 1
        if act == "BUY":
            _state["session_buys"] += 1
        else:
            _state["session_sells"] += 1
    elif raw_act != "HOLD" and act == "HOLD":
        # Signal was generated but filtered out
        _state["session_trades_avoided"] += 1
    else:
        _state["session_holds"] += 1

    vol_regime = indicators.get("vol_regime", "unknown")
    trend = indicators.get("trend", "sideways")
    score = decision.get("score", 50)
    _state["session_vol_regimes"].append(vol_regime)
    _state["session_trends"].append(trend)
    _state["session_scores"].append(score)
    # Keep only last 30 for rolling window
    for key in ("session_vol_regimes", "session_trends", "session_scores"):
        if len(_state[key]) > 30:
            _state[key] = _state[key][-30:]

    # Generate insight every N cycles
    since_last_insight = _state["cycle_count"] - _state["last_insight_cycle"]
    if since_last_insight >= INSIGHT_INTERVAL_CYCLES:
        _state["session_insight"] = _generate_session_insight()
        _state["session_insight_time"] = datetime.now(timezone.utc).isoformat()
        _state["last_insight_cycle"] = _state["cycle_count"]

    return {
        "price": price,
        "decision": decision,
        "result": result,
        "portfolio": portfolio,
        "indicators": indicators,
    }


def _loop(user_id: str) -> None:
    """Background loop."""
    while _state["running"]:
        try:
            cycle = run_cycle(user_id)
            price = cycle.get("price", 0)
            dec = cycle.get("decision", {})
            print(f"[auto_trader] #{_state['cycle_count']} "
                  f"BTC=${price:,.2f} → {dec.get('action','?')} "
                  f"(score={dec.get('score',0)} conf={dec.get('confidence',0):.0%}) "
                  f"cash=${cycle.get('portfolio',{}).get('cash',0):.2f}")
        except Exception as e:
            print(f"[auto_trader] Cycle error: {e}")
            _state["error"] = str(e)
        time.sleep(LOOP_INTERVAL)


def start(user_id: str = "admin") -> dict:
    """Start the autonomous trading loop."""
    if _state["running"]:
        return {"status": "already_running", "cycles": _state["cycle_count"]}

    _state["running"] = True
    _state["cycle_count"] = 0
    _state["error"] = None
    _state["last_trade_time"] = 0
    # Reset session tracking
    _state["session_start"] = time.time()
    _state["session_cycles"] = 0
    _state["session_trades_taken"] = 0
    _state["session_trades_avoided"] = 0
    _state["session_holds"] = 0
    _state["session_buys"] = 0
    _state["session_sells"] = 0
    _state["session_vol_regimes"] = []
    _state["session_trends"] = []
    _state["session_scores"] = []
    _state["session_insight"] = ""
    _state["session_insight_time"] = ""
    _state["last_insight_cycle"] = 0

    run_cycle(user_id)

    t = threading.Thread(target=_loop, args=(user_id,), daemon=True)
    t.start()
    _state["thread"] = t

    return {"status": "started", "interval": LOOP_INTERVAL}


def stop() -> dict:
    """Stop the autonomous trading loop."""
    if not _state["running"]:
        return {"status": "not_running"}
    _state["running"] = False
    return {"status": "stopped", "total_cycles": _state["cycle_count"]}


def get_state() -> dict:
    """Get the current auto-trader state for the API."""
    portfolio = load_auto_portfolio("admin")
    price = _state["last_price"]
    equity = portfolio["cash"] + portfolio["btc_holdings"] * price if price > 0 else portfolio["cash"]

    # Cooldown info
    since_last = time.time() - _state["last_trade_time"]
    cooldown_remaining = max(0, int(COOLDOWN_SECONDS - since_last))

    # Extract adaptive engine meta from last decision
    last_dec = _state["last_decision"] or {}
    meta = last_dec.get("meta", {})

    return {
        "running": _state["running"],
        "cycle_count": _state["cycle_count"],
        "last_price": _state["last_price"],
        "last_update": _state["last_update"],
        "last_decision": _state["last_decision"],
        "indicators": _state["indicators"],
        "cooldown_remaining": cooldown_remaining,
        "error": _state["error"],
        "portfolio": {
            "cash": round(portfolio["cash"], 4),
            "btc_holdings": round(portfolio["btc_holdings"], 8),
            "total_equity": round(equity, 4),
            "realized_pnl": round(portfolio["realized_pnl"], 4),
            "total_trades": portfolio["total_trades"],
            "avg_entry_price": round(portfolio["avg_entry_price"], 2),
        },
        "adaptive": {
            "vol_regime": meta.get("vol_regime", "unknown"),
            "buy_threshold": meta.get("buy_threshold", BASE_BUY_THRESHOLD),
            "sell_threshold": meta.get("sell_threshold", BASE_SELL_THRESHOLD),
            "momentum_boost": meta.get("momentum_boost", 0),
            "is_spike": meta.get("is_spike", False),
            "emerging_trend": meta.get("emerging_trend", "none"),
        },
        "market_state": _state["market_state"],
        "session_insight": get_session_insight(),
    }
