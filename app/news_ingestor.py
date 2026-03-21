"""
news_ingestor.py — CryptoMind v7.4 Observer Core: News Ingestion.

Fetches crypto news from free public APIs and normalises into a standard
format.  Feeds the existing news_events table, then hands off to
news_classifier for analysis.

Sources:
    1. CryptoCompare  (free, no key)
    2. CoinGecko trending coins
    3. Alternative.me  Fear & Greed Index

This module does NOT make trading decisions.
It is a calm, periodic observer: fetch → normalise → store → hand off.
"""

from __future__ import annotations

import json
import time
import threading
from datetime import datetime, timezone
from typing import Optional
import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_FETCH_INTERVAL = 300        # 5 minutes between fetches
_MAX_HEADLINES  = 50         # max headlines in memory cache
_USER_AGENT     = "CryptoMind/7.4 Observer"

# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------

_lock              = threading.Lock()
_cached_news: list[dict] = []
_fear_greed: dict  = {}
_last_fetch: float = 0
_last_success: float = 0       # timestamp of last successful fetch
_errors: list[str] = []
_source_status: dict = {       # per-source health tracking
    "cryptocompare":     {"ok": False, "last_ok": 0, "fails": 0},
    "coingecko_trending": {"ok": False, "last_ok": 0, "fails": 0},
    "fear_greed":        {"ok": False, "last_ok": 0, "fails": 0},
}

# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _http_get(url: str, timeout: int = 10):
    """Simple GET → parsed JSON.  Returns None on any failure."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        _errors.append(f"{datetime.now(timezone.utc).isoformat()[:19]}: {url[:50]}… → {e}")
        if len(_errors) > 20:
            _errors.pop(0)
        return None

# ---------------------------------------------------------------------------
# Source fetchers
# ---------------------------------------------------------------------------

def _fetch_cryptocompare() -> list[dict]:
    data = _http_get(
        "https://min-api.cryptocompare.com/data/v2/news/?lang=EN&sortOrder=latest"
    )
    if not data or "Data" not in data:
        _source_status["cryptocompare"]["fails"] += 1
        _source_status["cryptocompare"]["ok"] = False
        return []
    _source_status["cryptocompare"]["ok"] = True
    _source_status["cryptocompare"]["last_ok"] = time.time()
    _source_status["cryptocompare"]["fails"] = 0
    items = []
    for a in data["Data"][:15]:
        ts = datetime.fromtimestamp(
            a.get("published_on", 0), tz=timezone.utc
        ).isoformat() if a.get("published_on") else datetime.now(timezone.utc).isoformat()
        items.append({
            "headline":    a.get("title", ""),
            "body":        (a.get("body", "") or "")[:400],
            "source":      "cryptocompare",
            "source_name": a.get("source_info", {}).get("name", "unknown"),
            "timestamp":   ts,
            "url":         a.get("url"),
            "categories":  (a.get("categories") or "").lower(),
            "tags":        a.get("tags", ""),
        })
    return items


def _fetch_coingecko_trending() -> list[dict]:
    data = _http_get("https://api.coingecko.com/api/v3/search/trending")
    if not data or "coins" not in data:
        _source_status["coingecko_trending"]["fails"] += 1
        _source_status["coingecko_trending"]["ok"] = False
        return []
    _source_status["coingecko_trending"]["ok"] = True
    _source_status["coingecko_trending"]["last_ok"] = time.time()
    _source_status["coingecko_trending"]["fails"] = 0
    items = []
    for coin in data["coins"][:5]:
        item = coin.get("item", {})
        items.append({
            "headline":  f"{item.get('name','?')} ({item.get('symbol','?')}) trending on CoinGecko",
            "body":      "",
            "source":    "coingecko_trending",
            "source_name": "CoinGecko",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "url":       None,
            "categories": "trending",
            "tags":      item.get("symbol", ""),
        })
    return items


def _fetch_fear_greed() -> dict:
    data = _http_get("https://api.alternative.me/fng/?limit=2")
    if not data or "data" not in data:
        _source_status["fear_greed"]["fails"] += 1
        _source_status["fear_greed"]["ok"] = False
        return {}
    _source_status["fear_greed"]["ok"] = True
    _source_status["fear_greed"]["last_ok"] = time.time()
    _source_status["fear_greed"]["fails"] = 0
    entries = data["data"]
    if not entries:
        return {}
    cur  = entries[0]
    prev = entries[1] if len(entries) > 1 else {}
    val  = int(cur.get("value", 50))
    pval = int(prev.get("value", 50)) if prev else val
    return {
        "value":          val,
        "classification": cur.get("value_classification", "Neutral"),
        "previous_value": pval,
        "direction":      "rising" if val > pval else "falling" if val < pval else "flat",
        "timestamp":      datetime.now(timezone.utc).isoformat(),
    }

# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def fetch_all(force: bool = False) -> dict:
    """Fetch from all sources (rate-limited).

    Returns dict with keys: headlines, fear_greed, fetched, cached_count.
    """
    global _cached_news, _fear_greed, _last_fetch

    now = time.time()
    if not force and (now - _last_fetch) < _FETCH_INTERVAL and _cached_news:
        return {
            "headlines":    _cached_news,
            "fear_greed":   _fear_greed,
            "fetched":      False,
            "cached_count": len(_cached_news),
            "stale":        _is_stale(),
        }

    with _lock:
        # double-check
        if not force and (time.time() - _last_fetch) < _FETCH_INTERVAL and _cached_news:
            return {
                "headlines":    _cached_news,
                "fear_greed":   _fear_greed,
                "fetched":      False,
                "cached_count": len(_cached_news),
                "stale":        _is_stale(),
            }

        items: list[dict] = []
        try:   items.extend(_fetch_cryptocompare())
        except Exception: pass
        try:   items.extend(_fetch_coingecko_trending())
        except Exception: pass
        try:   _fear_greed = _fetch_fear_greed()
        except Exception: pass

        # Deduplicate by headline
        seen: set[str] = set()
        deduped: list[dict] = []
        for it in items:
            key = it.get("headline", "").strip().lower()[:80]
            if key and key not in seen:
                seen.add(key)
                deduped.append(it)
        deduped.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        # Only replace cache if we got something — preserve last-good state
        if deduped:
            _cached_news = deduped[:_MAX_HEADLINES]
            _last_success = time.time()
        _last_fetch  = time.time()

    # Persist raw headlines to existing news_events table
    if _cached_news:
        _persist_to_news_events(_cached_news)

    return {
        "headlines":    _cached_news,
        "fear_greed":   _fear_greed,
        "fetched":      True,
        "cached_count": len(_cached_news),
        "stale":        _is_stale(),
    }


def _persist_to_news_events(items: list[dict]) -> None:
    """Write raw headlines into the existing news_events table."""
    try:
        import db as v7db
        with v7db.get_db() as conn:
            for it in items[:20]:
                headline = it.get("headline", "")
                # skip if already stored (dedupe by headline)
                existing = conn.execute(
                    "SELECT news_id FROM news_events WHERE headline = ? LIMIT 1",
                    (headline,)
                ).fetchone()
                if existing:
                    continue
                conn.execute(
                    """INSERT INTO news_events
                       (timestamp, headline, source, event_type,
                        market_scope, learning_status)
                       VALUES (?, ?, ?, ?, ?, 'pending')""",
                    (
                        it.get("timestamp", datetime.now(timezone.utc).isoformat()),
                        headline,
                        it.get("source", ""),
                        it.get("categories", "general"),
                        "crypto",
                    ),
                )
    except Exception:
        pass  # non-fatal


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------

def _is_stale() -> bool:
    """News is stale if last successful fetch was >15 minutes ago."""
    if _last_success == 0:
        return True
    return (time.time() - _last_success) > 900  # 15 min


def get_headlines(limit: int = 20) -> list[dict]:
    return _cached_news[:limit]

def get_fear_greed() -> dict:
    return _fear_greed

def is_stale() -> bool:
    return _is_stale()

def get_status() -> dict:
    now = time.time()
    return {
        "cached_headlines":   len(_cached_news),
        "last_fetch_ago_s":   round(now - _last_fetch, 1) if _last_fetch else None,
        "last_success_ago_s": round(now - _last_success, 1) if _last_success else None,
        "stale":              _is_stale(),
        "fear_greed":         _fear_greed,
        "source_health":      dict(_source_status),
        "recent_errors":      _errors[-5:],
    }
