"""
Sentiment analysis service (Section 25).

Each news event should have:
    Relevance, Credibility, Sentiment, Magnitude, Confidence

Sentiment is not directly interpreted as a buy/sell signal.
Instead: News → Event → Fundamental Impact → Market Impact → Investment Impact
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)


# Simple keyword-based sentiment analysis
# In production, this would use an NLP model or LLM
POSITIVE_KEYWORDS = [
    "beat", "surpass", "exceed", "strong", "growth", "profit", "gain",
    "upgrade", "bullish", "positive", "record", "high", "raise", "boost",
    "opportunity", "optimistic", "recovery", "expand", "increase", "outperform",
]

NEGATIVE_KEYWORDS = [
    "miss", "fall", "decline", "loss", "weak", "downgrade", "bearish",
    "negative", "low", "cut", "reduce", "risk", "threat", "lawsuit",
    "investigation", "regulatory", "plunge", "drop", "fear", "concern",
    "warning", "caution", "trouble", "crisis", "recession",
]


class SentimentAnalyzer:
    """
    Analyzes news sentiment and impact.

    Section 25: Sentiment is not directly interpreted as a buy/sell signal.
    """

    @staticmethod
    def analyze(text: str) -> dict[str, float]:
        """
        Analyze text sentiment.

        Returns:
            sentiment: -1 to 1 (negative to positive)
            magnitude: 0 to 1 (intensity)
            confidence: 0 to 1
        """
        text_lower = text.lower()
        words = text_lower.split()

        positive_count = sum(1 for w in words if any(k in w for k in POSITIVE_KEYWORDS))
        negative_count = sum(1 for w in words if any(k in w for k in NEGATIVE_KEYWORDS))

        total = positive_count + negative_count
        if total == 0:
            return {"sentiment": 0.0, "magnitude": 0.0, "confidence": 0.3}

        sentiment = (positive_count - negative_count) / total
        magnitude = min(1.0, total / 10)
        confidence = min(1.0, 0.5 + total * 0.05)

        return {
            "sentiment": round(sentiment, 4),
            "magnitude": round(magnitude, 4),
            "confidence": round(confidence, 4),
        }

    @staticmethod
    def assess_relevance(text: str, ticker: str, company_name: str | None = None) -> float:
        """Assess how relevant a news item is to a specific company."""
        text_lower = text.lower()
        ticker_lower = ticker.lower()

        if ticker_lower in text_lower:
            return 0.95
        if company_name and company_name.lower() in text_lower:
            return 0.90

        # Check for partial company name
        if company_name:
            words = company_name.lower().split()
            matches = sum(1 for w in words if w in text_lower and len(w) > 3)
            if matches > 0:
                return min(0.8, 0.5 + matches * 0.1)

        return 0.3

    @staticmethod
    def assess_credibility(source: str) -> float:
        """Assess source credibility (0-1)."""
        high_credibility = {"SEC", "reuters", "bloomberg", "wsj", "ft.com", "cnbc"}
        medium_credibility = {"massive", "finnhub", "marketwatch", "seekingalpha"}

        source_lower = source.lower()
        if any(s in source_lower for s in high_credibility):
            return 0.95
        if any(s in source_lower for s in medium_credibility):
            return 0.80
        return 0.60

    def analyze_news(self, text: str, source: str, ticker: str, company_name: str | None = None) -> dict[str, float]:
        """Full news impact analysis (Section 25)."""
        sentiment_result = self.analyze(text)
        relevance = self.assess_relevance(text, ticker, company_name)
        credibility = self.assess_credibility(source)

        # Impact score combines sentiment magnitude with relevance
        impact = sentiment_result["magnitude"] * relevance

        # Overall confidence
        confidence = (credibility * 0.4 + relevance * 0.3 + sentiment_result["confidence"] * 0.3)

        return {
            "sentiment": sentiment_result["sentiment"],
            "magnitude": sentiment_result["magnitude"],
            "relevance_score": relevance,
            "credibility_score": credibility,
            "impact_score": round(impact, 4),
            "confidence_score": round(confidence, 4),
        }