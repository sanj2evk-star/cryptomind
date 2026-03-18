#!/bin/bash
###############################################################################
# start.sh — Quick start for BTC Paper Trader
#
# Usage:
#   chmod +x start.sh
#   ./start.sh          # start with docker-compose
#   ./start.sh --build  # rebuild images first
#   ./start.sh --down   # stop everything
###############################################################################

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

# Check .env exists
if [ ! -f .env ]; then
    echo -e "${BLUE}Creating .env from template...${NC}"
    cp .env.production .env
    echo -e "${RED}Please edit .env and add your API keys, then re-run.${NC}"
    exit 1
fi

# Handle flags
case "${1}" in
    --down)
        echo -e "${BLUE}Stopping all services...${NC}"
        docker-compose down
        echo -e "${GREEN}Stopped.${NC}"
        exit 0
        ;;
    --build)
        echo -e "${BLUE}Building and starting services...${NC}"
        docker-compose up --build -d
        ;;
    *)
        echo -e "${BLUE}Starting services...${NC}"
        docker-compose up -d
        ;;
esac

echo ""
echo -e "${GREEN}BTC Paper Trader is running!${NC}"
echo ""
echo -e "  Frontend:  ${BLUE}http://localhost:3000${NC}"
echo -e "  API:       ${BLUE}http://localhost:8000${NC}"
echo -e "  API Docs:  ${BLUE}http://localhost:8000/docs${NC}"
echo ""
echo -e "  Logs:      docker-compose logs -f"
echo -e "  Stop:      ./start.sh --down"
echo ""
