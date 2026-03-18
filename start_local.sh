#!/bin/bash
# ============================================================
# start_local.sh — Start backend + frontend for local dev
#
# Usage:
#   chmod +x start_local.sh
#   ./start_local.sh          start both services
#   ./start_local.sh --stop   stop both services
# ============================================================

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PID_FILE="$DIR/.backend.pid"
FRONTEND_PID_FILE="$DIR/.frontend.pid"

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
NC='\033[0m'

# ----------------------------------------------------------
# Stop mode
# ----------------------------------------------------------
if [ "$1" = "--stop" ]; then
    echo -e "${BLUE}Stopping services...${NC}"
    if [ -f "$BACKEND_PID_FILE" ]; then
        kill "$(cat "$BACKEND_PID_FILE")" 2>/dev/null && echo "  Backend stopped." || echo "  Backend was not running."
        rm -f "$BACKEND_PID_FILE"
    fi
    if [ -f "$FRONTEND_PID_FILE" ]; then
        kill "$(cat "$FRONTEND_PID_FILE")" 2>/dev/null && echo "  Frontend stopped." || echo "  Frontend was not running."
        rm -f "$FRONTEND_PID_FILE"
    fi
    exit 0
fi

# ----------------------------------------------------------
# Header
# ----------------------------------------------------------
echo ""
echo -e "${BLUE}=========================================${NC}"
echo -e "${BLUE}  BTC Paper Trader — Local Dev Launcher${NC}"
echo -e "${BLUE}=========================================${NC}"
echo ""

# ----------------------------------------------------------
# 1. Check dependencies
# ----------------------------------------------------------
echo -e "${BLUE}[1/4] Checking dependencies...${NC}"

MISSING=0

if ! command -v python3 &>/dev/null; then
    echo -e "  ${RED}✗ python3 not found${NC}"
    MISSING=1
else
    echo -e "  ${GREEN}✓ python3  $(python3 --version 2>&1 | awk '{print $2}')${NC}"
fi

if ! command -v node &>/dev/null; then
    echo -e "  ${RED}✗ node not found — install from https://nodejs.org${NC}"
    MISSING=1
else
    echo -e "  ${GREEN}✓ node     $(node --version)${NC}"
fi

if ! command -v npm &>/dev/null; then
    echo -e "  ${RED}✗ npm not found${NC}"
    MISSING=1
else
    echo -e "  ${GREEN}✓ npm      $(npm --version)${NC}"
fi

if [ $MISSING -eq 1 ]; then
    echo -e "\n  ${RED}Install missing dependencies and re-run.${NC}"
    exit 1
fi

# Check Python packages
if ! python3 -c "import fastapi, uvicorn, ccxt, pandas" 2>/dev/null; then
    echo -e "  ${YELLOW}! Python packages missing — installing...${NC}"
    pip3 install -r "$DIR/requirements.txt" --quiet
    echo -e "  ${GREEN}✓ Python packages installed${NC}"
else
    echo -e "  ${GREEN}✓ Python packages OK${NC}"
fi

# Check Node modules
if [ ! -d "$DIR/frontend/node_modules" ]; then
    echo -e "  ${YELLOW}! node_modules missing — installing...${NC}"
    cd "$DIR/frontend" && npm install --silent
    echo -e "  ${GREEN}✓ Node modules installed${NC}"
else
    echo -e "  ${GREEN}✓ Node modules OK${NC}"
fi

# Check .env
if [ ! -f "$DIR/.env" ]; then
    echo -e "  ${YELLOW}! .env not found — creating from template...${NC}"
    cp "$DIR/.env.example" "$DIR/.env"
    echo -e "  ${GREEN}✓ .env created (edit to add your API keys)${NC}"
else
    echo -e "  ${GREEN}✓ .env found${NC}"
fi

# Check frontend .env.local
if [ ! -f "$DIR/frontend/.env.local" ]; then
    echo -e "  ${YELLOW}! frontend/.env.local not found — creating...${NC}"
    echo "VITE_API_URL=http://localhost:8000" > "$DIR/frontend/.env.local"
    echo -e "  ${GREEN}✓ frontend/.env.local created${NC}"
else
    echo -e "  ${GREEN}✓ frontend/.env.local found${NC}"
fi

echo ""

# ----------------------------------------------------------
# 2. Start backend
# ----------------------------------------------------------
echo -e "${BLUE}[2/4] Starting backend on :8000...${NC}"

# Kill any existing process on port 8000
if lsof -i :8000 -t &>/dev/null; then
    echo -e "  ${YELLOW}Port 8000 in use — stopping existing process...${NC}"
    kill $(lsof -i :8000 -t) 2>/dev/null
    sleep 1
fi

cd "$DIR"
python3 run_api.py --port 8000 > /tmp/btc-trader-backend.log 2>&1 &
BACKEND_PID=$!
echo "$BACKEND_PID" > "$BACKEND_PID_FILE"

# Wait for backend to be ready
echo -ne "  Waiting for backend"
for i in $(seq 1 15); do
    if curl -s -o /dev/null http://127.0.0.1:8000/docs 2>/dev/null; then
        echo -e " ${GREEN}ready${NC}"
        break
    fi
    echo -n "."
    sleep 1
    if [ $i -eq 15 ]; then
        echo -e " ${RED}timeout${NC}"
        echo -e "  ${RED}Backend failed to start. Check /tmp/btc-trader-backend.log${NC}"
        tail -5 /tmp/btc-trader-backend.log 2>/dev/null
        exit 1
    fi
done

echo ""

# ----------------------------------------------------------
# 3. Start frontend
# ----------------------------------------------------------
echo -e "${BLUE}[3/4] Starting frontend on :3000...${NC}"

# Kill any existing process on port 3000
if lsof -i :3000 -t &>/dev/null; then
    echo -e "  ${YELLOW}Port 3000 in use — stopping existing process...${NC}"
    kill $(lsof -i :3000 -t) 2>/dev/null
    sleep 1
fi

cd "$DIR/frontend"
npx vite --port 3000 > /tmp/btc-trader-frontend.log 2>&1 &
FRONTEND_PID=$!
echo "$FRONTEND_PID" > "$FRONTEND_PID_FILE"

# Wait for frontend to be ready
echo -ne "  Waiting for frontend"
for i in $(seq 1 15); do
    if curl -s -o /dev/null http://localhost:3000 2>/dev/null; then
        echo -e " ${GREEN}ready${NC}"
        break
    fi
    echo -n "."
    sleep 1
    if [ $i -eq 15 ]; then
        echo -e " ${RED}timeout${NC}"
        echo -e "  ${RED}Frontend failed to start. Check /tmp/btc-trader-frontend.log${NC}"
        tail -5 /tmp/btc-trader-frontend.log 2>/dev/null
        exit 1
    fi
done

echo ""

# ----------------------------------------------------------
# 4. Done
# ----------------------------------------------------------
echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}  All services running!${NC}"
echo -e "${GREEN}=========================================${NC}"
echo ""
echo -e "  Frontend:   ${BLUE}http://localhost:3000${NC}"
echo -e "  Backend:    ${BLUE}http://localhost:8000${NC}"
echo -e "  API Docs:   ${BLUE}http://localhost:8000/docs${NC}"
echo ""
echo -e "  Login:      admin / changeme"
echo ""
echo -e "  Logs:       tail -f /tmp/btc-trader-backend.log"
echo -e "              tail -f /tmp/btc-trader-frontend.log"
echo ""
echo -e "  Stop:       ${YELLOW}./start_local.sh --stop${NC}"
echo ""
