"""
dashboard.py - Streamlit dashboard for the BTC/USDT paper trader.

Run with: streamlit run app/dashboard.py

Shows:
- Portfolio summary (cash, position, equity, P&L)
- Open position details
- Equity curve chart
- Recent trades table
"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Ensure app/ is importable when running via `streamlit run app/dashboard.py`
APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from config import DATA_DIR, SYMBOL
from paper_broker import load_portfolio, EQUITY_FILE
from logger import TRADES_FILE

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(page_title="BTC Paper Trader", layout="wide")
st.title("BTC/USDT Paper Trader")


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

@st.cache_data(ttl=30)
def load_equity() -> pd.DataFrame:
    """Load the equity curve CSV into a DataFrame."""
    if not EQUITY_FILE.exists():
        return pd.DataFrame()

    df = pd.read_csv(EQUITY_FILE)
    if df.empty:
        return df

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


@st.cache_data(ttl=30)
def load_trades() -> pd.DataFrame:
    """Load the trades CSV into a DataFrame."""
    if not TRADES_FILE.exists():
        return pd.DataFrame()

    df = pd.read_csv(TRADES_FILE)
    if df.empty:
        return df

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


# ---------------------------------------------------------------------------
# Portfolio summary
# ---------------------------------------------------------------------------

portfolio = load_portfolio()
equity_df = load_equity()
trades_df = load_trades()

# Compute live values
cash = portfolio.get("cash", 0.0)
position_size = portfolio.get("position_size", 0.0)
entry_price = portfolio.get("entry_price", 0.0)
realized_pnl = portfolio.get("realized_pnl", 0.0)
position_open = portfolio.get("position_open", False)

# Get latest equity or fall back to cash
if not equity_df.empty:
    latest = equity_df.iloc[-1]
    total_equity = latest["total_equity"]
    unrealized_pnl = latest["unrealized_pnl"]
    last_price = latest["price"]
else:
    total_equity = cash
    unrealized_pnl = 0.0
    last_price = 0.0

st.header("Portfolio")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Equity", f"${total_equity:,.4f}")
col2.metric("Cash", f"${cash:,.4f}")
col3.metric("Realized P&L", f"${realized_pnl:,.4f}")
col4.metric("Unrealized P&L", f"${unrealized_pnl:,.4f}")

# ---------------------------------------------------------------------------
# Open position
# ---------------------------------------------------------------------------

st.header("Open Position")

if position_open:
    pcol1, pcol2, pcol3 = st.columns(3)
    pcol1.metric("Size", f"{position_size:.6f} BTC")
    pcol2.metric("Entry Price", f"${entry_price:,.2f}")
    pcol3.metric("Last Price", f"${last_price:,.2f}")
else:
    st.info("No open position.")

# ---------------------------------------------------------------------------
# Equity curve
# ---------------------------------------------------------------------------

st.header("Equity Curve")

if not equity_df.empty and len(equity_df) > 1:
    chart_data = equity_df.set_index("timestamp")[["total_equity"]]
    st.line_chart(chart_data)
else:
    st.info("Not enough data to plot. Run a few trading cycles first.")

# ---------------------------------------------------------------------------
# Recent trades
# ---------------------------------------------------------------------------

st.header("Recent Trades")

if not trades_df.empty:
    display_cols = [
        "timestamp", "action", "price", "quantity",
        "pnl", "strategy", "strength", "market_condition",
    ]
    # Only show columns that exist
    display_cols = [c for c in display_cols if c in trades_df.columns]
    recent = trades_df.tail(20).iloc[::-1][display_cols]
    st.dataframe(recent, use_container_width=True, hide_index=True)
else:
    st.info("No trades yet.")
