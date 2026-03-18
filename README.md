# BTC/USDT Paper Trader

AI-powered multi-asset paper trading system using Claude as the decision engine. Features a FastAPI backend, React frontend, reinforcement learning, strategy optimization, and multi-user support.

---

## Quick Start (Local)

### Prerequisites

- Python 3.9+
- Node.js 18+
- npm

### 1. Clone and enter the project

```bash
cd ~/Desktop/CryptoMind/btc-paper-trader
```

### 2. Backend setup

```bash
# Install Python dependencies
pip install -r requirements.txt

# Create environment file (only needed once)
cp .env.example .env
```

Edit `.env` if you want to change defaults. The app works without an Anthropic API key for browsing the dashboard — you only need it for live trading cycles.

```bash
# Start the backend
python3 run_api.py
```

You should see:

```
[INFO] Starting API server on http://127.0.0.1:8000
[INFO] Docs at http://127.0.0.1:8000/docs
[api] Seeded admin with demo data: 8 trades, 81 equity points
INFO: Uvicorn running on http://127.0.0.1:8000
```

Verify it works:

```
http://127.0.0.1:8000/docs
```

### 3. Frontend setup (new terminal)

```bash
cd ~/Desktop/CryptoMind/btc-paper-trader/frontend

# Install Node dependencies
npm install

# Start the dev server
npm run dev
```

You should see:

```
VITE v5.x.x  ready in XXX ms
  ➜  Local:   http://localhost:3000/
```

### 4. Open the app

```
http://localhost:3000
```

Login credentials:

```
Username: admin
Password: changeme
```

The app comes pre-seeded with demo data — you'll see trades, charts, and strategies immediately.

---

## URLs

| Service | URL |
|---------|-----|
| Frontend (React) | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| API Docs (Swagger) | http://localhost:8000/docs |
| API Docs (ReDoc) | http://localhost:8000/redoc |

---

## Project Structure

```
btc-paper-trader/
├── app/                    # Python backend
│   ├── api.py              # FastAPI endpoints
│   ├── auth.py             # JWT authentication
│   ├── main.py             # Trading cycle orchestrator
│   ├── config.py           # Configuration and constants
│   ├── data_fetcher.py     # Market data from Binance via ccxt
│   ├── indicators.py       # EMA, RSI, trend detection
│   ├── regime_detector.py  # Market regime classification
│   ├── anomaly_detector.py # Spike/volatility detection
│   ├── prompt_builder.py   # Claude prompt construction
│   ├── claude_client.py    # Anthropic API client
│   ├── decision_engine.py  # Multi-bot signal combiner
│   ├── meta_engine.py      # Rules + RL + history blender
│   ├── paper_broker.py     # Simulated broker with risk guards
│   ├── portfolio_manager.py# Multi-asset capital allocation
│   ├── logger.py           # CSV trade/decision logging
│   ├── alerts.py           # Telegram notifications
│   ├── performance.py      # Daily metrics
│   ├── review_engine.py    # Post-trade Claude review
│   ├── strategy_store.py   # Strategy persistence + ranking
│   ├── strategy_advisor.py # Claude strategy analysis
│   ├── strategy_runner.py  # Multi-config backtesting
│   ├── optimizer.py        # Evolutionary optimizer
│   ├── backtester.py       # Historical backtesting
│   ├── visualizer.py       # Matplotlib charts
│   ├── rl_agent.py         # Q-learning agent
│   ├── experience_store.py # RL experience persistence
│   ├── evaluator.py        # Weekly system evaluation
│   ├── research_report.py  # Claude research reports
│   ├── replay.py           # Trade replay debugger
│   ├── user_manager.py     # Multi-user accounts
│   ├── seed_data.py        # Demo data generator
│   ├── dashboard.py        # Streamlit dashboard (standalone)
│   └── scheduler.py        # Hourly trading loop
├── frontend/               # React frontend
│   ├── src/
│   │   ├── pages/          # Dashboard, Trades, Performance
│   │   ├── components/     # Charts, tables, status displays
│   │   └── hooks/          # useApi data fetching
│   ├── package.json
│   └── vite.config.js
├── data/                   # Persisted data (gitignored)
├── prompts/                # Claude system prompts
├── run_api.py              # Backend entry point
├── requirements.txt        # Python dependencies
├── Dockerfile              # Backend container
├── docker-compose.yml      # Full stack containers
└── .env                    # Environment variables (not committed)
```

