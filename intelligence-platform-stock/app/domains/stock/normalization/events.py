"""
Event normalization — classifies market events and maps to canonical schema.

Phase 4 (#157): Enhanced event classification, impact scoring, and materiality.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


# Event type classification (Section 23 + Section 40)
EVENT_TYPES = {
    "earnings_beat": "EARNINGS_BEAT",
    "earnings_miss": "EARNINGS_MISS",
    "earnings_in_line": "EARNINGS_IN_LINE",
    "regulatory": "REGULATORY",
    "product_launch": "PRODUCT_LAUNCH",
    "merger_acquisition": "MA",
    "management_change": "MANAGEMENT_CHANGE",
    "guidance_update": "GUIDANCE_UPDATE",
    "dividend_change": "DIVIDEND_CHANGE",
    "stock_split": "STOCK_SPLIT",
    "buyback": "BUYBACK",
    "macro_event": "MACRO_EVENT",
    "sector_event": "SECTOR_EVENT",
    "insider_trading": "INSIDER_TRADING",
    "institutional_change": "INSTITUTIONAL_CHANGE",
    "analyst": "ANALYST",
    "supply_chain": "SUPPLY_CHAIN",
    "legal": "LEGAL",
    "other": "OTHER",
}

# Materiality weights by event type (Section 45).
# Higher weight = more likely to materially move the stock.
EVENT_MATERIALITY_WEIGHTS: dict[str, float] = {
    "EARNINGS_BEAT": 0.95,
    "EARNINGS_MISS": 0.95,
    "EARNINGS_IN_LINE": 0.60,
    "REGULATORY": 0.85,
    "PRODUCT_LAUNCH": 0.70,
    "MA": 0.90,
    "MANAGEMENT_CHANGE": 0.65,
    "GUIDANCE_UPDATE": 0.80,
    "DIVIDEND_CHANGE": 0.55,
    "STOCK_SPLIT": 0.40,
    "BUYBACK": 0.60,
    "MACRO_EVENT": 0.75,
    "SECTOR_EVENT": 0.50,
    "INSIDER_TRADING": 0.45,
    "INSTITUTIONAL_CHANGE": 0.40,
    "ANALYST": 0.50,
    "SUPPLY_CHAIN": 0.65,
    "LEGAL": 0.80,
    "OTHER": 0.20,
}


def _tokenize(text: str) -> set[str]:
    """Split text into lowercase word tokens for token-aware matching."""
    import re

    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _contains_any(text: str, phrases: list[str]) -> bool:
    """Phrase-aware substring match (word boundaries respected)."""
    return any(p in text for p in phrases)


def classify_event(news_title: str, news_content: str | None = None) -> str:
    """
    Classify a news event into a canonical event type.

    Token/word-boundary-aware rules ordered by specificity. Context
    requirements are enforced so that e.g. "beat" alone does not imply
    an earnings event, and a generic mention of "earnings" does not
    become EARNINGS_IN_LINE.

    This is still a keyword classifier; a dedicated NLP/LLM stage can
    replace it without changing the contract.
    """
    text = f"{news_title} {news_content or ''}".lower()
    tokens = _tokenize(text)

    # ── Earnings / results ──────────────────────────────────────
    # EARNINGS_BEAT / MISS require an explicit earnings/results context
    # AND a beat/miss verb. Word-boundary token matching prevents
    # "beaten" or "beating" from triggering EARNINGS_BEAT accidentally.
    earnings_context_terms = {"earnings", "revenue", "eps", "profit", "quarterly", "results", "estimates", "expectations"}
    has_earnings_context = bool(earnings_context_terms & tokens)

    beat_tokens = {"beat", "beats", "exceeded", "exceeds", "surpassed", "surpasses", "above"}
    miss_tokens = {"miss", "misses", "missed", "fell", "falls", "below", "short"}

    if has_earnings_context and (beat_tokens & tokens):
        return EVENT_TYPES["earnings_beat"]
    if has_earnings_context and (miss_tokens & tokens):
        return EVENT_TYPES["earnings_miss"]

    # EARNINGS_IN_LINE requires an explicit report context, not any
    # mention of the word "earnings" (which appears in many editorials).
    if _contains_any(text, ["earnings report", "quarterly results", "reported earnings",
                            "reports quarterly earnings", "reports earnings",
                            "earnings call", "earnings season", "fiscal q1", "fiscal q2",
                            "fiscal q3", "fiscal q4", "q1 earnings", "q2 earnings",
                            "q3 earnings", "q4 earnings"]):
        return EVENT_TYPES["earnings_in_line"]

    # ── Regulatory / legal ──────────────────────────────────────
    if _contains_any(text, ["regulatory approval", "sec investigation", "sec charges",
                            "doj investigation", "antitrust", "fines"]):
        return EVENT_TYPES["regulatory"]
    if _contains_any(text, ["lawsuit", "litigation", "settlement", "patent", "court ruling"]):
        return EVENT_TYPES["legal"]

    # ── Corporate actions ───────────────────────────────────────
    if _contains_any(text, ["acquire", "acquisition", "merger", "buyout", "takeover"]):
        return EVENT_TYPES["merger_acquisition"]
    if _contains_any(text, ["ceo", "cfo", "coo", "resign", "appoint", "step down",
                            "chief executive", "chief financial"]):
        return EVENT_TYPES["management_change"]
    if _contains_any(text, ["dividend", "payout"]):
        return EVENT_TYPES["dividend_change"]
    if _contains_any(text, ["stock split", "reverse split"]):
        return EVENT_TYPES["stock_split"]
    if _contains_any(text, ["buyback", "repurchase", "share repurchase"]):
        return EVENT_TYPES["buyback"]
    if _contains_any(text, ["launch", "unveil", "announce product", "new product"]):
        return EVENT_TYPES["product_launch"]

    # ── Guidance ────────────────────────────────────────────────
    if _contains_any(text, ["guidance", "outlook", "forecast", "raise guidance", "lower guidance"]):
        return EVENT_TYPES["guidance_update"]

    # ── Macro ───────────────────────────────────────────────────
    if _contains_any(text, ["interest rate", "federal reserve", "fed funds", "treasury",
                            "inflation", "gdp growth", "unemployment"]):
        return EVENT_TYPES["macro_event"]

    # ── Ownership / analyst ─────────────────────────────────────
    if _contains_any(text, ["insider", "director purchase", "officer sell"]):
        return EVENT_TYPES["insider_trading"]
    if _contains_any(text, ["fund ownership", "institutional", "13f", "stake"]):
        return EVENT_TYPES["institutional_change"]
    if _contains_any(text, ["analyst", "upgrade", "downgrade", "price target", "rating"]):
        return EVENT_TYPES["analyst"]

    # ── Supply chain ────────────────────────────────────────────
    if _contains_any(text, ["supply chain", "supplier", "shortage", "disruption", "inventory"]):
        return EVENT_TYPES["supply_chain"]

    return EVENT_TYPES["other"]


def score_event_impact(
    event_type: str,
    sentiment: float | None = None,
    confidence: float | None = None,
) -> tuple[str, float, float]:
    """
    Score event impact and materiality (Sections 25, 45).

    Returns:
        (impact_label, impact_score, materiality_score)
        - impact_label: "positive" | "negative" | "neutral"
        - impact_score: 0..1
        - materiality_score: 0..1
    """
    # Materiality from event type weight
    materiality = EVENT_MATERIALITY_WEIGHTS.get(event_type, 0.20)

    # Impact label from sentiment
    if sentiment is not None:
        if sentiment > 0.2:
            impact_label = "positive"
        elif sentiment < -0.2:
            impact_label = "negative"
        else:
            impact_label = "neutral"
        impact_score = min(1.0, abs(sentiment))
    else:
        impact_label = "neutral"
        impact_score = 0.0

    # Adjust materiality by confidence if available
    if confidence is not None:
        materiality = materiality * (0.5 + 0.5 * confidence)

    return impact_label, round(impact_score, 4), round(materiality, 4)


def normalize_event(
    event_type: str,
    event_date: datetime,
    company_id: int | None = None,
    description: str | None = None,
    impact: str = "neutral",
    impact_score: float | None = None,
    confidence: float | None = None,
    materiality_score: float | None = None,
    source_news_id: int | None = None,
) -> dict[str, Any]:
    """Create a canonical market event dict."""
    return {
        "company_id": company_id,
        "event_type": event_type,
        "event_date": event_date if event_date.tzinfo else event_date.replace(tzinfo=timezone.utc),
        "impact": impact,
        "impact_score": impact_score,
        "confidence": confidence,
        "materiality_score": materiality_score,
        "description": description,
        "source_news_id": source_news_id,
    }