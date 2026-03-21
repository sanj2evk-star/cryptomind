"""
news_classifier.py — CryptoMind v7.4 Observer Core: News Classifier.

Rule-based, deterministic classification of raw headlines into:
    - relevance   (BTC/crypto relevance 0-1)
    - sentiment   (bullish / bearish / neutral)
    - impact      (high / medium / low / noise)
    - trust       (how much the source/framing can be trusted 0-1)
    - novelty     (is this a fresh angle or recycled hype? 0-1)
    - hype_score  (how much hype language is present 0-1)
    - bs_risk     (probability this is bullshit 0-1)
    - category    (regulation, adoption, hack, macro, whale, protocol, narrative, noise)
    - verdict     (interesting / watch / reject / noise)

Every verdict comes with a plain-english explanation.
No LLM calls. Fast, explainable, honest.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Keyword banks
# ---------------------------------------------------------------------------

_BULLISH = {
    "etf approved", "etf approval", "institutional", "adoption",
    "all-time high", "ath", "rally", "surge", "breakout", "partnership",
    "inflow", "accumulation", "halving", "upgrade", "integration",
    "milestone", "record high", "treasury", "reserve", "spot etf",
    "legal tender", "defi growth", "tvl increase", "staking reward",
}

_BEARISH = {
    "hack", "exploit", "rug pull", "rugpull", "scam", "fraud", "ban",
    "crash", "dump", "selloff", "sell-off", "crackdown", "sec lawsuit",
    "outflow", "liquidation", "bankruptcy", "insolvent", "delisted",
    "warning", "ponzi", "investigation", "sanctions", "freeze",
    "vulnerability", "critical bug", "51% attack",
}

_HYPE = {
    "to the moon", "100x", "1000x", "guaranteed", "hurry", "last chance",
    "don't miss", "once in a lifetime", "explosive", "skyrocket",
    "prediction 2030", "will reach", "could reach", "price prediction",
    "sponsored", "press release", "paid content", "promoted",
}

_NOISE = {
    "nft collection", "meme coin", "shib", "doge to the moon",
    "influencer", "tiktok", "youtube", "airdrop", "giveaway",
    "celebrity", "onlyfans",
}

_BTC_RELEVANT = {
    "bitcoin", "btc", "crypto market", "cryptocurrency", "digital asset",
    "blockchain", "mining", "halving", "satoshi", "lightning network",
    "taproot", "ordinals", "defi", "stablecoin", "tether", "usdt",
    "usdc", "binance", "coinbase", "kraken", "grayscale", "blackrock",
    "fidelity", "microstrategy", "el salvador", "fed", "fomc",
    "interest rate", "inflation", "cpi", "treasury yield", "dxy",
}

_HIGH_IMPACT = [
    r"sec\s+(approve|reject|sue|charge)",
    r"etf\s+(approve|reject|launch)",
    r"hack\w*\s+\$?\d+\s*(million|billion|m\b|b\b)",
    r"(ban|prohibit)\w*\s+(bitcoin|crypto|mining)",
    r"(fed|fomc|powell)\s+(rate|hike|cut|pause|pivot)",
    r"(blackrock|fidelity|jpmorgan|goldman)\s+(bitcoin|crypto|btc)",
    r"(crash|surge|rally)\s+\d+%",
    r"all[- ]time\s+(high|low)",
    r"billion\s+(inflow|outflow|liquidat)",
]

_CATEGORY_MAP = {
    "regulation":  ["sec", "regulation", "crackdown", "ban", "lawsuit", "compliance", "legal"],
    "adoption":    ["adoption", "institutional", "etf", "mainstream", "integration", "partnership"],
    "hack":        ["hack", "exploit", "vulnerability", "rug pull", "scam", "fraud"],
    "macro":       ["fed", "fomc", "inflation", "cpi", "interest rate", "treasury", "dxy", "dollar"],
    "whale":       ["whale", "large transfer", "billion", "accumulation", "wallet"],
    "protocol":    ["upgrade", "fork", "halving", "taproot", "merge", "layer 2", "lightning"],
    "market_move": ["crash", "surge", "rally", "breakout", "selloff", "liquidation", "ath"],
    "narrative":   ["narrative", "cycle", "supercycle", "prediction", "forecast"],
}

# ---------------------------------------------------------------------------
# Tone library — one-liners keyed by (verdict, flavour)
# ---------------------------------------------------------------------------

_TONES = {
    ("interesting", "high"):   "This looks real. Paying attention.",
    ("interesting", "medium"): "Interesting, but let's see how it develops.",
    ("watch", "relevant"):     "Watching only. Not enough to act on.",
    ("watch", "early"):        "Interesting, but too early.",
    ("watch", "thin"):         "Thin signal. Worth tracking, not trusting yet.",
    ("reject", "hype"):        "This looks loud, not deep.",
    ("reject", "recycled"):    "Recycled narrative. Ignoring.",
    ("reject", "irrelevant"):  "Not our world. Moving on.",
    ("noise", "garbage"):      "Pure noise. Already forgotten.",
    ("noise", "promo"):        "Smells like paid content. Hard pass.",
    ("unclear", "weak"):       "Can't read this clearly. Not enough signal to judge.",
    ("unclear", "mixed"):      "Conflicting signals. Sitting this one out.",
    ("unclear", "vague"):      "Too vague to classify with confidence. Skipping.",
}

# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

def classify(headline: str, body: str = "", source: str = "") -> dict:
    """Classify a single headline.  Returns a rich dict."""
    text = f"{headline} {body}".lower().strip()

    # --- relevance ---
    rel_hits = [kw for kw in _BTC_RELEVANT if kw in text]
    relevance = min(1.0, len(rel_hits) * 0.15)

    # --- sentiment ---
    bull = [kw for kw in _BULLISH if kw in text]
    bear = [kw for kw in _BEARISH if kw in text]
    if len(bull) > len(bear):
        sentiment, sent_strength = "bullish", min(1.0, len(bull) * 0.25)
    elif len(bear) > len(bull):
        sentiment, sent_strength = "bearish", min(1.0, len(bear) * 0.25)
    else:
        sentiment, sent_strength = "neutral", 0.0

    # --- hype & noise ---
    hype_hits  = [kw for kw in _HYPE if kw in text]
    noise_hits = [kw for kw in _NOISE if kw in text]
    hype_score = min(1.0, len(hype_hits) * 0.30)
    is_noisy   = len(noise_hits) >= 2 or (relevance == 0 and not bull and not bear)

    # --- trust (inverse of hype + noise) ---
    trust = max(0.1, 1.0 - hype_score * 0.5 - (0.3 if is_noisy else 0))

    # --- novelty (crude: shorter headlines with fewer hype words = more novel) ---
    novelty = max(0.1, 1.0 - hype_score - (0.2 if "prediction" in text else 0))

    # --- impact ---
    high_impact = any(re.search(p, text) for p in _HIGH_IMPACT)
    if high_impact:
        impact, impact_strength = "high", 0.85
    elif relevance >= 0.3 and (bull or bear):
        impact, impact_strength = "medium", 0.55
    elif relevance > 0:
        impact, impact_strength = "low", 0.30
    else:
        impact, impact_strength = "noise", 0.1

    # --- bs_risk ---
    bs_risk = min(1.0, hype_score * 0.5 + (0.3 if is_noisy else 0) + (0.2 if not rel_hits else 0))

    # --- category ---
    category = "general"
    for cat, keywords in _CATEGORY_MAP.items():
        if any(kw in text for kw in keywords):
            category = cat
            break

    # --- half_life (hours) —  how long this news matters ---
    half_life_map = {"high": 48, "medium": 12, "low": 4, "noise": 0.5}
    half_life = half_life_map.get(impact, 1)

    # --- classification confidence (how sure are we?) ---
    total_signals = len(bull) + len(bear) + len(hype_hits) + len(noise_hits) + len(rel_hits)
    mixed_signals = (len(bull) > 0 and len(bear) > 0)  # conflicting bull+bear
    weak_signal   = (total_signals <= 1 and impact not in ("high",) and relevance < 0.15)
    short_text    = len(text.split()) < 5

    # --- verdict + explanation ---
    if weak_signal and short_text:
        # Too little text, too few signals — be honest about uncertainty
        verdict, flavour = "unclear", "vague"
    elif mixed_signals and impact != "high" and not is_noisy:
        # Bull and bear signals cancel out — conflicting
        verdict, flavour = "unclear", "mixed"
    elif is_noisy or impact == "noise":
        if hype_hits:
            verdict, flavour = "noise", "promo"
        else:
            verdict, flavour = "noise", "garbage"
    elif hype_score > 0.5:
        verdict, flavour = "reject", "hype"
    elif relevance == 0 and impact != "high":
        verdict, flavour = "reject", "irrelevant"
    elif impact == "high":
        verdict, flavour = "interesting", "high"
    elif impact == "medium":
        verdict, flavour = "interesting", "medium"
    elif relevance > 0 and novelty > 0.4:
        verdict, flavour = "watch", "relevant"
    elif relevance > 0:
        verdict, flavour = "watch", "thin"
    elif weak_signal:
        # Relevant-ish but genuinely hard to read
        verdict, flavour = "unclear", "weak"
    else:
        verdict, flavour = "reject", "recycled"

    explanation = _TONES.get((verdict, flavour), "Noted.")

    # --- impact_bias (for news_events table compatibility) ---
    impact_bias = sentiment if sentiment != "neutral" else "mixed"

    # --- volatility_warning ---
    vol_warning = impact == "high" and category in ("hack", "market_move", "macro")

    return {
        "headline":          headline,
        "source":            source,
        "category":          category,
        "sentiment":         sentiment,
        "sentiment_strength": round(sent_strength, 2),
        "impact":            impact,
        "impact_strength":   round(impact_strength, 2),
        "impact_bias":       impact_bias,
        "relevance":         round(relevance, 2),
        "trust":             round(trust, 2),
        "novelty":           round(novelty, 2),
        "hype_score":        round(hype_score, 2),
        "bs_risk":           round(bs_risk, 2),
        "half_life_hours":   half_life,
        "vol_warning":       vol_warning,
        "verdict":           verdict,
        "explanation":       explanation,
        "btc_relevant":      relevance > 0,
        "bullish_signals":   bull[:3],
        "bearish_signals":   bear[:3],
        "classified_at":     datetime.now(timezone.utc).isoformat(),
    }


def classify_batch(headlines: list[dict]) -> list[dict]:
    """Classify a list of headline dicts (from news_ingestor)."""
    results = []
    for it in headlines:
        c = classify(
            headline=it.get("headline", ""),
            body=it.get("body", ""),
            source=it.get("source", ""),
        )
        c["original_timestamp"] = it.get("timestamp")
        c["source_name"]        = it.get("source_name", it.get("source", ""))
        c["url"]                = it.get("url")
        results.append(c)
    return results


def summarise_batch(classified: list[dict]) -> dict:
    """Quick stats over a classified batch."""
    n = len(classified)
    if n == 0:
        return {"total": 0}
    verdicts   = {}
    sentiments = {}
    for c in classified:
        verdicts[c["verdict"]]     = verdicts.get(c["verdict"], 0) + 1
        sentiments[c["sentiment"]] = sentiments.get(c["sentiment"], 0) + 1
    return {
        "total":       n,
        "verdicts":    verdicts,
        "sentiments":  sentiments,
        "interesting": verdicts.get("interesting", 0),
        "watched":     verdicts.get("watch", 0),
        "rejected":    verdicts.get("reject", 0),
        "noise":       verdicts.get("noise", 0),
        "unclear":     verdicts.get("unclear", 0),
    }