---

## Environment Variables

Key variables in `.env`:

```bash
# Required for live trading (optional for UI browsing)
ANTHROPIC_API_KEY=your-key-here

# Auth (change in production)
API_USERNAME=admin
API_PASSWORD=changeme
JWT_SECRET=local-dev-secret-change-in-prod

# CORS
CORS_ORIGINS=http://localhost:3000
```

The frontend reads its API URL from `frontend/.env.local`:

```bash
VITE_API_URL=http://localhost:8000
```

---

## Running Individual Tools

These work standalone without the frontend:

```bash
cd btc-paper-trader

# Run a backtest (no API key needed)
python3 app/backtester.py

# Run the strategy optimizer
python3 app/strategy_runner.py

# Run the evolutionary optimizer
python3 app/optimizer.py

# Replay past trades
python3 app/replay.py
python3 app/replay.py --last 5
python3 app/replay.py --step

# Generate a research report (needs API key)
python3 app/research_report.py

# Run the weekly evaluator (needs API key)
python3 app/evaluator.py

# Start the Streamlit dashboard
streamlit run app/dashboard.py
```

---

## Docker

```bash
# Build and start everything
cp .env.example .env   # fill in your keys
./start.sh --build

# Or manually
docker-compose up --build

# Stop
./start.sh --down
```

Frontend: http://localhost:3000
Backend: http://localhost:8000

---

## Troubleshooting

### Port already in use

```
ERROR: address already in use
```

Find and kill the process:

```bash
# Find what's on port 8000
lsof -i :8000
# Kill it
kill -9 <PID>

# Or use a different port
python3 run_api.py --port 8001
```

For the frontend:

```bash
# Find what's on port 3000
lsof -i :3000
kill -9 <PID>

# Or change in vite.config.js: server.port
```

### Missing Python packages

```
ModuleNotFoundError: No module named 'ccxt'
```

```bash
pip install -r requirements.txt
```

If using Python 3 explicitly:

```bash
pip3 install -r requirements.txt
# or
python3 -m pip install -r requirements.txt
```

### Missing Node modules

```
Error: Cannot find module 'react'
```

```bash
cd frontend
rm -rf node_modules
npm install
```

### Backend not responding

**Symptom:** Frontend shows "Backend Unavailable" or "Cannot connect to backend."

1. Check if the backend is running:

```bash
curl http://localhost:8000/docs
```

2. If not running, start it:

```bash
python3 run_api.py
```

3. Check for startup errors in the terminal. Common issues:
   - Missing `.env` file: `cp .env.example .env`
   - Missing packages: `pip install -r requirements.txt`
   - Port conflict: `python3 run_api.py --port 8001`

4. If using a different port, update `frontend/.env.local`:

```
VITE_API_URL=http://localhost:8001
```

Then restart the frontend: `npm run dev`

### Frontend stuck on loading

**Symptom:** Spinner never goes away, or page shows "Loading..." forever.

1. Open browser DevTools (F12) → Console tab. Look for red errors.

2. If you see CORS errors:
   - Make sure the backend is running on port 8000
   - Check that `.env` has `CORS_ORIGINS=http://localhost:3000`
   - Restart the backend after changing `.env`

3. If you see "Failed to fetch":
   - Backend is not running. Start it with `python3 run_api.py`

4. If the login page works but dashboard doesn't load:
   - Clear browser localStorage: DevTools → Application → Local Storage → Clear
   - Refresh the page

5. If the app shows "Backend Unavailable" with a Retry button:
   - Start the backend, then click Retry

### Login not working

**Symptom:** "Invalid username or password" with correct credentials.

```bash
# Reset: delete the users file and restart
rm data/users.json
python3 run_api.py
# Default admin/changeme will be recreated
```

### No data showing (empty charts/tables)

The app auto-seeds demo data on first startup. If you see empty states:

```bash
# Manually trigger seeding via API
curl -X POST http://localhost:8000/seed \
  -H "Authorization: Bearer YOUR_TOKEN"
```

Or reset and restart:

```bash
rm -rf data/users/admin
python3 run_api.py
# Demo data will be re-seeded
```
