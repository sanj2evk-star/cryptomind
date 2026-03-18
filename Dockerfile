###############################################################################
# Backend Dockerfile — BTC Paper Trader API
#
# Multi-stage build:
#   Stage 1: Install Python dependencies in a clean layer
#   Stage 2: Copy app code on top of deps (fast rebuilds)
#
# Usage:
#   docker build -t btc-trader-api .
#   docker run -p 8000:8000 --env-file .env btc-trader-api
###############################################################################

# ---------------------------------------------------------------------------
# Stage 1: Dependencies
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS deps

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 2: Application
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

WORKDIR /app

# Copy installed packages from deps stage
COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Copy application code
COPY app/ ./app/
COPY prompts/ ./prompts/
COPY run_api.py .

# Copy data templates (will be overwritten by volume mount)
COPY data/portfolio.json ./data/portfolio.json
COPY data/strategies.json ./data/strategies.json
COPY data/equity.csv ./data/equity.csv
COPY data/trades.csv ./data/trades.csv
COPY data/decisions.csv ./data/decisions.csv

# Create directories that may not exist yet
RUN mkdir -p data/cache data/charts data/reports

# Non-root user for security
RUN useradd --create-home appuser
RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/docs')" || exit 1

CMD ["python", "run_api.py", "--host", "0.0.0.0", "--port", "8000"]
