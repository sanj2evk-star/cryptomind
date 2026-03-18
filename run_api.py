"""
run_api.py - Start the FastAPI server.

Launches the paper trading API on localhost:8000.
Validates environment variables before starting.

Usage:
    python run_api.py
    python run_api.py --port 9000
    python run_api.py --reload
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Ensure app/ is importable
APP_DIR = Path(__file__).resolve().parent / "app"
sys.path.insert(0, str(APP_DIR))

import uvicorn
from config import load_env, validate_env


def setup_logging() -> None:
    """Configure basic logging for the API server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="BTC Paper Trader API")
    default_port = int(os.getenv("PORT", "8000"))
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=default_port, help=f"Bind port (default: {default_port})")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    return parser.parse_args()


def main() -> None:
    """Load environment, validate, and start the server."""
    args = parse_args()
    setup_logging()
    logger = logging.getLogger("startup")

    # Load .env
    load_env()

    # Validate all environment variables
    logger.info("BTC Paper Trader API")
    logger.info("=" * 45)
    result = validate_env(logger)

    if not result["ok"]:
        logger.error("")
        logger.error("Fix the errors above before starting.")
        logger.error("Missing: %s", ", ".join(result["errors"]))
        logger.error("The server will start but some features may fail.")
        logger.error("")

    # Start server
    logger.info("")
    logger.info("Starting server on http://%s:%s", args.host, args.port)
    logger.info("API docs: http://%s:%s/docs", args.host, args.port)
    logger.info("")

    uvicorn.run(
        "app.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
